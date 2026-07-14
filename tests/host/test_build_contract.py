"""定义 T02 最小构建系统的静态契约。"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_BUILD_FILES = (
    "Makefile",
    "config/image-layout.json",
    "tools/make_image.py",
    "boot/stage1/boot.asm",
    "boot/stage2/entry.asm",
    "boot/stage2/linker.ld",
    "boot/include/boot_info.inc",
    "kernel/arch/x86/entry.asm",
    "kernel/core/kernel.c",
    "kernel/linker.ld",
    "include/minios/abi/syscall.h",
    "include/minios/abi/errno.h",
    "user/crt/start.asm",
    "user/libc/syscall.c",
    "user/libc/string.c",
    "user/programs/init.c",
    "user/programs/echo.c",
    "user/programs/sh.c",
    "user/programs/ps.c",
    "user/programs/memtest.c",
    "user/programs/fault.c",
    "user/linker.ld",
    "kernel/include/minios/proc/elf.h",
    "kernel/include/minios/proc/program_registry.h",
    "kernel/proc/elf.c",
    "kernel/proc/program_registry.c",
    "kernel/proc/embedded_programs.asm",
    "kernel/include/minios/drivers/ata.h",
    "kernel/include/minios/block/block.h",
    "kernel/drivers/ata.c",
    "kernel/block/block.c",
    "include/minios/abi/minifs.h",
    "tools/minifs.py",
    "tools/mkfs.py",
    "tools/fsck.py",
)

GENERATED_SUFFIXES = {
    ".o",
    ".d",
    ".elf",
    ".bin",
    ".map",
    ".sym",
    ".img",
}

EXPECTED_COMPONENTS = {
    "stage1": ("boot/stage1.bin", 0, 1),
    "stage2": ("boot/stage2.bin", 1, 127),
    "kernel": ("kernel/kernel.elf", 128, 1920),
    "minifs": ("fs/minifs.img", 2048, 129024),
}


class BuildContractTests(unittest.TestCase):
    def _read_layout(self) -> dict[str, object]:
        path = ROOT / "config/image-layout.json"
        self.assertTrue(path.is_file(), "缺少镜像布局：config/image-layout.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.fail(f"镜像布局不是有效 UTF-8 JSON：{error}")
        self.assertIsInstance(value, dict, "镜像布局顶层必须是 object")
        return value

    def test_required_build_inputs_exist(self) -> None:
        missing = [path for path in REQUIRED_BUILD_FILES if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"缺少 T02 构建输入：{missing}")

    def test_makefile_declares_both_cleanup_targets(self) -> None:
        path = ROOT / "Makefile"
        self.assertTrue(path.is_file(), "缺少顶层 Makefile")
        targets = {
            match.group(1)
            for match in re.finditer(
                r"(?m)^([A-Za-z][A-Za-z0-9_-]*):(?:\s|$)",
                path.read_text(encoding="utf-8"),
            )
        }
        self.assertEqual(set(), {"clean", "distclean"} - targets)

    def test_source_tree_contains_no_generated_artifacts(self) -> None:
        generated: list[str] = []
        for directory in ("boot", "kernel", "user", "config", "tools"):
            root = ROOT / directory
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in GENERATED_SUFFIXES:
                    generated.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], generated, f"源码树出现构建产物：{generated}")

    def test_user_build_declares_static_elf_and_shared_abi(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        kernel_syscall = (ROOT / "kernel/include/minios/syscall.h").read_text(
            encoding="utf-8"
        )
        user_syscall = (ROOT / "user/libc/syscall.c").read_text(encoding="utf-8")
        self.assertIn("USER_INIT_ELF", makefile)
        self.assertIn("USER_ECHO_ELF", makefile)
        self.assertIn("USER_SH_ELF", makefile)
        self.assertIn("USER_PS_ELF", makefile)
        self.assertIn("USER_MEMTEST_ELF", makefile)
        self.assertIn("USER_FAULT_ELF", makefile)
        self.assertIn("user/linker.ld", makefile)
        self.assertIn("-ffreestanding", makefile)
        self.assertIn("-nostdlib", makefile)
        self.assertIn("<minios/abi/syscall.h>", kernel_syscall)
        self.assertIn("<minios/abi/syscall.h>", user_syscall)

    def test_kernel_declares_strict_embedded_elf_loader(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        loader = (ROOT / "kernel/proc/elf.c").read_text(encoding="utf-8")
        registry = (ROOT / "kernel/proc/program_registry.c").read_text(
            encoding="utf-8"
        )
        embedded = (ROOT / "kernel/proc/embedded_programs.asm").read_text(
            encoding="utf-8"
        )
        self.assertIn("USER_INIT_ELF", makefile)
        self.assertIn("KERNEL_EMBEDDED_PROGRAMS_OBJ", makefile)
        self.assertIn("INCBIN", embedded)
        self.assertIn("/bin/init", registry)
        self.assertIn("/bin/echo", registry)
        self.assertIn("/bin/sh", registry)
        self.assertIn("/bin/ps", registry)
        self.assertIn("/bin/memtest", registry)
        self.assertIn("/bin/fault", registry)
        for contract in (
            "ELF_TYPE_EXECUTABLE",
            "ELF_MACHINE_I386",
            "ELF_PROGRAM_LOAD",
            "file_size > program->memory_size",
            "KERNEL_BASE",
            "vmm_address_space_map",
            "vmm_address_space_protect",
            "elf_loader_validation_self_test",
        ):
            self.assertIn(contract, loader)

    def test_build_guard_waits_for_nonzero_drvfs_inode(self) -> None:
        guard = (ROOT / "tools/build_dir_guard.py").read_text(encoding="utf-8")
        self.assertIn("BUILD_IDENTITY_STABILIZE_SECONDS", guard)
        self.assertIn("status.st_ino != 0", guard)
        self.assertIn("_stable_created_status", guard)

    def test_kernel_build_declares_ata_and_block_layers(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        guard = (ROOT / "tools/build_dir_guard.py").read_text(encoding="utf-8")
        self.assertIn("KERNEL_ATA_OBJ", makefile)
        self.assertIn("KERNEL_BLOCK_OBJ", makefile)
        self.assertIn('(\"kernel\", \"block\")', guard)

    def test_build_declares_minifs_image_and_fsck(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("MINIFS_IMAGE", makefile)
        self.assertIn("tools/mkfs.py", makefile)
        self.assertIn("tools/fsck.py", makefile)
        self.assertIn("test-image", makefile)

    def test_image_layout_has_one_unambiguous_source_of_truth(self) -> None:
        layout = self._read_layout()
        self.assertEqual(
            {"format_version", "sector_size", "image_size_bytes", "components"},
            set(layout),
            "镜像布局顶层字段不稳定",
        )
        self.assertIs(type(layout.get("format_version")), int)
        self.assertIs(type(layout.get("sector_size")), int)
        self.assertIs(type(layout.get("image_size_bytes")), int)
        self.assertEqual(1, layout.get("format_version"))
        self.assertEqual(512, layout.get("sector_size"))
        self.assertEqual(64 * 1024 * 1024, layout.get("image_size_bytes"))

        components = layout.get("components")
        self.assertIsInstance(components, list, "components 必须是数组")
        assert isinstance(components, list)

        normalized: dict[str, tuple[str, int, int]] = {}
        for index, component in enumerate(components):
            self.assertIsInstance(component, dict, f"components[{index}] 必须是 object")
            assert isinstance(component, dict)
            self.assertEqual(
                {"name", "artifact", "lba", "max_sectors"},
                set(component),
                f"components[{index}] 字段不稳定",
            )
            name = component.get("name")
            artifact = component.get("artifact")
            lba = component.get("lba")
            max_sectors = component.get("max_sectors")
            self.assertIsInstance(name, str)
            self.assertIsInstance(artifact, str)
            self.assertIs(type(lba), int)
            self.assertIs(type(max_sectors), int)
            assert isinstance(name, str)
            assert isinstance(artifact, str)
            assert isinstance(lba, int)
            assert isinstance(max_sectors, int)
            self.assertNotIn(name, normalized, f"重复组件：{name}")
            self.assertFalse(Path(artifact).is_absolute(), f"artifact 必须相对 BUILD_DIR：{artifact}")
            self.assertNotIn("..", Path(artifact).parts, f"artifact 不得逃逸 BUILD_DIR：{artifact}")
            self.assertGreaterEqual(lba, 0)
            self.assertGreater(max_sectors, 0)
            normalized[name] = (artifact, lba, max_sectors)

        self.assertEqual(EXPECTED_COMPONENTS, normalized)

        image_sectors = int(layout["image_size_bytes"]) // int(layout["sector_size"])
        regions = sorted(
            (lba, lba + max_sectors, name)
            for name, (_, lba, max_sectors) in normalized.items()
        )
        for index, (start, end, name) in enumerate(regions):
            self.assertLessEqual(end, image_sectors, f"组件越过镜像边界：{name}")
            if index:
                self.assertGreaterEqual(
                    start,
                    regions[index - 1][1],
                    f"组件区域重叠：{regions[index - 1][2]} 与 {name}",
                )


if __name__ == "__main__":
    unittest.main()
