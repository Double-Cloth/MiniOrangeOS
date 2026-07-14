"""定义 T03 QEMU 自动化与调试框架的静态合同。"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAKE_TARGETS = {
    "run-serial",
    "run-curses",
    "debug",
    "gdb",
    "test-qemu",
    "test-boot-qemu",
}


class QemuContractTests(unittest.TestCase):
    def _makefile(self) -> str:
        path = ROOT / "Makefile"
        self.assertTrue(path.is_file(), "缺少顶层 Makefile")
        return path.read_text(encoding="utf-8")

    def _runners(self) -> list[tuple[Path, str]]:
        paths = (ROOT / "tools/qemu_run.py", ROOT / "tools/qemu_test.py")
        missing = [path.relative_to(ROOT).as_posix() for path in paths if not path.is_file()]
        self.assertEqual([], missing, f"缺少 T03 runner：{missing}")
        return [(path, path.read_text(encoding="utf-8")) for path in paths]

    def test_makefile_exposes_all_public_qemu_targets(self) -> None:
        text = self._makefile()
        targets = {
            match.group(1)
            for match in re.finditer(
                r"(?m)^([A-Za-z][A-Za-z0-9_-]*):(?:\s|$)", text
            )
        }
        self.assertEqual(set(), MAKE_TARGETS - targets, "T03 公开入口不完整")

        phony = set()
        for match in re.finditer(r"(?m)^\.PHONY:\s*(.+)$", text):
            phony.update(match.group(1).split())
        self.assertEqual(set(), MAKE_TARGETS - phony, "T03 公开入口必须声明为 .PHONY")

    def test_makefile_declares_overridable_tools_and_resource_limits(self) -> None:
        text = self._makefile()
        for variable, default in (
            ("QEMU", "qemu-system-i386"),
            ("GDB", "gdb"),
            ("QEMU_TIMEOUT", None),
            ("QEMU_LOG_MAX_BYTES", None),
            ("GDB_ENDPOINT", "tcp:127.0.0.1:1234"),
        ):
            pattern = rf"(?m)^{variable}\s*\?=\s*(\S+)\s*$"
            match = re.search(pattern, text)
            self.assertIsNotNone(match, f"Makefile 缺少可覆盖变量 {variable}")
            if default is not None and match is not None:
                self.assertEqual(default, match.group(1))

    def test_runner_is_valid_python_and_does_not_use_shell_execution(self) -> None:
        unsafe_shell_calls: list[int] = []
        for path, text in self._runners():
            try:
                tree = ast.parse(text, filename=str(path))
            except SyntaxError as error:
                self.fail(f"QEMU runner 不是有效 Python：{error}")
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant):
                        if keyword.value.value is True:
                            unsafe_shell_calls.append(node.lineno)
        self.assertEqual([], unsafe_shell_calls, "runner 禁止 shell=True")

    def test_framework_never_uses_process_name_wide_kill(self) -> None:
        makefile = self._makefile()
        runners = "\n".join(text for _, text in self._runners())
        combined = f"{makefile}\n{runners}".casefold()
        forbidden = ("pkill", "killall", "taskkill")
        found = [token for token in forbidden if token in combined]
        self.assertEqual([], found, f"禁止按进程名全局清理：{found}")

    def test_debug_configuration_cannot_bind_wildcard_addresses(self) -> None:
        makefile = self._makefile()
        runners = "\n".join(text for _, text in self._runners())
        combined = f"{makefile}\n{runners}"
        self.assertNotIn("0.0.0.0", combined)
        self.assertNotRegex(combined, r"(?<![A-Za-z0-9_])tcp::")
        self.assertIn("127.0.0.1", combined, "GDB server/client 必须显式使用回环地址")


if __name__ == "__main__":
    unittest.main()
