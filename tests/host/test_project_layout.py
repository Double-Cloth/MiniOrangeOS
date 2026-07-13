"""验证 T00 仓库骨架和文本策略。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DIRECTORIES = (
    "boot/stage1",
    "boot/stage2",
    "boot/include",
    "kernel/arch/x86",
    "kernel/core",
    "kernel/mm",
    "kernel/proc",
    "kernel/syscall",
    "kernel/drivers",
    "kernel/block",
    "kernel/fs",
    "kernel/include",
    "user/crt",
    "user/libc",
    "user/programs",
    "tools",
    "tests/host",
    "tests/qemu",
    "tests/fixtures",
    "environment/wsl",
    "environment/ubuntu",
    "docs/decisions",
    "docs/task-reports",
)

REQUIRED_FILES = (
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "PROJECT_PLAN.md",
    "docs/coding-standards.md",
    "docs/progress.md",
    "docs/review-notes.md",
    "docs/decisions/0001-windows-worktree-wsl-tests.md",
    "environment/README.md",
)

REQUIRED_IGNORE_RULES = {
    "/build/",
    "*.img",
    "*.iso",
    "*.o",
    "*.elf",
    "*.bin",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    "/.cache/",
    "/environment/.state/",
}

REQUIRED_ATTRIBUTE_RULES = {
    "* text=auto eol=lf",
    "*.ps1 text eol=lf",
    "*.sh text eol=lf",
    "Makefile text eol=lf",
}

TEXT_SUFFIXES = {
    ".asm",
    ".c",
    ".h",
    ".ld",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".txt",
    ".yml",
    ".yaml",
}


class ProjectLayoutTests(unittest.TestCase):
    def test_required_directories_exist(self) -> None:
        missing = [path for path in REQUIRED_DIRECTORIES if not (ROOT / path).is_dir()]
        self.assertEqual([], missing, f"缺少目录：{missing}")

    def test_required_files_exist(self) -> None:
        missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"缺少文件：{missing}")

    def test_gitignore_contains_required_rules(self) -> None:
        path = ROOT / ".gitignore"
        self.assertTrue(path.is_file(), "缺少文件：.gitignore")
        rules = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(set(), REQUIRED_IGNORE_RULES - rules)

    def test_gitattributes_contains_required_rules(self) -> None:
        path = ROOT / ".gitattributes"
        self.assertTrue(path.is_file(), "缺少文件：.gitattributes")
        rules = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(set(), REQUIRED_ATTRIBUTE_RULES - rules)

    def test_text_files_use_lf(self) -> None:
        bad_files: list[str] = []
        for path in ROOT.rglob("*"):
            relative_path = path.relative_to(ROOT)
            if not path.is_file() or any(
                part in {".git", ".superpowers"} for part in relative_path.parts
            ):
                continue
            is_text = (
                path.suffix in TEXT_SUFFIXES
                or path.name in {
                    "Makefile",
                    "Containerfile",
                    "LICENSE",
                    ".gitignore",
                    ".gitattributes",
                    ".gitkeep",
                }
            )
            if not is_text:
                continue

            data = path.read_bytes()
            relative_name = relative_path.as_posix()
            try:
                data.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                bad_files.append(f"{relative_name}: 非 UTF-8")
            if b"\r" in data:
                bad_files.append(f"{relative_name}: 包含 CR")
        self.assertEqual([], bad_files, f"文本策略失败：{bad_files}")

    def test_readme_records_authoritative_worktree(self) -> None:
        path = ROOT / "README.md"
        self.assertTrue(path.is_file(), "缺少文件：README.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("D:\\DC\\program-projects\\OTHER\\MiniOrangeOS", content)
        self.assertIn("MiniOrangeOS-Dev", content)
        self.assertIn("/mnt/d/DC/program-projects/OTHER/MiniOrangeOS", content)

    def test_readme_records_real_ubuntu_verification(self) -> None:
        path = ROOT / "README.md"
        self.assertTrue(path.is_file(), "缺少文件：README.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("rootless OCI", content)
        self.assertIn("environment/ubuntu/create.sh", content)
        self.assertIn("environment/ubuntu/run.sh", content)
        self.assertIn("environment/ubuntu/destroy.sh --all", content)
        self.assertIn("T01 完成后可用", content)

    def test_project_plan_has_stable_name(self) -> None:
        self.assertTrue((ROOT / "PROJECT_PLAN.md").is_file())
        self.assertFalse((ROOT / "MiniOrangeOS_Codex_Project_Plan_v1.1.md").exists())

    def test_project_plan_records_t01_windows_boundary(self) -> None:
        path = ROOT / "PROJECT_PLAN.md"
        self.assertTrue(path.is_file(), "缺少文件：PROJECT_PLAN.md")
        content = path.read_text(encoding="utf-8")

        t01_start = content.index("### T01：")
        t02_start = content.index("### T02：", t01_start)
        t01_content = content[t01_start:t02_start]
        self.assertNotIn("Windows 只允许使用专用 WSL2", t01_content)
        self.assertIn("Windows Git 负责版本控制和文件编辑", t01_content)
        self.assertIn("不安装 Windows 原生编译、调试或虚拟化工具链", t01_content)
        self.assertIn("Linux 构建和测试仅在专用 WSL 或真实 Ubuntu 隔离模型中执行", t01_content)

    def test_development_workflow_records_commit_contract(self) -> None:
        path = ROOT / "docs/development-workflow.md"
        self.assertTrue(path.is_file(), "缺少文件：docs/development-workflow.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("type(scope): summary", content)
        self.assertNotIn("<type>: <summary>", content)
        for commit_type in ("feat", "fix", "test", "refactor", "docs", "build", "chore"):
            self.assertIn(f"`{commit_type}`", content)

    def test_environment_records_t01_script_contract(self) -> None:
        path = ROOT / "docs/environment.md"
        self.assertTrue(path.is_file(), "缺少文件：docs/environment.md")
        content = path.read_text(encoding="utf-8")
        required_scripts = (
            "environment/wsl/create.ps1",
            "environment/wsl/enter.ps1",
            "environment/wsl/backup.ps1",
            "environment/wsl/destroy.ps1",
            "environment/Containerfile",
            "environment/ubuntu/create.sh",
            "environment/ubuntu/run.sh",
            "environment/ubuntu/destroy.sh",
            "environment/bootstrap-inside.sh",
            "environment/with-env.sh",
            "environment/verify.sh",
            "tools/build_toolchain.sh",
        )
        for script in required_scripts:
            self.assertIn(script, content)


if __name__ == "__main__":
    unittest.main()
