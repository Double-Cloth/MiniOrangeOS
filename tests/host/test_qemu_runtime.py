"""在专用 WSL 中验证 T03 QEMU 协议、隔离和进程清理。"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from collections.abc import Iterator
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _is_supported_linux() -> bool:
    return platform.system() == "Linux"


@unittest.skipUnless(_is_supported_linux(), "真实 QEMU 合同只在 Linux 环境执行")
class QemuRuntimeTests(unittest.TestCase):
    workspace: Path
    temporary_directory: tempfile.TemporaryDirectory[str]
    fake_qemu: Path
    fake_gdb: Path
    argv_log: Path
    pid_file: Path
    leader_file: Path
    outside_root: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory(prefix="minios-t03-")
        cls.workspace = Path(cls.temporary_directory.name) / "workspace"
        cls.outside_root = Path(cls.temporary_directory.name) / "outside"
        cls.outside_root.mkdir()
        shutil.copytree(
            ROOT,
            cls.workspace,
            ignore=shutil.ignore_patterns(
                ".git",
                ".superpowers",
                "build",
                "__pycache__",
                ".pytest_cache",
                ".cache",
            ),
        )
        cls.argv_log = cls.workspace / "fake-qemu-argv.jsonl"
        cls.pid_file = cls.workspace / "fake-qemu-pids.json"
        cls.leader_file = cls.workspace / "fake-qemu-leader.pid"
        cls.fake_qemu = cls.workspace / "fake-qemu-system-i386"
        cls.fake_gdb = cls.workspace / "fake-i686-elf-gdb"
        child_helper = cls.workspace / "fake-qemu-child.py"

        child_helper.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, subprocess, sys, time\n"
            "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "with open(sys.argv[1], 'w', encoding='utf-8') as stream:\n"
            "    json.dump([os.getpid(), grandchild.pid], stream)\n"
            "while True:\n"
            "    time.sleep(10)\n",
            encoding="utf-8",
        )
        cls.fake_qemu.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, subprocess, sys, time\n"
            "argv_log = os.environ.get('MINIOS_FAKE_ARGV_LOG')\n"
            "if argv_log:\n"
            "    with open(argv_log, 'a', encoding='utf-8') as stream:\n"
            "        stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "scenario = os.environ.get('MINIOS_FAKE_SCENARIO', 'exit')\n"
            "leader_file = os.environ.get('MINIOS_FAKE_LEADER_FILE')\n"
            "if leader_file:\n"
            "    with open(leader_file, 'w', encoding='ascii') as stream: stream.write(str(os.getpid()))\n"
            "if scenario == 'foreign':\n"
            "    while True: time.sleep(10)\n"
            "if scenario == 'exit':\n"
            "    raise SystemExit(0)\n"
            "pid_file = os.environ['MINIOS_FAKE_PID_FILE']\n"
            "helper = os.path.join(os.path.dirname(__file__), 'fake-qemu-child.py')\n"
            "child = subprocess.Popen([sys.executable, helper, pid_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "deadline = time.monotonic() + 3\n"
            "while not os.path.exists(pid_file) and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
            "valid = '[TEST] suite=framework begin\\n[TEST] case=protocol PASS\\n[TEST] suite=framework PASS\\n[TEST] all PASS\\n'\n"
            "if scenario == 'image-hold':\n"
            "    drive = sys.argv[sys.argv.index('-drive') + 1]\n"
            "    image = next(part[5:] for part in drive.split(',') if part.startswith('file='))\n"
            "    open(os.environ['MINIOS_FAKE_IMAGE_READY'], 'w').close()\n"
            "    while not os.path.exists(os.environ['MINIOS_FAKE_IMAGE_RELEASE']): time.sleep(0.01)\n"
            "    with open(image, 'rb') as stream: data = stream.read(8)\n"
            "    with open(os.environ['MINIOS_FAKE_IMAGE_RESULT'], 'w', encoding='ascii') as stream: stream.write(data.hex())\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.1); raise SystemExit(33)\n"
            "elif scenario == 'pass':\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.45); raise SystemExit(33)\n"
            "elif scenario == 'pass-exit-zero':\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.1); raise SystemExit(0)\n"
            "elif scenario == 'pass-exit-other':\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.1); raise SystemExit(42)\n"
            "elif scenario == 'pass-sigsegv':\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.1); os.kill(os.getpid(), 11)\n"
            "elif scenario == 'pass-zombies':\n"
            "    zombie_pid = os.fork()\n"
            "    if zombie_pid == 0: os._exit(0)\n"
            "    with open(pid_file, encoding='utf-8') as stream: orphan_pids = json.load(stream)\n"
            "    orphan_pids.append(zombie_pid)\n"
            "    with open(pid_file, 'w', encoding='utf-8') as stream: json.dump(orphan_pids, stream)\n"
            "    time.sleep(0.15)\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.1); raise SystemExit(33)\n"
            "elif scenario == 'fail':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol FAIL code=E_FAKE tick=1 pid=1', flush=True)\n"
            "elif scenario == 'missing-final':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol PASS', flush=True)\n"
            "    print('[TEST] suite=framework PASS', flush=True)\n"
            "    raise SystemExit(0)\n"
            "elif scenario == 'isolated-pass':\n"
            "    print('[TEST] all PASS', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'truncated-pass':\n"
            "    sys.stdout.write(valid.rstrip('\\n')); sys.stdout.flush(); raise SystemExit(33)\n"
            "elif scenario == 'missing-begin':\n"
            "    print('[TEST] case=protocol PASS\\n[TEST] suite=framework PASS\\n[TEST] all PASS', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'missing-case':\n"
            "    print('[TEST] suite=framework begin\\n[TEST] suite=framework PASS\\n[TEST] all PASS', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'missing-suite-end':\n"
            "    print('[TEST] suite=framework begin\\n[TEST] case=protocol PASS\\n[TEST] all PASS', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'suite-mismatch':\n"
            "    print('[TEST] suite=alpha begin\\n[TEST] case=protocol PASS\\n[TEST] suite=beta PASS\\n[TEST] all PASS', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'out-of-order':\n"
            "    print('[TEST] case=protocol PASS\\n[TEST] suite=framework begin\\n[TEST] suite=framework PASS\\n[TEST] all PASS', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'duplicate-terminal':\n"
            "    sys.stdout.write(valid + '[TEST] all PASS\\n'); sys.stdout.flush(); raise SystemExit(33)\n"
            "elif scenario == 'forged-pass':\n"
            "    print('prefix [TEST] all PASS suffix', flush=True)\n"
            "    raise SystemExit(0)\n"
            "elif scenario == 'fail-then-pass':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol FAIL code=E_FAKE tick=1 pid=1', flush=True)\n"
            "    print('[TEST] all PASS', flush=True)\n"
            "    raise SystemExit(33)\n"
            "elif scenario == 'pass-then-fail':\n"
            "    sys.stdout.write(valid); sys.stdout.flush(); time.sleep(0.25)\n"
            "    print('[TEST] case=late FAIL code=E_LATE tick=2 pid=1', flush=True); raise SystemExit(33)\n"
            "elif scenario == 'bounded':\n"
            "    for index in range(8192):\n"
            "        print(f'noise-{index:05d}-' + ('x' * 48), flush=True)\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=bounded PASS', flush=True)\n"
            "    print('[TEST] suite=framework PASS', flush=True)\n"
            "    print('[TEST] all PASS', flush=True)\n"
            "    time.sleep(0.1); raise SystemExit(33)\n"
            "elif scenario == 'leader-exit-no-protocol':\n"
            "    raise SystemExit(0)\n"
            "while True:\n"
            "    time.sleep(10)\n",
            encoding="utf-8",
        )
        cls.fake_gdb.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['MINIOS_FAKE_ARGV_LOG'], 'a', encoding='utf-8') as stream:\n"
            "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n",
            encoding="utf-8",
        )
        for path in (child_helper, cls.fake_qemu, cls.fake_gdb):
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

        build = cls._run_class("make", "-j4", "image", timeout=90)
        if build.returncode != 0:
            raise AssertionError(
                f"T03 测试工作副本无法构建镜像：\n{build.stdout}\n{build.stderr}"
            )
        fixture = cls.workspace / "build/test-fixtures/protocol-pass.img"
        fixture.parent.mkdir(parents=True, exist_ok=True)
        assembled = cls._run_class(
            "nasm",
            "-f",
            "bin",
            "-o",
            str(fixture),
            "tests/fixtures/qemu/protocol_pass.asm",
        )
        if assembled.returncode != 0:
            raise AssertionError(assembled.stdout + assembled.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    @classmethod
    def _run_class(
        cls, *arguments: str, timeout: float = 15, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return subprocess.run(
            ["bash", "environment/with-env.sh", *arguments],
            cwd=cls.workspace,
            env=merged,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def setUp(self) -> None:
        for path in (self.argv_log, self.pid_file, self.leader_file):
            path.unlink(missing_ok=True)
        log_dir = self.workspace / "build/test-logs"
        if log_dir.is_symlink():
            log_dir.unlink()
        elif log_dir.exists():
            shutil.rmtree(log_dir)
        shutil.rmtree(self.outside_root, ignore_errors=True)
        self.outside_root.mkdir()

    def tearDown(self) -> None:
        """测试失败也只清理可由 helper 命令行证明归属本次测试的进程组。"""

        if not self.pid_file.is_file():
            return
        try:
            pids = [int(pid) for pid in json.loads(self.pid_file.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        for pid in pids:
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
            except OSError:
                continue
            if str(self.workspace).encode() not in command:
                continue
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            break

    def _fake_env(self, scenario: str) -> dict[str, str]:
        return {
            "MINIOS_FAKE_SCENARIO": scenario,
            "MINIOS_FAKE_ARGV_LOG": str(self.argv_log),
            "MINIOS_FAKE_PID_FILE": str(self.pid_file),
            "MINIOS_FAKE_LEADER_FILE": str(self.leader_file),
        }

    def _make(
        self,
        target: str,
        *,
        scenario: str = "exit",
        timeout_seconds: str = "2",
        log_max_bytes: str = "65536",
        extra_env: dict[str, str] | None = None,
        real_qemu: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self._assert_make_target(target)
        env = self._fake_env(scenario)
        if extra_env:
            env.update(extra_env)
        arguments = [
            "make",
            target,
            f"QEMU_TIMEOUT={timeout_seconds}",
            f"QEMU_LOG_MAX_BYTES={log_max_bytes}",
        ]
        if not real_qemu:
            arguments.append(f"QEMU={self.fake_qemu}")
        if target == "gdb":
            arguments.append(f"GDB={self.fake_gdb}")
        return self._run_class(*arguments, timeout=15, env=env)

    def _assert_make_target(self, target: str) -> None:
        makefile = (self.workspace / "Makefile").read_text(encoding="utf-8")
        self.assertRegex(
            makefile,
            rf"(?m)^{target}:(?:\s|$)",
            f"Makefile 缺少公开目标 {target}",
        )

    def _argv(self) -> list[str]:
        self.assertTrue(self.argv_log.is_file(), "假工具未被调用")
        lines = self.argv_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, len(lines), f"工具调用次数不稳定：{lines}")
        value = json.loads(lines[0])
        self.assertIsInstance(value, list)
        return value

    def _serial_log(self) -> Path:
        return self.workspace / "build/test-logs/qemu-serial.log"

    def _direct_runner_arguments(
        self,
        *,
        image: Path,
        log: Path,
        timeout_seconds: str = "3",
        rooted: bool = False,
        build_dir: Path | None = None,
    ) -> list[str]:
        arguments = [
            "bash",
            "environment/with-env.sh",
            "python3",
            "tools/qemu_test.py",
            "--qemu",
            str(self.fake_qemu),
            "--image",
            str(image),
            "--log",
            str(log),
            "--timeout",
            timeout_seconds,
            "--max-log-bytes",
            "65536",
        ]
        if rooted:
            arguments.extend(
                (
                    "--repo",
                    str(self.workspace),
                    "--build-dir",
                    str(build_dir or self.workspace / "build"),
                )
            )
        return arguments

    def _run_rooted(
        self,
        *,
        image: Path,
        log: Path,
        scenario: str = "pass",
        extra_env: dict[str, str] | None = None,
        timeout: float = 8,
        build_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(self._fake_env(scenario))
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            self._direct_runner_arguments(
                image=image,
                log=log,
                rooted=True,
                build_dir=build_dir,
            ),
            cwd=self.workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def _start_direct_runner(
        self,
        *,
        scenario: str,
        log: Path,
        timeout_seconds: str = "3",
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        env = os.environ.copy()
        env.update(self._fake_env(scenario))
        if extra_env:
            env.update(extra_env)
        return subprocess.Popen(
            self._direct_runner_arguments(
                image=self.workspace / "build/miniorangeos.img",
                log=log,
                timeout_seconds=timeout_seconds,
            ),
            cwd=self.workspace,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _recorded_descendants(self) -> list[int]:
        deadline = time.monotonic() + 2
        while not self.pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.pid_file.is_file(), "假 QEMU 未记录后代 PID")
        return [int(pid) for pid in json.loads(self.pid_file.read_text(encoding="utf-8"))]

    def _assert_pids_gone(self, pids: list[int]) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if all(not Path(f"/proc/{pid}").exists() for pid in pids):
                return
            time.sleep(0.02)
        remaining = [pid for pid in pids if Path(f"/proc/{pid}").exists()]
        self.fail(f"本次 QEMU 后代未清理：{remaining}")

    def _qemu_pids(self) -> set[int]:
        pids: set[int] = set()
        for process in Path("/proc").iterdir():
            if not process.name.isdigit():
                continue
            try:
                executable = os.readlink(process / "exe")
            except OSError:
                continue
            if Path(executable).name == "qemu-system-i386":
                pids.add(int(process.name))
        return pids

    @contextlib.contextmanager
    def _foreign_same_name_process(self) -> Iterator[subprocess.Popen[str]]:
        env = os.environ.copy()
        env.update(self._fake_env("foreign"))
        process = subprocess.Popen(
            [str(self.fake_qemu)],
            cwd=self.workspace,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            time.sleep(0.1)
            self.assertIsNone(process.poll(), "外来同名进程未成功启动")
            yield process
            self.assertIsNone(process.poll(), "测试框架误杀了外来同名进程")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def test_public_run_modes_pass_arguments_as_distinct_tokens(self) -> None:
        expectations = {
            "run-serial": ("-display", "none", "-serial", "stdio"),
            "run-curses": ("-display", "curses"),
            "debug": ("-S", "-gdb"),
        }
        for target, required in expectations.items():
            with self.subTest(target=target):
                self.argv_log.unlink(missing_ok=True)
                result = self._make(target)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                argv = self._argv()
                for token in required:
                    self.assertIn(token, argv, f"{target} 缺少独立参数 {token}")
                drive_index = argv.index("-drive")
                drive = argv[drive_index + 1]
                self.assertIn("format=raw", drive)
                self.assertIn("file=", drive)
                self.assertNotIn(";", drive)

    def test_debug_and_gdb_use_loopback_only(self) -> None:
        debug = self._make("debug")
        self.assertEqual(0, debug.returncode, debug.stdout + debug.stderr)
        debug_argv = self._argv()
        endpoint = debug_argv[debug_argv.index("-gdb") + 1]
        self.assertIn("127.0.0.1:1234", endpoint)
        self.assertNotIn("0.0.0.0", endpoint)

        self.argv_log.unlink(missing_ok=True)
        gdb = self._make("gdb")
        self.assertEqual(0, gdb.returncode, gdb.stdout + gdb.stderr)
        gdb_argv = self._argv()
        self.assertTrue(
            any("target remote 127.0.0.1:1234" in token for token in gdb_argv),
            f"GDB 未连接回环地址：{gdb_argv}",
        )

    def test_protocol_pass_returns_zero_and_cleans_process_tree(self) -> None:
        with self._foreign_same_name_process():
            started = time.monotonic()
            result = self._make("test-qemu", scenario="pass")
            elapsed = time.monotonic() - started
            pids = self._recorded_descendants()
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertGreaterEqual(
                elapsed,
                0.35,
                "runner 不得看到 all PASS 后抢先杀死尚未完成退出握手的 QEMU",
            )
            self._assert_pids_gone(pids)
        log = self._serial_log()
        self.assertTrue(log.is_file())
        self.assertIn("[TEST] all PASS", log.read_text(encoding="utf-8"))

    def test_complete_protocol_requires_exact_debug_exit_status(self) -> None:
        for scenario in ("pass-exit-zero", "pass-exit-other", "pass-sigsegv"):
            with self.subTest(scenario=scenario):
                for path in (self.pid_file, self.leader_file):
                    path.unlink(missing_ok=True)
                log = self.workspace / f"build/test-logs/{scenario}.log"
                result = self._run_rooted(
                    image=self.workspace / "build/miniorangeos.img",
                    log=log,
                    scenario=scenario,
                )
                self.assertNotEqual(
                    0,
                    result.returncode,
                    "只有 isa-debug-exit 约定的 QEMU 状态 33 才能证明成功",
                )
                self.assertIn("[TEST] all PASS", log.read_text(encoding="utf-8"))
                self._assert_pids_gone(self._recorded_descendants())

    def test_subreaper_runner_reaps_orphaned_descendants_in_container_semantics(self) -> None:
        wrapper = self.workspace / "subreaper-wrapper.py"
        wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import ctypes, os, sys\n"
            "PR_SET_CHILD_SUBREAPER = 36\n"
            "if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:\n"
            "    raise OSError(ctypes.get_errno(), 'prctl(PR_SET_CHILD_SUBREAPER)')\n"
            "value = ctypes.c_int()\n"
            "if ctypes.CDLL(None, use_errno=True).prctl(37, ctypes.byref(value), 0, 0, 0) != 0 or value.value != 1:\n"
            "    raise RuntimeError('subreaper 未生效')\n"
            "open(os.environ['MINIOS_SUBREAPER_MARKER'], 'w').write('enabled')\n"
            "os.execvp(sys.argv[1], sys.argv[1:])\n",
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        observation = self.workspace / "subreaper-after-cleanup.log"
        hook = self.workspace / "subreaper-observer.py"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "if sys.argv[1] == 'after-cleanup':\n"
            "    pids = json.loads(pathlib.Path(os.environ['MINIOS_FAKE_PID_FILE']).read_text())\n"
            "    states = []\n"
            "    for pid in pids:\n"
            "        try:\n"
            "            text = pathlib.Path(f'/proc/{pid}/stat').read_text()\n"
            "            states.append(f\"{pid}:{text[text.rfind(chr(41)) + 2]}\")\n"
            "        except FileNotFoundError: pass\n"
            "    pathlib.Path(os.environ['MINIOS_SUBREAPER_OBSERVATION']).write_text(','.join(states))\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        log = self.workspace / "build/test-logs/subreaper.log"
        base = self._direct_runner_arguments(
            image=self.workspace / "build/miniorangeos.img",
            log=log,
            rooted=True,
        )
        command = [base[0], base[1], str(wrapper), *base[2:]]
        env = os.environ.copy()
        marker = self.workspace / "subreaper-enabled.marker"
        env.update(self._fake_env("pass-zombies"))
        env["MINIOS_SUBREAPER_MARKER"] = str(marker)
        env.update(
            {
                "MINIOS_TEST_MODE": "1",
                "MINIOS_QEMU_TEST_HOOK": str(hook),
                "MINIOS_SUBREAPER_OBSERVATION": str(observation),
            }
        )
        result = subprocess.run(
            command,
            cwd=self.workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        descendants = self._recorded_descendants()
        self.assertEqual("enabled", marker.read_text(encoding="utf-8"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            "",
            observation.read_text(encoding="utf-8"),
            "runner 完成 cleanup 时不得仍持有 orphan zombie",
        )
        self._assert_pids_gone(descendants)
        self.assertFalse(
            any(Path(f"/proc/{pid}/stat").exists() for pid in descendants),
            "subreaper 模式不得遗留 orphan zombie",
        )

    def test_protocol_fail_returns_nonzero_and_cleans_process_tree(self) -> None:
        with self._foreign_same_name_process():
            result = self._make("test-qemu", scenario="fail")
            pids = self._recorded_descendants()
            self.assertNotEqual(0, result.returncode)
            self._assert_pids_gone(pids)
        log = self._serial_log()
        self.assertTrue(log.is_file())
        self.assertIn("FAIL code=E_FAKE", log.read_text(encoding="utf-8"))

    def test_missing_final_pass_returns_nonzero(self) -> None:
        result = self._make("test-qemu", scenario="missing-final")
        self.assertNotEqual(0, result.returncode)
        log = self._serial_log()
        self.assertTrue(log.is_file(), "协议不完整也必须保留串口日志")
        self.assertNotIn("[TEST] all PASS", log.read_text(encoding="utf-8"))

    def test_protocol_requires_an_exact_terminal_pass_line(self) -> None:
        result = self._make("test-qemu", scenario="forged-pass")
        self.assertNotEqual(0, result.returncode, "协议解析不得接受包含 PASS 的任意文本")

    def test_protocol_rejects_incomplete_mismatched_or_reordered_sequences(self) -> None:
        scenarios = (
            "isolated-pass",
            "truncated-pass",
            "missing-begin",
            "missing-case",
            "missing-suite-end",
            "suite-mismatch",
            "out-of-order",
            "duplicate-terminal",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self.pid_file.unlink(missing_ok=True)
                result = self._make("test-qemu", scenario=scenario)
                self.assertNotEqual(
                    0,
                    result.returncode,
                    f"非法串口协议被误判 PASS：{scenario}",
                )
                self._assert_pids_gone(self._recorded_descendants())

    def test_any_fail_line_overrides_later_pass(self) -> None:
        result = self._make("test-qemu", scenario="fail-then-pass")
        self.assertNotEqual(0, result.returncode, "出现 FAIL 后不得被最终 PASS 覆盖")
        self._assert_pids_gone(self._recorded_descendants())

    def test_fail_after_terminal_pass_is_still_fatal(self) -> None:
        result = self._make("test-qemu", scenario="pass-then-fail")
        self.assertNotEqual(0, result.returncode, "最终 PASS 后的 FAIL 不得被丢弃")
        log = self._serial_log().read_text(encoding="utf-8")
        self.assertIn("FAIL code=E_LATE", log)
        self._assert_pids_gone(self._recorded_descendants())

    def test_timeout_returns_nonzero_and_cleans_process_tree(self) -> None:
        with self._foreign_same_name_process():
            started = time.monotonic()
            result = self._make(
                "test-qemu", scenario="timeout", timeout_seconds="1"
            )
            elapsed = time.monotonic() - started
            pids = self._recorded_descendants()
            self.assertNotEqual(0, result.returncode)
            self.assertLess(elapsed, 5, "QEMU 超时未被及时执行")
            self._assert_pids_gone(pids)
        self.assertTrue(self._serial_log().is_file(), "超时也必须保留串口日志")

    def test_interrupt_term_and_hup_flush_logs_and_clean_only_owned_tree(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signal.Signals(signum).name):
                for path in (self.pid_file, self.leader_file):
                    path.unlink(missing_ok=True)
                log = self.workspace / f"build/test-logs/signal-{signum}.log"
                with self._foreign_same_name_process():
                    runner = self._start_direct_runner(
                        scenario="timeout", log=log, timeout_seconds="10"
                    )
                    try:
                        descendants = self._recorded_descendants()
                        leader = int(self.leader_file.read_text(encoding="ascii"))
                        runner.send_signal(signum)
                        stdout, stderr = runner.communicate(timeout=6)
                        self.assertEqual(
                            128 + signum,
                            runner.returncode,
                            (stdout + stderr).decode("utf-8", errors="replace"),
                        )
                        self.assertTrue(log.is_file(), "收到信号也必须原子落盘日志")
                        self._assert_pids_gone([leader, *descendants])
                    finally:
                        if runner.poll() is None:
                            runner.kill()
                            runner.wait(timeout=2)

    def test_serial_log_is_bounded_and_preserves_terminal_protocol(self) -> None:
        limit = 32768
        result = self._make(
            "test-qemu", scenario="bounded", log_max_bytes=str(limit)
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        log = self._serial_log()
        self.assertLessEqual(log.stat().st_size, limit)
        self.assertIn("[TEST] all PASS", log.read_text(encoding="utf-8"))
        self._assert_pids_gone(self._recorded_descendants())

    def test_invalid_numeric_boundaries_fail_before_qemu_spawn(self) -> None:
        for variable, value in (
            ("QEMU_TIMEOUT", "0"),
            ("QEMU_TIMEOUT", "-1"),
            ("QEMU_TIMEOUT", "1.5"),
            ("QEMU_LOG_MAX_BYTES", "0"),
            ("QEMU_LOG_MAX_BYTES", "-1"),
            ("GDB_ENDPOINT", "tcp:0.0.0.0:1234"),
            ("GDB_ENDPOINT", "tcp:127.0.0.1:0"),
            ("GDB_ENDPOINT", "tcp:127.0.0.1:65536"),
            ("GDB_ENDPOINT", "not-an-endpoint"),
        ):
            with self.subTest(variable=variable, value=value):
                self.argv_log.unlink(missing_ok=True)
                target = "debug" if variable == "GDB_ENDPOINT" else "test-qemu"
                self._assert_make_target(target)
                arguments = [
                    "make",
                    target,
                    f"QEMU={self.fake_qemu}",
                    "QEMU_TIMEOUT=2",
                    "QEMU_LOG_MAX_BYTES=65536",
                    "GDB_ENDPOINT=tcp:127.0.0.1:1234",
                    f"{variable}={value}",
                ]
                result = self._run_class(
                    *arguments, timeout=8, env=self._fake_env("exit")
                )
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(self.argv_log.exists(), "非法参数不得启动 QEMU")

    def test_test_hook_is_ignored_without_test_mode_and_enabled_with_it(self) -> None:
        ignored = self._make(
            "test-qemu",
            scenario="pass",
            extra_env={"MINIOS_QEMU_TEST_HOOK": "/definitely/not/a/hook"},
        )
        self.assertEqual(0, ignored.returncode, ignored.stdout + ignored.stderr)

        hook = self.workspace / "qemu-test-hook"
        hook_log = self.workspace / "qemu-test-hook.log"
        hook.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$1\" >> \"$MINIOS_HOOK_LOG\"\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        self.pid_file.unlink(missing_ok=True)
        enabled = self._make(
            "test-qemu",
            scenario="pass",
            extra_env={
                "MINIOS_TEST_MODE": "1",
                "MINIOS_QEMU_TEST_HOOK": str(hook),
                "MINIOS_HOOK_LOG": str(hook_log),
            },
        )
        self.assertEqual(0, enabled.returncode, enabled.stdout + enabled.stderr)
        stages = hook_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(["after-spawn", "before-cleanup", "after-cleanup"], stages)

    def test_log_identity_hook_is_gated_and_detects_temp_replacement(self) -> None:
        ignored = self._run_rooted(
            image=self.workspace / "build/miniorangeos.img",
            log=self.workspace / "build/test-logs/log-hook-ignored.log",
            extra_env={"MINIOS_QEMU_LOG_TEST_HOOK": "/definitely/not/a/log-hook"},
        )
        self.assertEqual(0, ignored.returncode, ignored.stdout + ignored.stderr)

        hook = self.workspace / "replace-log-temp-hook.py"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "stage, temporary = sys.argv[1:]\n"
            "if stage != 'before-log-commit': raise SystemExit(2)\n"
            "pathlib.Path(os.environ['MINIOS_LOG_HOOK_MARKER']).write_text(stage)\n"
            "matches = list(pathlib.Path(os.environ['MINIOS_LOG_BUILD']).rglob(temporary))\n"
            "if len(matches) != 1: raise SystemExit(4)\n"
            "target = matches[0]\n"
            "target.unlink()\n"
            "attack = os.environ['MINIOS_LOG_ATTACK']\n"
            "external = pathlib.Path(os.environ['MINIOS_LOG_EXTERNAL'])\n"
            "if attack == 'symlink': target.symlink_to(external)\n"
            "elif attack == 'hardlink': os.link(external, target)\n"
            "elif attack == 'foreign': target.write_bytes(b'FOREIGN-LOG')\n"
            "else: raise SystemExit(3)\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

        for attack in ("symlink", "hardlink", "foreign"):
            with self.subTest(attack=attack):
                for path in (self.pid_file, self.leader_file):
                    path.unlink(missing_ok=True)
                log_dir = self.workspace / "build/test-logs"
                if log_dir.exists():
                    shutil.rmtree(log_dir)
                external = self.outside_root / f"{attack}-sentinel.log"
                external.write_text(f"sentinel-{attack}", encoding="utf-8")
                marker = self.workspace / f"log-hook-{attack}.marker"
                marker.unlink(missing_ok=True)
                final_log = log_dir / f"{attack}.log"
                result = self._run_rooted(
                    image=self.workspace / "build/miniorangeos.img",
                    log=final_log,
                    extra_env={
                        "MINIOS_TEST_MODE": "1",
                        "MINIOS_QEMU_LOG_TEST_HOOK": str(hook),
                        "MINIOS_LOG_HOOK_MARKER": str(marker),
                        "MINIOS_LOG_ATTACK": attack,
                        "MINIOS_LOG_EXTERNAL": str(external),
                        "MINIOS_LOG_BUILD": str(self.workspace / "build"),
                    },
                )
                self.assertTrue(marker.is_file(), "gated 日志身份 hook 未执行")
                self.assertNotEqual(0, result.returncode, "临时日志身份变化必须失败")
                self.assertEqual(
                    f"sentinel-{attack}", external.read_text(encoding="utf-8")
                )
                self.assertFalse(
                    final_log.exists(), "身份不可信的临时文件不得提交为成功日志"
                )
                self._assert_pids_gone(self._recorded_descendants())

    def test_rooted_runner_accepts_only_paths_inside_verified_build_tree(self) -> None:
        result = self._run_rooted(
            image=self.workspace / "build/miniorangeos.img",
            log=self.workspace / "build/test-logs/rooted.log",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((self.workspace / "build/test-logs/rooted.log").is_file())
        self._assert_pids_gone(self._recorded_descendants())

    def test_image_rejects_symlink_hardlink_and_fifo(self) -> None:
        cases = self.workspace / "build/path-cases"
        cases.mkdir(parents=True, exist_ok=True)
        regular = cases / "regular.img"
        regular.write_bytes(b"regular-image")
        symlink = cases / "symlink.img"
        symlink.symlink_to(regular)
        hardlink_source = cases / "hardlink-source.img"
        hardlink_source.write_bytes(b"hardlink-image")
        hardlink = cases / "hardlink.img"
        os.link(hardlink_source, hardlink)
        fifo = cases / "fifo.img"
        os.mkfifo(fifo)

        for image in (symlink, hardlink, fifo):
            with self.subTest(kind=image.name):
                self.argv_log.unlink(missing_ok=True)
                result = self._run_rooted(
                    image=image,
                    log=self.workspace / f"build/test-logs/{image.name}.log",
                    scenario="exit",
                )
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(self.argv_log.exists(), "非法镜像不得启动 QEMU")

    def test_build_image_and_log_intermediate_symlinks_cannot_escape(self) -> None:
        external = self.outside_root / "external"
        external.mkdir(parents=True)
        (external / "nested").mkdir()
        external_image = external / "nested/image.img"
        external_image.write_bytes(b"external-image")

        image_link = self.workspace / "build/image-middle"
        image_link.symlink_to(external)
        image_result = self._run_rooted(
            image=image_link / "nested/image.img",
            log=self.workspace / "build/test-logs/image-middle.log",
            scenario="exit",
        )
        self.assertNotEqual(0, image_result.returncode)

        log_link = self.workspace / "build/log-middle"
        log_link.symlink_to(external)
        escaped_log = external / "nested/escaped.log"
        log_result = self._run_rooted(
            image=self.workspace / "build/miniorangeos.img",
            log=log_link / "nested/escaped.log",
        )
        self.assertNotEqual(0, log_result.returncode)
        self.assertFalse(escaped_log.exists(), "日志中间符号链接逃逸到 build 外")

        build_link = self.workspace / "build-middle"
        build_link.symlink_to(external)
        build_result = self._run_rooted(
            image=external_image,
            log=external / "nested/build-escaped.log",
            scenario="exit",
            build_dir=build_link / "nested",
        )
        self.assertNotEqual(0, build_result.returncode)
        self.assertFalse((external / "nested/build-escaped.log").exists())

    def test_existing_log_symlink_never_overwrites_external_file(self) -> None:
        external = self.outside_root / "protected.log"
        external.write_text("sentinel", encoding="utf-8")
        log = self.workspace / "build/test-logs/final.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.symlink_to(external)
        result = self._run_rooted(
            image=self.workspace / "build/miniorangeos.img",
            log=log,
        )
        self.assertEqual("sentinel", external.read_text(encoding="utf-8"))
        if result.returncode == 0:
            self.assertTrue(log.is_file() and not log.is_symlink())
            self.assertIn("[TEST] all PASS", log.read_text(encoding="utf-8"))

    def test_log_parent_replacement_after_spawn_cannot_redirect_commit(self) -> None:
        parent = self.workspace / "build/race-log-parent"
        (parent / "nested").mkdir(parents=True)
        external = self.outside_root / "race-log"
        (external / "nested").mkdir(parents=True)
        hook = self.workspace / "replace-log-parent-hook.py"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "if sys.argv[1] == 'after-spawn':\n"
            "    parent = pathlib.Path(os.environ['MINIOS_RACE_PARENT'])\n"
            "    saved = parent.with_name(parent.name + '.saved')\n"
            "    parent.rename(saved)\n"
            "    parent.symlink_to(os.environ['MINIOS_RACE_EXTERNAL'])\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        result = self._run_rooted(
            image=self.workspace / "build/miniorangeos.img",
            log=parent / "nested/qemu.log",
            extra_env={
                "MINIOS_TEST_MODE": "1",
                "MINIOS_QEMU_TEST_HOOK": str(hook),
                "MINIOS_RACE_PARENT": str(parent),
                "MINIOS_RACE_EXTERNAL": str(external),
            },
        )
        self.assertFalse((external / "nested/qemu.log").exists())
        if result.returncode == 0:
            self.assertTrue(
                (parent.with_name(parent.name + ".saved") / "nested/qemu.log").is_file()
            )

    def test_build_root_replacement_after_spawn_cannot_escape_log(self) -> None:
        build = self.workspace / "build"
        saved = self.workspace / "build.saved"
        external = self.outside_root / "build-race"
        external.mkdir()
        hook = self.workspace / "replace-build-hook.py"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "if sys.argv[1] == 'after-spawn':\n"
            "    build = pathlib.Path(os.environ['MINIOS_RACE_BUILD'])\n"
            "    build.rename(os.environ['MINIOS_RACE_SAVED'])\n"
            "    build.symlink_to(os.environ['MINIOS_RACE_EXTERNAL'])\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        try:
            result = self._run_rooted(
                image=build / "miniorangeos.img",
                log=build / "test-logs/build-race.log",
                extra_env={
                    "MINIOS_TEST_MODE": "1",
                    "MINIOS_QEMU_TEST_HOOK": str(hook),
                    "MINIOS_RACE_BUILD": str(build),
                    "MINIOS_RACE_SAVED": str(saved),
                    "MINIOS_RACE_EXTERNAL": str(external),
                },
            )
            self.assertFalse((external / "test-logs/build-race.log").exists())
            if result.returncode == 0:
                self.assertTrue((saved / "test-logs/build-race.log").is_file())
        finally:
            if build.is_symlink():
                build.unlink()
            if saved.exists():
                saved.rename(build)

    def test_validated_image_fd_survives_path_replacement(self) -> None:
        image = self.workspace / "build/path-cases/image-race.img"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"ORIGINAL-image")
        saved = image.with_suffix(".saved")
        ready = self.workspace / "image-race.ready"
        release = self.workspace / "image-race.release"
        observed = self.workspace / "image-race.result"
        env = os.environ.copy()
        env.update(self._fake_env("image-hold"))
        env.update(
            {
                "MINIOS_FAKE_IMAGE_READY": str(ready),
                "MINIOS_FAKE_IMAGE_RELEASE": str(release),
                "MINIOS_FAKE_IMAGE_RESULT": str(observed),
            }
        )
        runner = subprocess.Popen(
            self._direct_runner_arguments(
                image=image,
                log=self.workspace / "build/test-logs/image-race.log",
                rooted=True,
            ),
            cwd=self.workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not ready.exists() and runner.poll() is None:
                time.sleep(0.01)
            self.assertTrue(ready.is_file(), "QEMU 未获得已验证镜像描述符")
            image.rename(saved)
            image.write_bytes(b"MALICIOU-image")
            release.touch()
            stdout, stderr = runner.communicate(timeout=5)
            self.assertEqual(
                0,
                runner.returncode,
                (stdout + stderr).decode("utf-8", errors="replace"),
            )
            self.assertEqual(b"ORIGINAL", bytes.fromhex(observed.read_text(encoding="ascii")))
        finally:
            if runner.poll() is None:
                runner.kill()
                runner.wait(timeout=2)

    def test_exited_leader_is_held_during_cleanup_while_pid_churn_runs(self) -> None:
        observation = self.workspace / "leader-hold.log"
        hook = self.workspace / "leader-hold-hook.py"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, subprocess, sys\n"
            "if sys.argv[1] == 'before-cleanup':\n"
            "    leader = pathlib.Path(os.environ['MINIOS_FAKE_LEADER_FILE']).read_text()\n"
            "    held = pathlib.Path('/proc').joinpath(leader).exists()\n"
            "    for _ in range(128): subprocess.run(['true'], start_new_session=True, check=True)\n"
            "    pathlib.Path(os.environ['MINIOS_LEADER_OBSERVATION']).write_text(f'held={int(held)}')\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        with self._foreign_same_name_process():
            result = self._run_rooted(
                image=self.workspace / "build/miniorangeos.img",
                log=self.workspace / "build/test-logs/leader-exit.log",
                scenario="leader-exit-no-protocol",
                extra_env={
                    "MINIOS_TEST_MODE": "1",
                    "MINIOS_QEMU_TEST_HOOK": str(hook),
                    "MINIOS_LEADER_OBSERVATION": str(observation),
                },
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(
                "held=1",
                observation.read_text(encoding="utf-8"),
                "cleanup 前不得 poll/reap leader，以免 PGID 在 kill 前复用",
            )
            self._assert_pids_gone(self._recorded_descendants())

    def test_real_qemu_fixture_passes_with_complete_protocol(self) -> None:
        result = self._make("test-qemu", timeout_seconds="5", real_qemu=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        log = self._serial_log()
        self.assertTrue(log.is_file(), "真实 fixture 未生成串口日志")
        text = log.read_text(encoding="utf-8")
        self.assertIn("[TEST] suite=", text)
        self.assertIn("[TEST] case=", text)
        self.assertIn("[TEST] all PASS", text)

    def test_real_fixture_completes_debug_exit_handshake_without_runner_kill(self) -> None:
        fixture = self.workspace / "build/test-fixtures/protocol-pass.img"
        command = [
            "bash",
            "environment/with-env.sh",
            "qemu-system-i386",
            "-machine",
            "pc,accel=tcg",
            "-drive",
            f"file={fixture},format=raw,if=ide,index=0,media=disk",
            "-display",
            "none",
            "-monitor",
            "none",
            "-serial",
            "stdio",
            "-device",
            "isa-debug-exit,iobase=0xf4,iosize=0x04",
        ]
        process = subprocess.Popen(
            command,
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        try:
            try:
                stdout, stderr = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=2)
            self.assertFalse(
                timed_out,
                "真实 protocol fixture 必须通过 isa-debug-exit 主动退出",
            )
            self.assertEqual(
                33,
                process.returncode,
                (stdout + stderr).decode("utf-8", errors="replace"),
            )
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)

    def test_real_headless_qemu_timeout_leaves_no_new_process(self) -> None:
        before = self._qemu_pids()
        runner = self.workspace / "tools/qemu_test.py"
        self.assertTrue(runner.is_file(), "缺少 tools/qemu_test.py")
        result = self._run_class(
            "python3",
            "tools/qemu_test.py",
            "--qemu",
            "qemu-system-i386",
            "--image",
            "build/miniorangeos.img",
            "--log",
            "build/test-logs/qemu-timeout.log",
            "--timeout",
            "1",
            "--max-log-bytes",
            "65536",
            timeout=8,
        )
        self.assertNotEqual(0, result.returncode, "占位镜像不应伪造最终 PASS")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and self._qemu_pids() - before:
            time.sleep(0.02)
        self.assertEqual(set(), self._qemu_pids() - before, "真实 QEMU 超时后存在残留")

    def test_real_debug_and_batch_gdb_handshake_are_loopback_only(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        endpoint = f"tcp:127.0.0.1:{port}"
        port_hex = f"{port:04X}"

        def listeners() -> set[str]:
            found: set[str] = set()
            for table in ("/proc/net/tcp", "/proc/net/tcp6"):
                try:
                    lines = Path(table).read_text(encoding="ascii").splitlines()[1:]
                except OSError:
                    continue
                for line in lines:
                    fields = line.split()
                    address, state = fields[1], fields[3]
                    if address.rsplit(":", 1)[1].upper() == port_hex and state == "0A":
                        found.add(address)
            return found

        before_qemu = self._qemu_pids()
        debug = subprocess.Popen(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                "debug",
                f"GDB_ENDPOINT={endpoint}",
            ],
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline and not listeners():
                if debug.poll() is not None:
                    stdout, stderr = debug.communicate()
                    self.fail(
                        "make debug 提前退出："
                        + (stdout + stderr).decode("utf-8", errors="replace")
                    )
                time.sleep(0.03)
            bound = listeners()
            self.assertTrue(bound, "真实 QEMU GDB 端口未开始监听")
            self.assertTrue(
                all(address.startswith("0100007F:") for address in bound),
                f"GDB 端口不是仅绑定 127.0.0.1：{bound}",
            )

            real_gdb = shutil.which("gdb")
            self.assertIsNotNone(real_gdb, "Linux 环境必须提供真实 gdb")
            wrapper = self.workspace / "real-gdb-batch-wrapper"
            transcript = self.workspace / "real-gdb-transcript.log"
            wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import os, subprocess, sys\n"
                f"command = [{real_gdb!r}, '-batch', *sys.argv[1:], '-ex', 'detach', '-ex', 'quit']\n"
                f"with open({str(transcript)!r}, 'wb') as stream:\n"
                "    result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)\n"
                "raise SystemExit(result.returncode)\n",
                encoding="utf-8",
            )
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
            gdb = self._run_class(
                "make",
                "gdb",
                f"GDB={wrapper}",
                f"GDB_ENDPOINT={endpoint}",
                timeout=12,
            )
            self.assertEqual(0, gdb.returncode, gdb.stdout + gdb.stderr)
            output = transcript.read_text(encoding="utf-8", errors="replace")
            self.assertRegex(output, r"(?i)(remote debugging|remote target|detaching|detached)")
            self.assertNotIn("Invalid argument", output, "真实 GDB 必须能打开 Kernel ELF")
            self.assertNotIn("No executable has been specified", output)
        finally:
            try:
                os.killpg(debug.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                debug.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(debug.pid, signal.SIGKILL)
                debug.communicate(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (listeners() or self._qemu_pids() - before_qemu):
            time.sleep(0.03)
        self.assertEqual(set(), listeners(), "GDB 监听端口未清理")
        self.assertEqual(set(), self._qemu_pids() - before_qemu, "真实 debug QEMU 有残留")


if __name__ == "__main__":
    unittest.main()
