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
    "kernel/drivers",
    "kernel/block",
    "kernel/fs",
    "kernel/include",
    "user/crt",
    "user/libc",
    "user/programs",
    "tools",
    "tests/host",
    "tests/fixtures",
    "environment/wsl",
    "environment/ubuntu",
)

REQUIRED_FILES = (
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "README.md",
    "docs/PROJECT.md",
    "docs/DEVELOPMENT.md",
    "docs/HISTORY.md",
    "config/wsl.psd1",
    "environment/wsl/common.ps1",
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
    ".psd1",
    ".py",
    ".sh",
    ".txt",
    ".yml",
    ".yaml",
}

MACHINE_SPECIFIC_REPO_PATHS = (
    "D:" + r"\DC\program-projects\OTHER\MiniOrangeOS",
    "/mnt/" + "d/DC/program-projects/OTHER/MiniOrangeOS",
)


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

    def test_machine_specific_repository_paths_are_not_committed(self) -> None:
        violations: list[str] = []
        ignored_parts = {".git", ".state", ".venv", "build", "toolchain"}
        for path in ROOT.rglob("*"):
            relative_path = path.relative_to(ROOT)
            if not path.is_file() or any(
                part in ignored_parts for part in relative_path.parts
            ):
                continue
            if path.suffix not in TEXT_SUFFIXES and path.name not in {
                "Makefile",
                "Containerfile",
            }:
                continue
            content = path.read_text(encoding="utf-8-sig")
            for fixed_path in MACHINE_SPECIFIC_REPO_PATHS:
                if fixed_path in content:
                    violations.append(f"{relative_path.as_posix()}: {fixed_path}")
        self.assertEqual([], violations, f"发现机器特定仓库路径：{violations}")

    def test_readme_records_relocatable_authoritative_worktree(self) -> None:
        path = ROOT / "README.md"
        self.assertTrue(path.is_file(), "缺少文件：README.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("MiniOrangeOS-Dev", content)
        self.assertIn("仓库根目录", content)
        self.assertIn("自动推导", content)

    def test_readme_records_real_ubuntu_verification(self) -> None:
        path = ROOT / "README.md"
        self.assertTrue(path.is_file(), "缺少文件：README.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("rootless OCI", content)
        self.assertIn("environment/ubuntu/create.sh", content)
        self.assertIn("environment/ubuntu/run.sh", content)
        self.assertIn("environment/ubuntu/destroy.sh --all", content)
        self.assertIn("无参数只预览且不删除任何资源", content)

    def test_documentation_is_consolidated(self) -> None:
        self.assertTrue((ROOT / "docs/PROJECT.md").is_file())
        self.assertTrue((ROOT / "docs/DEVELOPMENT.md").is_file())
        self.assertTrue((ROOT / "docs/HISTORY.md").is_file())
        self.assertFalse((ROOT / "PROJECT_PLAN.md").exists())
        self.assertFalse((ROOT / "CONTRIBUTING.md").exists())

    def test_development_guide_records_relocatable_worktree_and_phase_contract(self) -> None:
        path = ROOT / "docs/DEVELOPMENT.md"
        self.assertTrue(path.is_file(), "缺少文件：docs/DEVELOPMENT.md")
        content = path.read_text(encoding="utf-8")

        self.assertIn("仓库根目录", content)
        self.assertIn("config/wsl.psd1", content)
        self.assertIn("MiniOrangeOS-Dev", content)
        self.assertIn("Git 只由 Windows 执行", content)
        self.assertIn("只负责 Linux 构建、QEMU、GDB 和测试", content)
        self.assertIn("Windows", content)
        self.assertIn("项目专用 GCC", content)
        for target in ("image", "run-curses", "test", "demo-persistence"):
            self.assertIn(f"`{target}`", content)

    def test_development_workflow_records_commit_contract(self) -> None:
        path = ROOT / "docs/DEVELOPMENT.md"
        self.assertTrue(path.is_file(), "缺少文件：docs/DEVELOPMENT.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("type(scope): summary", content)
        self.assertNotIn("<type>: <summary>", content)
        for commit_type in ("feat", "fix", "test", "refactor", "docs", "build", "chore"):
            self.assertIn(f"`{commit_type}`", content)

    def test_environment_records_t01_script_contract(self) -> None:
        path = ROOT / "docs/DEVELOPMENT.md"
        self.assertTrue(path.is_file(), "缺少文件：docs/DEVELOPMENT.md")
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
