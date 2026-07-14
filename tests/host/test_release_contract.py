"""验证 P7 聚合测试、CI、代码量与发布材料合同。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github/workflows/ci.yml"
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
        self.assertRegex(source, r"actions/checkout@[0-9a-f]{40}")
        self.assertIn("permissions:\n  contents: read", source)
        self.assertIn("environment/Containerfile", source)
        self.assertIn("/source:ro", source)
        self.assertIn("./environment/verify.sh", source)
        self.assertIn("./environment/with-env.sh make test", source)
        self.assertNotIn("chmod -R a+rwX", source)
        self.assertNotRegex(source, r"uses:\s+[^\s]+@(main|master|v[0-9]+)\s*$")

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
