#!/usr/bin/env python3
"""运行无界面 QEMU，解析 COM1 测试协议并可靠清理本次进程树。"""

from __future__ import annotations

import argparse
import os
import secrets
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn


PASS_LINE = b"[TEST] all PASS"
READ_SIZE = 65536
LINE_LIMIT = 262144
TERMINATE_GRACE_SECONDS = 0.35


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
    """按完整行严格识别 TEST 终态，不接受子串伪造。"""

    def __init__(self) -> None:
        self._pending = bytearray()
        self.passed = False
        self.failed = False

    def feed(self, data: bytes) -> None:
        self._pending.extend(data)
        while True:
            newline = self._pending.find(b"\n")
            if newline < 0:
                if len(self._pending) > LINE_LIMIT:
                    del self._pending[:-LINE_LIMIT]
                return
            line = bytes(self._pending[:newline]).rstrip(b"\r")
            del self._pending[: newline + 1]
            self._parse_line(line)

    def finish(self) -> None:
        if self._pending:
            self._parse_line(bytes(self._pending).rstrip(b"\r"))
            self._pending.clear()

    def _parse_line(self, line: bytes) -> None:
        if line.startswith(b"[TEST] ") and b"FAIL" in line.split():
            self.failed = True
        if line == PASS_LINE:
            self.passed = True


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


def _atomic_log(path: Path, content: bytes) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    directory_fd = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary = f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _test_hook(stage: str) -> None:
    if os.environ.get("MINIOS_TEST_MODE") != "1":
        return
    hook = os.environ.get("MINIOS_QEMU_TEST_HOOK")
    if not hook:
        return
    subprocess.run([_safe_text(hook, "测试 hook"), stage], check=True)


def _group_exists(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup(process: subprocess.Popen[bytes]) -> None:
    """只向本次 start_new_session 创建的进程组发送信号。"""

    group = process.pid
    try:
        os.killpg(group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline and _group_exists(group):
        time.sleep(0.01)
    if _group_exists(group):
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=1.0)


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


def _run(arguments: argparse.Namespace) -> int:
    timeout = _positive_integer(arguments.timeout, "timeout")
    maximum = _positive_integer(arguments.max_log_bytes, "max-log-bytes")
    command = _command(arguments.qemu, arguments.image)
    log_path = Path(_safe_text(arguments.log, "日志路径"))
    capture = BoundedTail(maximum)
    parser = ProtocolParser()
    interrupted = 0
    process: subprocess.Popen[bytes] | None = None
    hook_error: BaseException | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = signum

    previous = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            bufsize=0,
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
            while not interrupted and not parser.failed and not parser.passed:
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
                if process.poll() is not None and not selector.get_map():
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
            _cleanup(process)
            try:
                _test_hook("after-cleanup")
            except BaseException as error:
                hook_error = hook_error or error
        parser.finish()
        _atomic_log(log_path, capture.bytes())
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    if interrupted:
        print(f"QEMU 测试被信号 {interrupted} 中断", file=sys.stderr)
        return 128 + interrupted
    if hook_error is not None:
        print(f"QEMU 测试 hook 失败：{hook_error}", file=sys.stderr)
        return 1
    if parser.failed:
        print("QEMU 串口协议报告 FAIL", file=sys.stderr)
        return 1
    if not parser.passed:
        print("QEMU 超时或缺少精确的最终 [TEST] all PASS", file=sys.stderr)
        return 1
    print("QEMU 串口协议 PASS")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", default="qemu-system-i386")
    parser.add_argument("--image", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--timeout", default="10")
    parser.add_argument("--max-log-bytes", default="1048576")
    return parser


def main() -> int:
    try:
        return _run(_parser().parse_args())
    except (RunnerError, OSError, subprocess.SubprocessError) as error:
        print(f"QEMU 测试错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
