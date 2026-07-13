"""在专用 WSL 中验证 T03 QEMU 协议、隔离和进程清理。"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from collections.abc import Iterator
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _is_wsl_linux() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return False
    return "microsoft" in release.casefold()


@unittest.skipUnless(_is_wsl_linux(), "真实 QEMU 合同只在专用 WSL Linux 中执行")
class QemuRuntimeTests(unittest.TestCase):
    workspace: Path
    temporary_directory: tempfile.TemporaryDirectory[str]
    fake_qemu: Path
    fake_gdb: Path
    argv_log: Path
    pid_file: Path

    @classmethod
    def setUpClass(cls) -> None:
        test_root = ROOT / "build/test-workspaces"
        test_root.mkdir(parents=True, exist_ok=True)
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix="minios-t03-", dir=test_root
        )
        cls.workspace = Path(cls.temporary_directory.name) / "workspace"
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
        cls.fake_qemu = cls.workspace / "fake-qemu-system-i386"
        cls.fake_gdb = cls.workspace / "fake-i686-elf-gdb"
        child_helper = cls.workspace / "fake-qemu-child.py"

        child_helper.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, subprocess, sys, time\n"
            "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
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
            "if scenario == 'foreign':\n"
            "    while True: time.sleep(10)\n"
            "if scenario == 'exit':\n"
            "    raise SystemExit(0)\n"
            "pid_file = os.environ['MINIOS_FAKE_PID_FILE']\n"
            "helper = os.path.join(os.path.dirname(__file__), 'fake-qemu-child.py')\n"
            "child = subprocess.Popen([sys.executable, helper, pid_file])\n"
            "deadline = time.monotonic() + 3\n"
            "while not os.path.exists(pid_file) and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
            "if scenario == 'pass':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol PASS', flush=True)\n"
            "    print('[TEST] suite=framework PASS', flush=True)\n"
            "    print('[TEST] all PASS', flush=True)\n"
            "elif scenario == 'fail':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol FAIL code=E_FAKE tick=1 pid=1', flush=True)\n"
            "elif scenario == 'missing-final':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol PASS', flush=True)\n"
            "    print('[TEST] suite=framework PASS', flush=True)\n"
            "    raise SystemExit(0)\n"
            "elif scenario == 'forged-pass':\n"
            "    print('prefix [TEST] all PASS suffix', flush=True)\n"
            "    raise SystemExit(0)\n"
            "elif scenario == 'fail-then-pass':\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=protocol FAIL code=E_FAKE tick=1 pid=1', flush=True)\n"
            "    print('[TEST] all PASS', flush=True)\n"
            "elif scenario == 'bounded':\n"
            "    for index in range(8192):\n"
            "        print(f'noise-{index:05d}-' + ('x' * 48), flush=True)\n"
            "    print('[TEST] suite=framework begin', flush=True)\n"
            "    print('[TEST] case=bounded PASS', flush=True)\n"
            "    print('[TEST] suite=framework PASS', flush=True)\n"
            "    print('[TEST] all PASS', flush=True)\n"
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

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()
        for directory in (ROOT / "build/test-workspaces", ROOT / "build"):
            try:
                directory.rmdir()
            except OSError:
                pass

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
        for path in (self.argv_log, self.pid_file):
            path.unlink(missing_ok=True)
        log_dir = self.workspace / "build/test-logs"
        if log_dir.exists():
            shutil.rmtree(log_dir)

    def _fake_env(self, scenario: str) -> dict[str, str]:
        return {
            "MINIOS_FAKE_SCENARIO": scenario,
            "MINIOS_FAKE_ARGV_LOG": str(self.argv_log),
            "MINIOS_FAKE_PID_FILE": str(self.pid_file),
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
            result = self._make("test-qemu", scenario="pass")
            pids = self._recorded_descendants()
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self._assert_pids_gone(pids)
        log = self._serial_log()
        self.assertTrue(log.is_file())
        self.assertIn("[TEST] all PASS", log.read_text(encoding="utf-8"))

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

    def test_any_fail_line_overrides_later_pass(self) -> None:
        result = self._make("test-qemu", scenario="fail-then-pass")
        self.assertNotEqual(0, result.returncode, "出现 FAIL 后不得被最终 PASS 覆盖")
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

    def test_real_qemu_fixture_passes_with_complete_protocol(self) -> None:
        result = self._make("test-qemu", timeout_seconds="5", real_qemu=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        log = self._serial_log()
        self.assertTrue(log.is_file(), "真实 fixture 未生成串口日志")
        text = log.read_text(encoding="utf-8")
        self.assertIn("[TEST] suite=", text)
        self.assertIn("[TEST] case=", text)
        self.assertIn("[TEST] all PASS", text)

    def test_real_headless_qemu_timeout_leaves_no_new_process(self) -> None:
        def qemu_pids() -> set[int]:
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

        before = qemu_pids()
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
        while time.monotonic() < deadline and qemu_pids() - before:
            time.sleep(0.02)
        self.assertEqual(set(), qemu_pids() - before, "真实 QEMU 超时后存在残留")


if __name__ == "__main__":
    unittest.main()
