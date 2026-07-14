"""验证 P7 聚合测试、CI、代码量与发布材料合同。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github/workflows/ci.yml"
CI_RUNNER = ROOT / "environment/ubuntu/ci-run.sh"
CHECKLIST = ROOT / "docs/release-checklist.md"
LOC_TOOL = ROOT / "tools/loc.py"
DEMO_TOOL = ROOT / "tools/demo_persistence.py"


class ReleaseContractTests(unittest.TestCase):
    def test_makefile_exposes_release_targets(self) -> None:
        source = MAKEFILE.read_text(encoding="utf-8")
        for target in ("check", "test-host", "test", "loc", "demo-persistence"):
            self.assertRegex(source, rf"(?m)^{re.escape(target)}:\s*.*$")
        self.assertIn("./environment/verify.sh", source)
        self.assertIn("-m unittest discover -s tests/host -v", source)
        self.assertIn("env -u MAKEFLAGS -u MFLAGS -u MAKELEVEL", source)
        self.assertIn("-u BUILD_DIR", source)
        self.assertIn("tools/loc.py", source)
        self.assertIn("tools/demo_persistence.py", source)

    def test_loc_report_has_required_categories(self) -> None:
        result = subprocess.run(
            [sys.executable, str(LOC_TOOL), "--repo", str(ROOT), "--format", "json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        categories = report["categories"]
        required = {
            "boot_loader_asm",
            "kernel_c",
            "kernel_asm",
            "user_programs",
            "user_libc",
            "tools",
            "tests",
            "docs",
            "generated",
            "third_party",
        }
        self.assertTrue(required.issubset(categories))
        self.assertGreater(categories["kernel_c"]["nonblank_lines"], 0)
        self.assertGreater(categories["tests"]["files"], 0)
        self.assertEqual(categories["generated"]["files"], 0)
        self.assertEqual(categories["third_party"]["files"], 0)

    def test_linux_ci_is_isolated_and_pinned(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            source,
        )
        self.assertIn(
            "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
            source,
        )
        self.assertIn("permissions:\n  contents: read", source)
        self.assertIn("environment/Containerfile", source)
        self.assertIn("/source:ro", source)
        self.assertIn("${{ runner.temp }}/miniorangeos-ci-artifacts", source)
        self.assertIn("container-build.log", source)
        self.assertIn("$CI_ARTIFACT_DIR:/artifacts", source)
        self.assertIn("bash /source/environment/ubuntu/ci-run.sh", source)
        self.assertIn("if: failure()", source)
        self.assertIn("if-no-files-found: error", source)
        self.assertNotIn("chmod -R a+rwX", source)
        self.assertNotRegex(source, r"uses:\s+[^\s]+@(main|master|v[0-9]+)\s*$")

        runner = CI_RUNNER.read_text(encoding="utf-8")
        self.assertIn("./environment/verify.sh", runner)
        self.assertIn("./environment/with-env.sh make test", runner)
        self.assertIn("ci-output.log", runner)
        self.assertIn("qemu-command-lines.txt", runner)
        self.assertIn("image-layout-summary.txt", runner)
        self.assertIn("find \"$workspace\" -type f -name '*.log'", runner)
        self.assertIn("status=${PIPESTATUS[0]}", runner)
        self.assertIn("chmod -R a+rX", runner)

    def test_linux_ci_failure_evidence_survives_runner_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minios-ci-contract-") as temporary:
            root = Path(temporary)
            source = root / "source"
            artifacts = root / "artifacts"
            fake_bin = root / "bin"
            (source / "environment").mkdir(parents=True)
            (source / "config").mkdir()
            artifacts.mkdir()
            fake_bin.mkdir()

            verify = source / "environment/verify.sh"
            verify.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            with_env = source / "environment/with-env.sh"
            with_env.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "qemu-system-i386 --machine contract\n"
                "mkdir -p build/test-logs\n"
                "printf 'serial failure\\n' >build/test-logs/qemu-serial.log\n"
                "printf 'image' >build/failure.img\n"
                "printf 'fsck failure\\n'\n"
                "exit 7\n",
                encoding="utf-8",
            )
            qemu = fake_bin / "qemu-system-i386"
            qemu.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for executable in (verify, with_env, qemu):
                executable.chmod(0o700)
            (source / "config/image-layout.json").write_text(
                '{"disk_size": 67108864}\n', encoding="utf-8"
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "MINIOS_CI_SOURCE_ROOT": str(source),
                    "MINIOS_CI_ARTIFACT_ROOT": str(artifacts),
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                }
            )
            result = subprocess.run(
                ["bash", str(CI_RUNNER)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )

            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertIn(
                "fsck failure",
                (artifacts / "ci-output.log").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "--machine contract",
                (artifacts / "qemu-command-lines.txt").read_text(encoding="utf-8"),
            )
            self.assertTrue((artifacts / "image-layout.json").is_file())
            self.assertIn(
                "build/failure.img",
                (artifacts / "image-layout-summary.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (
                    artifacts
                    / "logs/build/test-logs/qemu-serial.log"
                ).read_text(encoding="utf-8"),
                "serial failure\n",
            )

    def test_demo_and_release_checklist_are_present(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(DEMO_TOOL), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("双启动", help_result.stdout)

        checklist = CHECKLIST.read_text(encoding="utf-8")
        for heading in (
            "环境与来源",
            "构建与测试",
            "演示闭环",
            "文档与交付",
            "已知限制",
        ):
            self.assertIn(f"## {heading}", checklist)


if __name__ == "__main__":
    unittest.main()
