"""验证镜像临时文件清理不会跨越目录替换边界。"""

from __future__ import annotations

import os
import subprocess
import time
import unittest
from pathlib import Path

from tests.host import test_build_runtime as _runtime


@unittest.skipUnless(_runtime._is_wsl_linux(), "真实镜像清理竞态只在专用 WSL Linux 中执行")
class ImageCleanupRaceTests(unittest.TestCase):
    _workspace = _runtime.BuildRuntimeTests._workspace
    _run = _runtime.BuildRuntimeTests._run
    _make = _runtime.BuildRuntimeTests._make
    _assert_makefile = _runtime.BuildRuntimeTests._assert_makefile
    _assert_success = _runtime.BuildRuntimeTests._assert_success
    _build_dir = _runtime.BuildRuntimeTests._build_dir
    _single_component_layout = _runtime.BuildRuntimeTests._single_component_layout
    _image_command = _runtime.BuildRuntimeTests._image_command

    def _wait_for(self, path: Path, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 10
        while not path.is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not path.is_file():
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(
                f"测试 hook 未到达：{path}; rc={process.returncode}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            )

    def test_cleanup_fallback_rejects_second_parent_replacement(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)

            output_parent = workspace / "race-output"
            output_parent.mkdir()
            output = output_parent / "miniorangeos.img"
            original_marker = b"preserve-original-output"
            output.write_bytes(original_marker)

            first_replacement = workspace / "race-output-first-replacement"
            first_replacement.mkdir()
            first_foreign_output = first_replacement / output.name
            first_foreign_marker = b"preserve-first-foreign-output"
            first_foreign_output.write_bytes(first_foreign_marker)

            second_replacement = workspace / "race-output-second-replacement"
            second_replacement.mkdir()
            second_sentinel = second_replacement / "sentinel.txt"
            second_sentinel.write_text("foreign\n", encoding="utf-8")

            layout = self._single_component_layout(
                workspace,
                "cleanup-second-replacement",
                "boot/stage1.bin",
            )
            first_control = workspace / "first-hook"
            second_control = workspace / "second-hook"
            first_control.mkdir()
            second_control.mkdir()
            first_ready = first_control / "ready"
            first_continue = first_control / "continue"
            first_log = first_control / "hook.log"
            second_ready = second_control / "ready"
            second_continue = second_control / "continue"
            second_log = second_control / "hook.log"
            temporary_name_file = second_control / "temporary-name"
            first_stage = "output-after-validation-before-commit"
            second_stage = "cleanup-after-bound-unlink-failed-before-return"
            env = os.environ.copy()
            env.update(
                {
                    "MINIOS_TEST_MODE": "1",
                    "MINIOS_IMAGE_TEST_HOOK": first_stage,
                    "MINIOS_TEST_HOOK_READY": str(first_ready),
                    "MINIOS_TEST_HOOK_CONTINUE": str(first_continue),
                    "MINIOS_TEST_HOOK_LOG": str(first_log),
                    "MINIOS_IMAGE_CLEANUP_TEST_HOOK": second_stage,
                    "MINIOS_IMAGE_CLEANUP_TEST_HOOK_READY": str(second_ready),
                    "MINIOS_IMAGE_CLEANUP_TEST_HOOK_CONTINUE": str(second_continue),
                    "MINIOS_IMAGE_CLEANUP_TEST_HOOK_LOG": str(second_log),
                    "MINIOS_IMAGE_CLEANUP_TEST_TEMP_NAME_FILE": str(
                        temporary_name_file
                    ),
                }
            )
            process = subprocess.Popen(
                self._image_command(workspace, self._build_dir(workspace), output, layout),
                cwd=workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                self._wait_for(first_ready, process)
                owned_parent = workspace / "race-output-owned"
                output_parent.rename(owned_parent)
                first_replacement.rename(output_parent)
                first_continue.write_text("continue\n", encoding="utf-8")

                self._wait_for(second_ready, process)
                temporary_name = temporary_name_file.read_text(
                    encoding="utf-8"
                ).strip()
                self.assertIn(".tmp-", temporary_name)
                foreign_temporary = second_replacement / temporary_name
                foreign_temporary_marker = b"preserve-foreign-temporary"
                foreign_temporary.write_bytes(foreign_temporary_marker)

                abandoned_parent = workspace / "race-output-abandoned"
                owned_parent.rename(abandoned_parent)
                second_replacement.rename(owned_parent)
                second_continue.write_text("continue\n", encoding="utf-8")
                stdout, stderr = process.communicate(timeout=30)
            except BaseException:
                process.kill()
                process.communicate()
                raise

            self.assertNotEqual(0, process.returncode, (stdout, stderr))
            self.assertEqual([first_stage], first_log.read_text(encoding="utf-8").splitlines())
            self.assertEqual([second_stage], second_log.read_text(encoding="utf-8").splitlines())
            self.assertEqual(original_marker, (abandoned_parent / output.name).read_bytes())
            self.assertEqual(first_foreign_marker, (output_parent / output.name).read_bytes())
            self.assertEqual("foreign\n", (owned_parent / "sentinel.txt").read_text(encoding="utf-8"))
            self.assertEqual(
                foreign_temporary_marker,
                (owned_parent / temporary_name).read_bytes(),
            )
            self.assertTrue(
                (abandoned_parent / temporary_name).is_file(),
                "无法安全清理时应保留原随机临时文件，而不是删除外来文件",
            )


if __name__ == "__main__":
    unittest.main()
