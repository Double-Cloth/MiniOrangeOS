#!/usr/bin/env python3
"""运行无界面 QEMU，解析 COM1 测试协议并可靠清理本次进程树。"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import secrets
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

from qemu_paths import BoundBuild, BoundFile, BoundLog, PathBoundaryError


PASS_LINE = b"[TEST] all PASS"
SUITE_BEGIN = re.compile(rb"^\[TEST\] suite=([A-Za-z0-9_.-]+) begin$")
SUITE_PASS = re.compile(rb"^\[TEST\] suite=([A-Za-z0-9_.-]+) PASS$")
CASE_PASS = re.compile(rb"^\[TEST\] case=([A-Za-z0-9_.-]+) PASS$")
READ_SIZE = 65536
LINE_LIMIT = 262144
TERMINATE_GRACE_SECONDS = 0.35
PR_SET_CHILD_SUBREAPER = 36
EXPECTED_DEBUG_EXIT_CODE = 33


class RunnerError(Exception):
    """表示 QEMU runner 的输入或运行错误。"""


class BoundedTail:
    """只保留串口输出末尾，确保最终协议不会被早期噪声挤掉。"""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._data = bytearray()

    def append(self, data: bytes) -> None:
        if len(data) >= self._limit:
            self._data[:] = data[-self._limit :]
            return
        overflow = len(self._data) + len(data) - self._limit
        if overflow > 0:
            del self._data[:overflow]
        self._data.extend(data)

    def bytes(self) -> bytes:
        return bytes(self._data)


class ProtocolParser:
    """严格验证 suite/case/总终态的顺序和完整换行。"""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._active_suite: bytes | None = None
        self._case_passes = 0
        self._completed_suites = 0
        self.passed = False
        self.failed = False
        self.failure_reason = ""

    def feed(self, data: bytes) -> None:
        self._pending.extend(data)
        while True:
            newline = self._pending.find(b"\n")
            if newline < 0:
                if len(self._pending) > LINE_LIMIT:
                    if self._pending.startswith(b"[TEST]"):
                        self._fail("TEST 行超过长度限制")
                    del self._pending[:-LINE_LIMIT]
                return
            line = bytes(self._pending[:newline]).rstrip(b"\r")
            del self._pending[: newline + 1]
            self._parse_line(line)

    def finish(self) -> None:
        if self._pending.startswith(b"[TEST]"):
            self._fail("TEST 行缺少换行终止符")
        self._pending.clear()

    def _fail(self, reason: str) -> None:
        if not self.failed:
            self.failure_reason = reason
        self.failed = True

    def _parse_line(self, line: bytes) -> None:
        if not line.startswith(b"[TEST]"):
            return
        if self.passed:
            self._fail("总 PASS 后仍出现 TEST 行")
            return
        if b"FAIL" in line.split():
            self._fail("协议报告 FAIL")
            return

        match = SUITE_BEGIN.fullmatch(line)
        if match is not None:
            if self._active_suite is not None:
                self._fail("suite begin 嵌套或乱序")
                return
            self._active_suite = match.group(1)
            self._case_passes = 0
            return

        match = CASE_PASS.fullmatch(line)
        if match is not None:
            if self._active_suite is None:
                self._fail("case PASS 位于 suite 之外")
                return
            self._case_passes += 1
            return

        match = SUITE_PASS.fullmatch(line)
        if match is not None:
            if self._active_suite != match.group(1):
                self._fail("suite PASS 名称不匹配或乱序")
                return
            if self._case_passes < 1:
                self._fail("suite 没有成功 case")
                return
            self._active_suite = None
            self._case_passes = 0
            self._completed_suites += 1
            return

        if line == PASS_LINE:
            if self._active_suite is not None or self._completed_suites < 1:
                self._fail("总 PASS 之前存在未完成或缺失的 suite")
                return
            self.passed = True
            return

        self._fail("未知或格式错误的 TEST 行")


def _positive_integer(value: str, name: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise RunnerError(f"{name} 必须是正整数")
    result = int(value, 10)
    if result <= 0:
        raise RunnerError(f"{name} 必须大于零")
    return result


def _safe_text(value: str, name: str) -> str:
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise RunnerError(f"{name} 为空或含控制字符")
    return value


def _atomic_log(log: BoundLog, content: bytes) -> None:
    temporary = f".{log.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    log.write_atomic(content, temporary)


def _test_hook(stage: str) -> None:
    if os.environ.get("MINIOS_TEST_MODE") != "1":
        return
    hook = os.environ.get("MINIOS_QEMU_TEST_HOOK")
    if not hook:
        return
    subprocess.run([_safe_text(hook, "测试 hook"), stage], check=True)


def _enable_subreaper() -> None:
    """让孤儿后代回到 runner，避免容器 PID 1 不及时回收僵尸。"""

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    prctl.restype = ctypes.c_int
    if prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise RunnerError(
            f"无法启用 CHILD_SUBREAPER：{os.strerror(error_number)}"
        )


def _log_test_hook(stage: str, temporary_name: str) -> None:
    if os.environ.get("MINIOS_TEST_MODE") != "1":
        return
    hook = os.environ.get("MINIOS_QEMU_LOG_TEST_HOOK")
    if not hook:
        return
    subprocess.run(
        [_safe_text(hook, "日志测试 hook"), stage, temporary_name],
        check=True,
    )


def _leader_exited(process_id: int) -> bool:
    """观察主进程退出但不回收，保持 PID/PGID 身份直到组清理完成。"""

    result = os.waitid(
        os.P_PID,
        process_id,
        os.WEXITED | os.WNOHANG | os.WNOWAIT,
    )
    return result is not None


def _group_processes(group: int) -> dict[int, tuple[str, int]]:
    """返回本组 PID 到 (state, ppid) 的瞬时快照。"""

    members: dict[int, tuple[str, int]] = {}
    try:
        entries = os.scandir("/proc")
    except OSError as error:
        raise RunnerError(f"无法枚举 QEMU 进程组：{error}") from error
    with entries:
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                stat_line = Path(entry.path, "stat").read_text(
                    encoding="ascii", errors="strict"
                )
                fields = stat_line[stat_line.rfind(")") + 2 :].split()
                state = fields[0]
                parent = int(fields[1])
                process_group = int(fields[2])
            except (OSError, ValueError, IndexError, UnicodeError):
                continue
            if process_group == group:
                members[int(entry.name)] = (state, parent)
    return members


def _reap_adopted_group_zombies(group: int, leader: int) -> None:
    """只回收已由 subreaper 收养的本组僵尸，leader 始终留到最后。"""

    runner = os.getpid()
    for process_id, (state, parent) in _group_processes(group).items():
        if process_id == leader or state != "Z" or parent != runner:
            continue
        try:
            os.waitpid(process_id, os.WNOHANG)
        except ChildProcessError:
            continue


def _signal_group(group: int, signum: int) -> None:
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def _cleanup(process: subprocess.Popen[bytes]) -> None:
    """保留未回收 leader 锚点，只清理本次新建的会话进程组。"""

    group = process.pid
    try:
        actual_group = os.getpgid(process.pid)
    except ProcessLookupError as error:
        raise RunnerError("QEMU leader 在清理前已被意外回收") from error
    if actual_group != group:
        raise RunnerError("QEMU 未处于 runner 创建的独立进程组")

    _signal_group(group, signal.SIGTERM)
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    empty_observations = 0
    while time.monotonic() < deadline:
        _reap_adopted_group_zombies(group, process.pid)
        leader_done = _leader_exited(process.pid)
        descendants = set(_group_processes(group)) - {process.pid}
        if leader_done and not descendants:
            empty_observations += 1
            if empty_observations >= 3:
                break
        else:
            empty_observations = 0
        time.sleep(0.01)

    if not _leader_exited(process.pid) or set(_group_processes(group)) - {
        process.pid
    }:
        _signal_group(group, signal.SIGKILL)

    disappearance_deadline = time.monotonic() + 2.0
    empty_observations = 0
    while time.monotonic() < disappearance_deadline:
        _reap_adopted_group_zombies(group, process.pid)
        if _leader_exited(process.pid) and not (
            set(_group_processes(group)) - {process.pid}
        ):
            empty_observations += 1
            if empty_observations >= 3:
                break
        else:
            empty_observations = 0
        time.sleep(0.01)

    _reap_adopted_group_zombies(group, process.pid)
    remaining = set(_group_processes(group)) - {process.pid}
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        _signal_group(group, signal.SIGKILL)
        process.wait(timeout=1.0)
    if remaining:
        raise RunnerError(f"QEMU 进程组仍有未清理成员：{sorted(remaining)}")

def _drain_serial(
    stream: object, capture: BoundedTail, parser: ProtocolParser
) -> None:
    descriptor = stream.fileno()  # type: ignore[attr-defined]
    while True:
        try:
            data = os.read(descriptor, READ_SIZE)
        except BlockingIOError:
            return
        if not data:
            return
        capture.append(data)
        parser.feed(data)


def _command(qemu: str, image: str) -> list[str]:
    image_path = os.path.abspath(image)
    if any(character in image_path for character in (",", "\r", "\n", "\x00")):
        raise RunnerError("镜像路径含 QEMU drive 不支持的字符")
    if not os.path.isfile(image_path):
        raise RunnerError(f"镜像不是普通文件：{image}")
    return [
        _safe_text(qemu, "QEMU 可执行文件"),
        "-machine",
        "pc,accel=tcg",
        "-m",
        "32M",
        "-drive",
        f"file={image_path},format=raw,if=ide,index=0,media=disk",
        "-boot",
        "c",
        "-display",
        "none",
        "-monitor",
        "none",
        "-serial",
        "stdio",
        "-no-reboot",
        "-no-shutdown",
        "-device",
        "isa-debug-exit,iobase=0xf4,iosize=0x04",
    ]


def _run_bound(
    arguments: argparse.Namespace, image: BoundFile, log: BoundLog
) -> int:
    timeout = _positive_integer(arguments.timeout, "timeout")
    maximum = _positive_integer(arguments.max_log_bytes, "max-log-bytes")
    command = _command(arguments.qemu, image.proc_path)
    capture = BoundedTail(maximum)
    parser = ProtocolParser()
    interrupted = 0
    leader_completed = False
    process: subprocess.Popen[bytes] | None = None
    hook_error: BaseException | None = None
    cleanup_error: BaseException | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = signum

    previous = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        _enable_subreaper()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            bufsize=0,
            pass_fds=(image.descriptor,),
        )
        _test_hook("after-spawn")
        selector = selectors.DefaultSelector()
        assert process.stdout is not None
        assert process.stderr is not None
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stderr.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, True)
        selector.register(process.stderr, selectors.EVENT_READ, False)
        deadline = time.monotonic() + timeout
        try:
            while not interrupted:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                events = selector.select(min(remaining, 0.1))
                for key, _mask in events:
                    try:
                        data = os.read(key.fileobj.fileno(), READ_SIZE)
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data:
                        capture.append(data)
                        parser.feed(data)
                if _leader_exited(process.pid):
                    leader_completed = True
                    break
        finally:
            selector.close()
    except (OSError, subprocess.SubprocessError) as error:
        raise RunnerError(f"无法运行 QEMU：{error}") from error
    finally:
        if process is not None:
            try:
                _test_hook("before-cleanup")
            except BaseException as error:  # 测试 hook 失败也必须继续清理。
                hook_error = error
            try:
                _cleanup(process)
            except BaseException as error:
                cleanup_error = error
            assert process.stdout is not None
            try:
                _drain_serial(process.stdout, capture, parser)
            except OSError as error:
                cleanup_error = cleanup_error or error
            process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            try:
                _test_hook("after-cleanup")
            except BaseException as error:
                hook_error = hook_error or error
        parser.finish()
        _atomic_log(log, capture.bytes())
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    if interrupted:
        print(f"QEMU 测试被信号 {interrupted} 中断", file=sys.stderr)
        return 128 + interrupted
    if hook_error is not None:
        print(f"QEMU 测试 hook 失败：{hook_error}", file=sys.stderr)
        return 1
    if cleanup_error is not None:
        print(f"QEMU 进程组清理失败：{cleanup_error}", file=sys.stderr)
        return 1
    if not leader_completed:
        print("QEMU 超时，未完成真实退出握手", file=sys.stderr)
        return 1
    assert process is not None
    if process.returncode != EXPECTED_DEBUG_EXIT_CODE:
        print(
            "QEMU 退出码错误："
            f"expected={EXPECTED_DEBUG_EXIT_CODE} actual={process.returncode}",
            file=sys.stderr,
        )
        return 1
    if parser.failed:
        print(f"QEMU 串口协议失败：{parser.failure_reason}", file=sys.stderr)
        return 1
    if not parser.passed:
        print("QEMU 超时或缺少精确的最终 [TEST] all PASS", file=sys.stderr)
        return 1
    print("QEMU 串口协议 PASS")
    return 0


def _run(arguments: argparse.Namespace) -> int:
    repo = os.path.abspath(_safe_text(arguments.repo, "repo"))
    with BoundBuild.open(repo, arguments.build_dir) as build:
        with build.open_file(arguments.image, "镜像") as image:
            with build.bind_log(arguments.log, _log_test_hook) as log:
                return _run_bound(arguments, image, log)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", default="qemu-system-i386")
    parser.add_argument("--image", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--timeout", default="10")
    parser.add_argument("--max-log-bytes", default="1048576")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--build-dir", default="build")
    return parser


def main() -> int:
    try:
        return _run(_parser().parse_args())
    except (RunnerError, PathBoundaryError, OSError, subprocess.SubprocessError) as error:
        print(f"QEMU 测试错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
