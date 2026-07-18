"""在 Linux/WSL 中验证 Stage 2 实模式接口与 P1 模式切换。"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE2_SOURCE = ROOT / "boot/stage2/entry.asm"
KERNEL_ENTRY_SOURCE = ROOT / "kernel/arch/x86/entry.asm"
KERNEL_CONSOLE_SOURCE = ROOT / "kernel/core/console.c"
KERNEL_PANIC_SOURCE = ROOT / "kernel/core/panic.c"
KERNEL_SERIAL_SOURCE = ROOT / "kernel/drivers/serial.c"
KERNEL_VGA_SOURCE = ROOT / "kernel/drivers/vga.c"
KERNEL_GDT_SOURCE = ROOT / "kernel/arch/x86/gdt.c"
KERNEL_GDT_ASSEMBLY = ROOT / "kernel/arch/x86/gdt.asm"
KERNEL_IDT_SOURCE = ROOT / "kernel/arch/x86/idt.c"
KERNEL_EXCEPTION_ASSEMBLY = ROOT / "kernel/arch/x86/exceptions.asm"
KERNEL_EXCEPTION_SOURCE = ROOT / "kernel/arch/x86/exception.c"
KERNEL_TRAP_FRAME_HEADER = ROOT / "kernel/include/minios/arch/x86/trap_frame.h"
KERNEL_IRQ_ASSEMBLY = ROOT / "kernel/arch/x86/irqs.asm"
KERNEL_IRQ_SOURCE = ROOT / "kernel/arch/x86/irq.c"
KERNEL_PIC_SOURCE = ROOT / "kernel/drivers/pic.c"
KERNEL_PIT_SOURCE = ROOT / "kernel/drivers/pit.c"
KERNEL_KEYBOARD_SOURCE = ROOT / "kernel/drivers/keyboard.c"
KERNEL_INPUT_HEADER = ROOT / "include/minios/abi/input.h"
KERNEL_BOOT_INFO_HEADER = ROOT / "kernel/include/minios/boot_info.h"
KERNEL_PMM_SOURCE = ROOT / "kernel/mm/pmm.c"
KERNEL_VMM_SOURCE = ROOT / "kernel/mm/vmm.c"
KERNEL_HEAP_SOURCE = ROOT / "kernel/mm/heap.c"
KERNEL_ADDRESS_SPACE_SOURCE = ROOT / "kernel/mm/address_space.c"
KERNEL_USERCOPY_SOURCE = ROOT / "kernel/mm/usercopy.c"
KERNEL_SCHEDULER_SOURCE = ROOT / "kernel/proc/scheduler.c"
KERNEL_CONTEXT_ASSEMBLY = ROOT / "kernel/arch/x86/context_switch.asm"
KERNEL_USER_MODE_ASSEMBLY = ROOT / "kernel/arch/x86/user_mode.asm"
KERNEL_SYSCALL_SOURCE = ROOT / "kernel/core/syscall.c"
KERNEL_ATA_SOURCE = ROOT / "kernel/drivers/ata.c"
KERNEL_BLOCK_HEADER = ROOT / "kernel/include/minios/block/block.h"
KERNEL_BLOCK_SOURCE = ROOT / "kernel/block/block.c"
KERNEL_MINIFS_HEADER = ROOT / "kernel/include/minios/fs/minifs.h"
KERNEL_MINIFS_SOURCE = ROOT / "kernel/fs/minifs.c"
KERNEL_VFS_HEADER = ROOT / "kernel/include/minios/fs/vfs.h"
KERNEL_VFS_SOURCE = ROOT / "kernel/fs/vfs.c"
MINIFS_LAYOUT_TOOL = ROOT / "tools/generate_minifs_layout.py"
BIOS_FIXTURE_SOURCE = ROOT / "tests/fixtures/boot/stage2_bios_interfaces.asm"
QEMU = os.environ.get("MINIOS_QEMU", "qemu-system-i386")


def _is_supported_linux() -> bool:
    return sys.platform.startswith("linux")


@unittest.skipUnless(_is_supported_linux(), "Stage 2 构建与真实 QEMU 验证只在 Linux 环境执行")
class BootStage2Tests(unittest.TestCase):
    temporary_directory: tempfile.TemporaryDirectory[str]
    build_relative: Path
    build_directory: Path
    stage2_binary: Path
    stage2_elf: Path
    kernel_elf: Path
    image: Path
    disassembly: list[tuple[int, str]]
    symbols: dict[str, int]
    ordered_symbols: list[tuple[int, str]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix=".p1-stage2-host-", dir=ROOT
        )
        temporary_root = Path(cls.temporary_directory.name)
        cls.build_directory = temporary_root / "build"
        cls.build_relative = cls.build_directory.relative_to(ROOT)

        result = cls._run_make("-j4", "image", timeout=90)
        if result.returncode != 0:
            raise AssertionError(
                "Stage 2 正式镜像构建失败：\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        cls.stage2_binary = cls.build_directory / "boot/stage2.bin"
        cls.stage2_elf = cls.build_directory / "boot/stage2.elf"
        cls.kernel_elf = cls.build_directory / "kernel/kernel.elf"
        cls.image = cls.build_directory / "miniorangeos.img"

        disassembled = cls._run_tool(
            "ndisasm",
            "-b",
            "16",
            "-o",
            "0x8000",
            str(cls.stage2_binary),
            timeout=15,
        )
        if disassembled.returncode != 0:
            raise AssertionError(disassembled.stdout + disassembled.stderr)
        cls.disassembly = []
        for line in disassembled.stdout.lower().splitlines():
            match = re.fullmatch(
                r"([0-9a-f]{8})\s+[0-9a-f]+\s+(.+)", line.strip()
            )
            if match is not None:
                cls.disassembly.append((int(match.group(1), 16), match.group(2)))

        symbol_result = cls._run_tool(
            "i686-elf-nm",
            "-n",
            "--defined-only",
            str(cls.stage2_elf),
            timeout=15,
        )
        if symbol_result.returncode != 0:
            raise AssertionError(symbol_result.stdout + symbol_result.stderr)
        cls.symbols = {}
        for line in symbol_result.stdout.splitlines():
            match = re.fullmatch(
                r"([0-9a-fA-F]+)\s+([A-Z])\s+(\S+)", line.strip()
            )
            if match is not None:
                cls.symbols[match.group(3)] = int(match.group(1), 16)
        cls.ordered_symbols = sorted(
            (address, name) for name, address in cls.symbols.items()
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    @classmethod
    def _run_make(
        cls, *arguments: str, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={cls.build_relative.as_posix()}",
                *arguments,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _run_tool(
        tool: str, *arguments: str, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "environment/with-env.sh", tool, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    @classmethod
    def _symbol_instructions(cls, name: str) -> list[str]:
        start = cls.symbols[name]
        following = [
            address
            for address, _symbol_name in cls.ordered_symbols
            if address > start
        ]
        end = following[0] if following else start + 0x100
        return [
            instruction
            for address, instruction in cls.disassembly
            if start <= address < end
        ]

    @classmethod
    def _build_bios_fixture_image(cls) -> Path:
        fixture_directory = cls.build_directory / "test-fixtures/stage2-bios"
        fixture_directory.mkdir(parents=True, exist_ok=True)
        fixture_object = fixture_directory / "fixture.o"
        stage2_object = fixture_directory / "stage2-entry.o"
        fixture_elf = fixture_directory / "fixture.elf"
        fixture_binary = fixture_directory / "fixture.bin"
        fixture_image = fixture_directory / "fixture.img"
        linker_script = fixture_directory / "fixture.ld"
        linker_script.write_text(
            """OUTPUT_FORMAT(elf32-i386)
OUTPUT_ARCH(i386)
ENTRY(fixture_entry)
SECTIONS
{
    . = 0x8000;
    .fixture_entry : { KEEP(*(.fixture.entry)) }
    .stage2_entry : { KEEP(*(.text16.entry)) }
    .text16 : { *(.text16*) }
    .rodata16 : { *(.rodata16*) }
    .data16 : { *(.data16*) }
    .fixture_data : { *(.fixture.data*) }
    .bss : { *(.bss*) *(COMMON) }
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
ASSERT(fixture_entry == 0x8000, "fixture entry moved")
ASSERT(. <= 0x10000, "fixture exceeds 16-bit address space")
""",
            encoding="ascii",
        )

        commands = (
            (
                "nasm",
                "-I",
                f"{cls.build_directory / 'boot'}/",
                "-I",
                f"{ROOT / 'boot/include'}/",
                "-f",
                "elf32",
                "-o",
                str(stage2_object),
                str(STAGE2_SOURCE),
            ),
            (
                "nasm",
                "-f",
                "elf32",
                "-o",
                str(fixture_object),
                str(BIOS_FIXTURE_SOURCE),
            ),
            (
                "i686-elf-ld",
                "-m",
                "elf_i386",
                "-nostdlib",
                "-T",
                str(linker_script),
                "-o",
                str(fixture_elf),
                str(fixture_object),
                str(stage2_object),
            ),
            (
                "i686-elf-objcopy",
                "-O",
                "binary",
                str(fixture_elf),
                str(fixture_binary),
            ),
        )
        for command in commands:
            result = cls._run_tool(command[0], *command[1:], timeout=20)
            if result.returncode != 0:
                raise AssertionError(
                    f"Stage 2 BIOS fixture 构建失败：{' '.join(command)}\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )

        payload = fixture_binary.read_bytes()
        if not payload or len(payload) > 127 * 512:
            raise AssertionError(f"Stage 2 BIOS fixture 大小非法：{len(payload)}")
        shutil.copyfile(cls.image, fixture_image)
        with fixture_image.open("r+b") as image_file:
            image_file.seek(512)
            image_file.write(bytes(127 * 512))
            image_file.seek(512)
            image_file.write(payload)
        return fixture_image

    def test_source_declares_both_cpu_modes_and_public_interfaces(self) -> None:
        source = STAGE2_SOURCE.read_text(encoding="utf-8")
        self.assertRegex(source, r"(?im)^\s*BITS\s+16\s*$")
        self.assertRegex(source, r"(?im)^\s*BITS\s+32\s*$")

        readelf = self._run_tool(
            "i686-elf-readelf", "-sW", str(self.stage2_elf), timeout=15
        )
        self.assertEqual(readelf.returncode, 0, readelf.stdout + readelf.stderr)
        for symbol in (
            "stage2_entry",
            "stage2_protected_entry",
            "stage2_boot_drive",
            "e820_entry_count",
            "bios_write_char",
            "bios_disk_read_edd",
        ):
            self.assertRegex(
                readelf.stdout,
                rf"(?m)^\s*\d+:\s+[0-9a-fA-F]+\s+\d+\s+\S+\s+GLOBAL\s+\S+\s+\S+\s+{re.escape(symbol)}$",
                f"{symbol} 必须作为可链接的全局接口导出",
            )

    def test_source_bounds_e820_and_sets_cr0_pe_before_far_jump(self) -> None:
        source = STAGE2_SOURCE.read_text(encoding="utf-8")
        required_patterns = {
            "E820 缓冲地址": r"(?m)^%define E820_BUFFER_SEGMENT\s+0x1800$",
            "E820 固定条目大小": r"(?m)^%define E820_ENTRY_SIZE\s+24$",
            "E820 条目上限": r"(?m)^%define E820_MAX_ENTRIES\s+128$",
            "加载临时 GDT": r"(?m)^\s*lgdt \[gdt_descriptor\]$",
            "读取 CR0": r"(?m)^\s*mov eax, cr0$",
            "写回 CR0": r"(?m)^\s*mov cr0, eax$",
            "远跳保护模式入口": (
                r"(?m)^\s*jmp dword GDT_CODE_SELECTOR:stage2_protected_entry$"
            ),
        }
        missing = [
            description
            for description, pattern in required_patterns.items()
            if re.search(pattern, source) is None
        ]
        self.assertEqual(missing, [], f"Stage 2 模式切换合同缺少：{', '.join(missing)}")

    def test_stage2_artifacts_are_elf32_and_bounded_binary(self) -> None:
        payload = self.stage2_binary.read_bytes()
        self.assertGreater(len(payload), 0, "stage2.bin 不得为空")
        self.assertLessEqual(len(payload), 127 * 512, "stage2.bin 越过 Loader 保留区")

        header = self._run_tool(
            "i686-elf-readelf", "-h", str(self.stage2_elf), timeout=15
        )
        self.assertEqual(header.returncode, 0, header.stdout + header.stderr)
        required = {
            "ELF32": r"Class:\s+ELF32",
            "小端序": r"Data:\s+2's complement, little endian",
            "i386": r"Machine:\s+Intel 80386",
            "可执行文件": r"Type:\s+EXEC",
            "入口 0x8000": r"Entry point address:\s+0x8000\b",
        }
        missing = [
            description
            for description, pattern in required.items()
            if re.search(pattern, header.stdout) is None
        ]
        self.assertEqual(missing, [], f"stage2.elf 头缺少：{', '.join(missing)}")

    def test_kernel_elf_is_high_half_with_physical_load_addresses(self) -> None:
        header = self._run_tool(
            "i686-elf-readelf", "-hW", str(self.kernel_elf), timeout=15
        )
        segments = self._run_tool(
            "i686-elf-readelf", "-lW", str(self.kernel_elf), timeout=15
        )
        self.assertEqual(header.returncode, 0, header.stdout + header.stderr)
        self.assertEqual(segments.returncode, 0, segments.stdout + segments.stderr)
        self.assertRegex(header.stdout, r"Entry point address:\s+0x[cC][0-9a-fA-F]{7}\b")

        load_segments = re.findall(
            r"(?m)^\s*LOAD\s+\S+\s+(0x[0-9a-fA-F]+)\s+"
            r"(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+"
            r"(0x[0-9a-fA-F]+)\s+.+$",
            segments.stdout,
        )
        nonempty_load_segments = [
            (virtual_text, physical_text)
            for virtual_text, physical_text, _file_size, memory_size in load_segments
            if int(memory_size, 16) != 0
        ]
        self.assertTrue(nonempty_load_segments, "Kernel ELF 至少需要一个非空 PT_LOAD")
        for virtual_text, physical_text in nonempty_load_segments:
            virtual = int(virtual_text, 16)
            physical = int(physical_text, 16)
            self.assertGreaterEqual(virtual, 0xC0000000)
            self.assertGreaterEqual(physical, 0x00100000)
            self.assertEqual(0xC0000000, virtual - physical)

    def test_kernel_entry_declares_early_paging_and_bss_contract(self) -> None:
        source = KERNEL_ENTRY_SOURCE.read_text(encoding="utf-8")
        required_patterns = {
            "页目录": r"(?m)^global boot_page_directory$",
            "页表": r"(?m)^global boot_page_table$",
            "加载 CR3": r"(?m)^\s*mov cr3, eax$",
            "开启分页": r"(?m)^\s*or eax, 0x80000000$",
            "高半入口": r"(?m)^global kernel_high_entry$",
            "清零 BSS": r"(?m)^\s*rep stosb$",
        }
        missing = [
            description
            for description, pattern in required_patterns.items()
            if re.search(pattern, source) is None
        ]
        self.assertEqual(missing, [], f"内核早期分页合同缺少：{', '.join(missing)}")

    def test_kernel_console_and_panic_contract(self) -> None:
        required_sources = {
            "控制台": KERNEL_CONSOLE_SOURCE,
            "panic": KERNEL_PANIC_SOURCE,
            "COM1": KERNEL_SERIAL_SOURCE,
            "VGA": KERNEL_VGA_SOURCE,
        }
        missing_files = [
            description
            for description, source in required_sources.items()
            if not source.is_file()
        ]
        self.assertEqual(missing_files, [], f"内核输出源码缺少：{', '.join(missing_files)}")

        console = KERNEL_CONSOLE_SOURCE.read_text(encoding="utf-8")
        panic = KERNEL_PANIC_SOURCE.read_text(encoding="utf-8")
        serial = KERNEL_SERIAL_SOURCE.read_text(encoding="utf-8")
        vga = KERNEL_VGA_SOURCE.read_text(encoding="utf-8")
        for specifier in ("%s", "%c", "%u", "%d", "%x", "%p", "%%"):
            self.assertIn(specifier, console)
        self.assertIn("_Noreturn void panic", panic)
        self.assertIn("0x03F8", serial)
        self.assertIn("0xC00B8000", vga)

    def test_kernel_declares_formal_ring0_gdt_contract(self) -> None:
        self.assertTrue(KERNEL_GDT_SOURCE.is_file(), "缺少正式 GDT C 实现")
        self.assertTrue(KERNEL_GDT_ASSEMBLY.is_file(), "缺少正式 GDT 加载入口")
        source = KERNEL_GDT_SOURCE.read_text(encoding="utf-8")
        assembly = KERNEL_GDT_ASSEMBLY.read_text(encoding="utf-8")
        self.assertIn("0x9A", source)
        self.assertIn("0x92", source)
        self.assertIn("0xCF", source)
        self.assertIn("lgdt", assembly)
        self.assertIn("jmp 0x08:", assembly)

    def test_kernel_declares_ring3_segments_and_tss_contract(self) -> None:
        source = KERNEL_GDT_SOURCE.read_text(encoding="utf-8")
        assembly = KERNEL_GDT_ASSEMBLY.read_text(encoding="utf-8")
        header = (ROOT / "kernel/include/minios/arch/x86/gdt.h").read_text(
            encoding="utf-8"
        )
        self.assertIn("GDT_ENTRY_COUNT 6U", source)
        self.assertIn("GDT_USER_CODE_ACCESS 0xFAU", source)
        self.assertIn("GDT_USER_DATA_ACCESS 0xF2U", source)
        self.assertIn("GDT_TSS_ACCESS 0x89U", source)
        self.assertIn("struct task_state_segment", source)
        self.assertIn("io_map_base", source)
        self.assertIn("tss_load", source)
        self.assertIn("ltr", assembly)
        self.assertIn("gdt_set_kernel_stack", header)

    def test_kernel_declares_idt_and_exception_contract(self) -> None:
        required = (
            KERNEL_IDT_SOURCE,
            KERNEL_EXCEPTION_ASSEMBLY,
            KERNEL_EXCEPTION_SOURCE,
            KERNEL_TRAP_FRAME_HEADER,
        )
        self.assertEqual([path.name for path in required if not path.is_file()], [])
        idt = KERNEL_IDT_SOURCE.read_text(encoding="utf-8")
        stubs = KERNEL_EXCEPTION_ASSEMBLY.read_text(encoding="utf-8")
        handler = KERNEL_EXCEPTION_SOURCE.read_text(encoding="utf-8")
        trap_frame = KERNEL_TRAP_FRAME_HEADER.read_text(encoding="utf-8")
        self.assertIn("IDT_ENTRY_COUNT 256", idt)
        self.assertIn("IDT_INTERRUPT_GATE 0x8E", idt)
        self.assertIn("exception_stub_table", stubs)
        self.assertEqual(len(re.findall(r"(?m)^EXCEPTION_(?:NO_ERROR|ERROR) \d+$", stubs)), 32)
        self.assertIn("struct trap_frame", trap_frame)
        self.assertIn("panicf", handler)

    def test_kernel_declares_pic_pit_and_irq_contract(self) -> None:
        required = (
            KERNEL_IRQ_ASSEMBLY,
            KERNEL_IRQ_SOURCE,
            KERNEL_PIC_SOURCE,
            KERNEL_PIT_SOURCE,
        )
        self.assertEqual([path.name for path in required if not path.is_file()], [])
        irqs = KERNEL_IRQ_ASSEMBLY.read_text(encoding="utf-8")
        pic = KERNEL_PIC_SOURCE.read_text(encoding="utf-8")
        pit = KERNEL_PIT_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"(?m)^IRQ_STUB \d+$", irqs)), 16)
        self.assertIn("0x20", pic)
        self.assertIn("0x28", pic)
        self.assertIn("pic_send_eoi", pic)
        self.assertIn("1193182", pit)
        self.assertIn("[KERN] pit tick=%u", pit)

    def test_kernel_declares_ps2_keyboard_contract(self) -> None:
        self.assertTrue(KERNEL_KEYBOARD_SOURCE.is_file(), "缺少 PS/2 键盘驱动")
        self.assertTrue(KERNEL_INPUT_HEADER.is_file(), "缺少内核与用户态共享的按键 ABI")
        source = KERNEL_KEYBOARD_SOURCE.read_text(encoding="utf-8")
        input_abi = KERNEL_INPUT_HEADER.read_text(encoding="utf-8")
        self.assertIn("0x0060", source)
        self.assertIn("0x0064", source)
        self.assertIn("KEYBOARD_BUFFER_SIZE", source)
        self.assertIn("keyboard_try_read", source)
        self.assertIn("PS2_POLL_LIMIT", source)
        for key_name in (
            "MINIOS_KEY_LEFT",
            "MINIOS_KEY_RIGHT",
            "MINIOS_KEY_UP",
            "MINIOS_KEY_DOWN",
            "MINIOS_KEY_HOME",
            "MINIOS_KEY_END",
            "MINIOS_KEY_DELETE",
        ):
            self.assertIn(key_name, input_abi)
        for extended_scancode in ("0x47", "0x48", "0x4B", "0x4D", "0x4F", "0x50", "0x53"):
            self.assertIn(extended_scancode, source)
        for punctuation in ("'-'", "'='", "'['", "']'", "';'", "'\"'", "'`'", "'\\\\'", "','", "'.'", "'/'"):
            self.assertIn(punctuation, source)
        self.assertIn("left_shift_pressed", source)
        self.assertIn("right_shift_pressed", source)
        self.assertIn("left_ctrl_pressed", source)
        self.assertIn("right_ctrl_pressed", source)

    def test_vga_supports_shell_editing_control_sequences(self) -> None:
        source = KERNEL_VGA_SOURCE.read_text(encoding="utf-8")
        self.assertIn("'\\b'", source)
        self.assertIn("0x03D4", source)
        self.assertIn("0x03D5", source)
        self.assertIn("VGA_ESCAPE", source)
        self.assertIn("vga_clear", source)

    def test_kernel_declares_boot_info_and_pmm_contract(self) -> None:
        self.assertTrue(KERNEL_BOOT_INFO_HEADER.is_file(), "缺少 Boot Info C 合同")
        self.assertTrue(KERNEL_PMM_SOURCE.is_file(), "缺少 PMM 实现")
        boot_info = KERNEL_BOOT_INFO_HEADER.read_text(encoding="utf-8")
        pmm = KERNEL_PMM_SOURCE.read_text(encoding="utf-8")
        self.assertIn("_Static_assert(sizeof(struct boot_info) == 64U", boot_info)
        self.assertIn("_Static_assert(sizeof(struct e820_entry) == 24U", boot_info)
        self.assertIn("PMM_MAX_PAGES 1048576U", pmm)
        self.assertIn("allocatable_bitmap", pmm)
        self.assertIn("bool pmm_free", pmm)
        self.assertIn("e820_entries", pmm)

    def test_kernel_declares_formal_vmm_contract(self) -> None:
        self.assertTrue(KERNEL_VMM_SOURCE.is_file(), "缺少正式 VMM 实现")
        source = KERNEL_VMM_SOURCE.read_text(encoding="utf-8")
        self.assertIn("RECURSIVE_PAGE_TABLES 0xFFC00000U", source)
        self.assertIn("RECURSIVE_PAGE_DIRECTORY 0xFFFFF000U", source)
        self.assertIn("CR0_WRITE_PROTECT 0x00010000U", source)
        self.assertIn("invlpg", source)
        self.assertIn("bool vmm_map", source)
        self.assertIn("bool vmm_unmap", source)
        self.assertIn("page_directory[0] = 0U", source)

    def test_kernel_declares_first_fit_heap_contract(self) -> None:
        self.assertTrue(KERNEL_HEAP_SOURCE.is_file(), "缺少内核堆实现")
        source = KERNEL_HEAP_SOURCE.read_text(encoding="utf-8")
        self.assertIn("HEAP_ALIGNMENT 8U", source)
        self.assertIn("HEAP_MAGIC 0x48454150U", source)
        self.assertIn("find_first_fit", source)
        self.assertIn("split_block", source)
        self.assertIn("coalesce", source)
        self.assertIn("void *kmalloc", source)
        self.assertIn("bool kfree", source)
        self.assertIn("vmm_map", source)
        self.assertIn("#include <minios/arch/x86/irq.h>", source)
        self.assertIn("irq_save_disable", source)
        self.assertIn("irq_restore", source)

    def test_kernel_declares_user_memory_safety_contract(self) -> None:
        self.assertTrue(KERNEL_USERCOPY_SOURCE.is_file(), "缺少 usercopy 实现")
        self.assertTrue(KERNEL_ADDRESS_SPACE_SOURCE.is_file(), "缺少用户地址空间实现")
        address_space = KERNEL_ADDRESS_SPACE_SOURCE.read_text(encoding="utf-8")
        usercopy = KERNEL_USERCOPY_SOURCE.read_text(encoding="utf-8")
        exception = KERNEL_EXCEPTION_SOURCE.read_text(encoding="utf-8")
        self.assertIn("vmm_address_space_create", address_space)
        self.assertIn("vmm_address_space_destroy", address_space)
        self.assertIn("vmm_address_space_map", address_space)
        self.assertIn("vmm_address_space_protect", address_space)
        self.assertIn("vmm_address_space_activate", address_space)
        self.assertIn("vmm_kernel_page_directory", address_space)
        self.assertIn("vmm_current_page_directory", address_space)
        self.assertIn("vmm_activate_page_directory", address_space)
        self.assertIn("irq_save_disable", address_space)
        self.assertIn("KERNEL_PDE_INDEX", address_space)
        self.assertIn("validate_user_range", usercopy)
        self.assertIn("copy_from_user", usercopy)
        self.assertIn("copy_to_user", usercopy)
        self.assertIn("copy_user_string", usercopy)
        self.assertIn("MINIOS_EFAULT", usercopy)
        self.assertIn("read_cr2", exception)
        self.assertIn("PAGE_FAULT_USER", exception)
        self.assertIn("user_page_fault_handler", exception)

    def test_kernel_declares_cooperative_thread_scheduler_contract(self) -> None:
        self.assertTrue(KERNEL_SCHEDULER_SOURCE.is_file(), "缺少调度器实现")
        self.assertTrue(KERNEL_CONTEXT_ASSEMBLY.is_file(), "缺少上下文切换入口")
        source = KERNEL_SCHEDULER_SOURCE.read_text(encoding="utf-8")
        assembly = KERNEL_CONTEXT_ASSEMBLY.read_text(encoding="utf-8")
        for field in (
            "pid",
            "state",
            "name[32]",
            "saved_stack",
            "kernel_stack_top",
            "page_directory",
            "exit_code",
            "parent_pid",
            "wake_tick",
            "time_slice",
            "fd_table",
            "current_working_directory",
        ):
            self.assertIn(field, source)
        self.assertIn("PROCESS_READY", source)
        self.assertIn("PROCESS_RUNNING", source)
        self.assertIn("PROCESS_ZOMBIE", source)
        self.assertIn("scheduler_yield", source)
        self.assertIn("scheduler_on_tick", source)
        self.assertIn("scheduler_sleep_current", source)
        self.assertIn("scheduler_waitpid", source)
        self.assertIn("allocate_pid", source)
        self.assertIn("scheduler_lifecycle_self_test", source)
        self.assertIn("scheduler_preemption_self_test", source)
        self.assertIn("context_switch", source)
        self.assertIn("push ebp", assembly)
        self.assertIn("mov esp, edx", assembly)

    def test_kernel_declares_ring3_syscall_contract(self) -> None:
        self.assertTrue(KERNEL_USER_MODE_ASSEMBLY.is_file(), "缺少 Ring 3 汇编入口")
        self.assertTrue(KERNEL_SYSCALL_SOURCE.is_file(), "缺少系统调用分发实现")
        user_mode = KERNEL_USER_MODE_ASSEMBLY.read_text(encoding="utf-8")
        syscall = KERNEL_SYSCALL_SOURCE.read_text(encoding="utf-8")
        idt = KERNEL_IDT_SOURCE.read_text(encoding="utf-8")
        scheduler = KERNEL_SCHEDULER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("IDT_USER_INTERRUPT_GATE 0xEEU", idt)
        self.assertIn("syscall_stub", idt)
        self.assertIn("enter_user_mode", user_mode)
        self.assertIn("iretd", user_mode)
        self.assertIn("int 0x80", user_mode)
        self.assertIn("user_fault_test_start", user_mode)
        self.assertIn("syscall_dispatch", syscall)
        self.assertIn("SYS_getpid", syscall)
        self.assertIn("SYS_write", syscall)
        self.assertIn("SYS_read", syscall)
        self.assertIn("SYS_open", syscall)
        self.assertIn("SYS_close", syscall)
        self.assertIn("SYS_lseek", syscall)
        self.assertIn("SYS_create", syscall)
        self.assertIn("SYS_unlink", syscall)
        self.assertIn("SYS_mkdir", syscall)
        self.assertIn("SYS_readdir", syscall)
        self.assertIn("SYS_stat", syscall)
        self.assertIn("SYS_yield", syscall)
        self.assertIn("SYS_exit", syscall)
        self.assertIn("SYS_waitpid", syscall)
        self.assertIn("SYS_spawn", syscall)
        self.assertIn("SYS_sleep", syscall)
        self.assertIn("SYS_chdir", syscall)
        self.assertIn("SYS_getcwd", syscall)
        self.assertIn("SYS_getticks", syscall)
        self.assertIn("SYS_ps", syscall)
        self.assertIn("vmm_address_space_activate", scheduler)
        self.assertIn("user_process_self_test", scheduler)
        self.assertIn("user_elf_self_test", scheduler)
        self.assertIn("vfs_open", scheduler)
        self.assertIn("vfs_read", scheduler)
        self.assertIn("page_fault_set_user_handler", scheduler)
        self.assertIn("user_page_fault_self_test", scheduler)

    def test_kernel_declares_ata_and_block_contract(self) -> None:
        self.assertTrue(KERNEL_ATA_SOURCE.is_file(), "缺少内核 ATA PIO 驱动")
        self.assertTrue(KERNEL_BLOCK_SOURCE.is_file(), "缺少 block device 层")
        ata = KERNEL_ATA_SOURCE.read_text(encoding="utf-8")
        block = (
            KERNEL_BLOCK_HEADER.read_text(encoding="utf-8")
            + KERNEL_BLOCK_SOURCE.read_text(encoding="utf-8")
        )
        for contract in (
            "ATA_DATA_PORT",
            "ATA_COMMAND_IDENTIFY",
            "ATA_COMMAND_READ_SECTORS",
            "ATA_COMMAND_WRITE_SECTORS",
            "ATA_COMMAND_CACHE_FLUSH",
            "ATA_STATUS_BUSY",
            "ATA_STATUS_DRQ",
            "ATA_STATUS_ERROR",
            "ATA_STATUS_DEVICE_FAULT",
            "ATA_POLL_LIMIT",
            "ata_read_sectors",
            "ata_write_sectors",
            "irq_save_disable",
        ):
            self.assertIn(contract, ata)
        for contract in (
            "BLOCK_SIZE 4096U",
            "SECTORS_PER_BLOCK 8U",
            "block_read",
            "block_write",
            "ata_read_sectors",
            "ata_write_sectors",
        ):
            self.assertIn(contract, block)

    def test_kernel_declares_minifs_io_contract(self) -> None:
        self.assertTrue(KERNEL_MINIFS_HEADER.is_file(), "缺少内核 MiniFS 接口")
        self.assertTrue(KERNEL_MINIFS_SOURCE.is_file(), "缺少内核 MiniFS 实现")
        self.assertTrue(MINIFS_LAYOUT_TOOL.is_file(), "缺少 MiniFS 布局头生成器")
        source = KERNEL_MINIFS_SOURCE.read_text(encoding="utf-8")
        generator = MINIFS_LAYOUT_TOOL.read_text(encoding="utf-8")
        for contract in (
            "MINIFS_VOLUME_START_BLOCK",
            "MINIFS_SUPERBLOCK_CHECKSUM_OFFSET",
            "MINIFS_CRC32_POLYNOMIAL",
            "read_le32",
            "block_read",
            "minifs_mount",
            "minifs_lookup",
            "minifs_read",
            "minifs_create",
            "minifs_write",
            "minifs_truncate",
            "minifs_mkdir",
            "minifs_unlink",
            "minifs_readdir",
            "allocate_block",
            "allocate_inode",
            "rollback",
            "irq_save_disable",
            "program_registry_lookup",
        ):
            self.assertIn(contract, source)
        self.assertIn("MINIFS_VOLUME_START_BLOCK", generator)
        self.assertIn("MINIFS_VOLUME_BLOCK_COUNT", generator)

    def test_kernel_declares_vfs_and_process_fd_contract(self) -> None:
        self.assertTrue(KERNEL_VFS_HEADER.is_file(), "缺少内核 VFS 接口")
        self.assertTrue(KERNEL_VFS_SOURCE.is_file(), "缺少内核 VFS 实现")
        source = KERNEL_VFS_SOURCE.read_text(encoding="utf-8")
        scheduler = KERNEL_SCHEDULER_SOURCE.read_text(encoding="utf-8")
        for contract in (
            "struct vfs_file",
            "refcount",
            "vfs_open",
            "vfs_read",
            "vfs_write",
            "vfs_lseek",
            "vfs_close",
            "vfs_stat",
            "vfs_mkdir",
            "vfs_unlink",
            "vfs_readdir",
            "vfs_close_all_current",
            "scheduler_fd_install",
            "scheduler_fd_get",
            "scheduler_fd_remove",
        ):
            self.assertIn(contract, source + scheduler)

    def test_entry_builds_independent_real_mode_stack_and_saves_dl(self) -> None:
        self.assertIn("stage2_entry", self.symbols)
        self.assertIn("stage2_boot_drive", self.symbols)
        instructions = self._symbol_instructions("stage2_entry")
        self.assertGreaterEqual(len(instructions), 6, "Stage 2 入口指令不完整")
        self.assertEqual(instructions[0], "cli", "入口必须先阻止栈切换期间的中断")

        ss_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if re.fullmatch(r"mov\s+ss,ax", instruction)
            ),
            None,
        )
        self.assertIsNotNone(ss_index, "入口必须显式初始化 SS")
        assert ss_index is not None
        self.assertTrue(
            any(
                re.fullmatch(r"(?:xor\s+ax,ax|mov\s+ax,0x0)", instruction)
                for instruction in instructions[:ss_index]
            ),
            "T11 实模式栈合同要求 SS=0",
        )
        sp_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if re.fullmatch(r"mov\s+sp,0x[0-9a-f]+", instruction)
            ),
            None,
        )
        self.assertIsNotNone(sp_index, "入口必须显式初始化 SP")
        assert sp_index is not None
        self.assertLess(ss_index, sp_index, "必须先设置 SS 再设置 SP")
        stack_top = int(instructions[sp_index].rsplit("0x", 1)[1], 16)
        self.assertGreaterEqual(stack_top, 0x0600, "实模式栈不得覆盖 IVT/BDA")
        self.assertLess(stack_top, 0x7C00, "Stage 2 必须使用独立于 Stage 1 的栈")

        drive_address = self.symbols["stage2_boot_drive"]
        drive_stores = [
            index
            for index, instruction in enumerate(instructions)
            if re.fullmatch(
                rf"mov\s+\[(?:cs:)?0x{drive_address:x}\],dl", instruction
            )
        ]
        self.assertLessEqual(len(drive_stores), 1, "入口只能保存一次 BIOS 启动盘号")
        self.assertTrue(drive_stores, "入口必须把 BIOS 传入的 DL 保存到公开变量")
        first_call = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if instruction.startswith(("call ", "int "))
            ),
            len(instructions),
        )
        self.assertLess(drive_stores[0], first_call, "必须在任何 BIOS/内部调用前保存 DL")

    def test_stage2_embeds_boot_progress_and_failure_messages(self) -> None:
        payload = self.stage2_binary.read_bytes()
        for message in (
            b"[S2] loader entered\x00",
            b"[S2] boot drive=0x\x00",
            b"[S2] A20 enabled\x00",
            b"[S2] A20 failure\x00",
            b"[S2] E820 entries=0x\x00",
            b"[S2] E820 failure\x00",
            b"[S2] protected mode entered\x00",
            b"[S2] ATA failure\x00",
            b"[S2] ELF failure\x00",
            b"[S2] kernel loaded entry=0x\x00",
        ):
            self.assertEqual(
                payload.count(message), 1, f"stage2.bin 必须唯一包含 {message!r}"
            )

    def test_public_bios_character_output_uses_int10_teletype(self) -> None:
        self.assertIn("bios_write_char", self.symbols, "缺少公开 BIOS 字符输出接口")
        instructions = self._symbol_instructions("bios_write_char")
        ah_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if re.fullmatch(r"mov\s+ah,0xe", instruction)
            ),
            None,
        )
        int_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if instruction == "int 0x10"
            ),
            None,
        )
        self.assertIsNotNone(ah_index, "bios_write_char 必须选择 INT 10h AH=0Eh")
        self.assertIsNotNone(int_index, "bios_write_char 必须调用 INT 10h")
        assert ah_index is not None and int_index is not None
        self.assertLess(ah_index, int_index)
        self.assertIn("ret", instructions[int_index + 1 :], "字符接口必须返回调用方")

    def test_public_edd_read_uses_saved_drive_and_exposes_cf_ah(self) -> None:
        self.assertIn("bios_disk_read_edd", self.symbols, "缺少公开 EDD 读盘接口")
        self.assertIn("stage2_boot_drive", self.symbols, "缺少公开启动盘保存变量")
        instructions = self._symbol_instructions("bios_disk_read_edd")
        drive_address = self.symbols["stage2_boot_drive"]
        load_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if re.fullmatch(
                    rf"mov\s+dl,\[(?:cs:)?0x{drive_address:x}\]", instruction
                )
            ),
            None,
        )
        ah_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if re.fullmatch(r"mov\s+ah,0x42", instruction)
            ),
            None,
        )
        int_index = next(
            (
                index
                for index, instruction in enumerate(instructions)
                if instruction == "int 0x13"
            ),
            None,
        )
        self.assertIsNotNone(load_index, "EDD 接口必须从保存变量恢复启动盘 DL")
        self.assertIsNotNone(ah_index, "EDD 接口必须选择 INT 13h AH=42h")
        self.assertIsNotNone(int_index, "EDD 接口必须调用 INT 13h")
        assert load_index is not None and ah_index is not None and int_index is not None
        self.assertLess(load_index, ah_index)
        self.assertLess(ah_index, int_index)
        return_path = instructions[int_index + 1 :]
        self.assertTrue(return_path and return_path[-1] == "ret", "EDD 接口必须返回调用方")
        self.assertTrue(
            all(
                re.fullmatch(r"pop\s+(?:es|ds|bp|di|si|dx|cx|bx)", instruction)
                for instruction in return_path[:-1]
            ),
            "INT 13h 后只能恢复不影响 flags/AH 的寄存器再返回",
        )

    def test_public_bios_interfaces_execute_in_qemu(self) -> None:
        fixture_image = self._build_bios_fixture_image()
        log = self.build_directory / "test-logs/stage2-bios-interfaces.log"
        result = subprocess.run(
            [
                sys.executable,
                "tools/qemu_test.py",
                "--qemu",
                QEMU,
                "--image",
                str(fixture_image),
                "--log",
                str(log),
                "--timeout",
                "5",
                "--max-log-bytes",
                "262144",
                "--repo",
                str(ROOT),
                "--build-dir",
                self.build_relative.as_posix(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        output = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        self.assertEqual(
            result.returncode,
            0,
            "Stage 2 正式 BIOS 接口动态夹具失败：\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\nserial:\n{output}",
        )
        self.assertIn("[TEST] case=bios_write_char PASS", output)
        self.assertIn("[TEST] case=bios_disk_read_edd PASS", output)

    def test_real_product_image_logs_s1_then_s2_and_times_out_safely(self) -> None:
        image = self.build_directory / "test-fixtures/stage2-product.img"
        log = self.build_directory / "test-logs/stage2-product.log"
        image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.image, image)
        result = subprocess.run(
            [
                sys.executable,
                "tools/qemu_test.py",
                "--qemu",
                QEMU,
                "--image",
                str(image),
                "--log",
                str(log),
                "--timeout",
                "30",
                "--max-log-bytes",
                "262144",
                "--repo",
                str(ROOT),
                "--build-dir",
                self.build_relative.as_posix(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, "P1 尚未定义最终测试 PASS/退出握手")
        self.assertIn("QEMU 超时", result.stderr, "正式 Loader 必须由安全 runner 超时清理")
        output = log.read_text(encoding="utf-8", errors="replace")
        boot_lines = re.findall(r"(?m)^\[(?:S1|S2)\][^\r\n]*", output)
        self.assertEqual(len(boot_lines), 8, f"启动阶段日志数量异常：\n{output}")
        self.assertEqual(
            boot_lines[:5],
            [
                "[S1] boot",
                "[S1] loader loaded",
                "[S2] loader entered",
                "[S2] boot drive=0x80",
                "[S2] A20 enabled",
            ],
            f"正式启动链未按 S1→S2 合同输出：\n{output}",
        )
        self.assertRegex(
            boot_lines[5],
            r"^\[S2\] E820 entries=0x[0-9A-F]{4}$",
            "E820 成功日志必须包含固定宽度的非零条目数",
        )
        self.assertNotEqual(boot_lines[5], "[S2] E820 entries=0x0000")
        self.assertEqual(boot_lines[6], "[S2] protected mode entered")
        self.assertRegex(
            boot_lines[7],
            r"^\[S2\] kernel loaded entry=0xC[0-9A-F]{7}$",
        )
        kernel_lines = re.findall(r"(?m)^\[KERN\][^\r\n]*", output)
        self.assertEqual(
            kernel_lines[:7],
            [
                "[KERN] boot info valid",
                "[KERN] paging enabled",
                "[KERN] bss cleared",
                "[KERN] console ready hex=c0ffee dec=42 str=ok",
                "[KERN] gdt ready",
                "[KERN] tss ready",
                "[KERN] idt ready",
            ],
        )
        self.assertRegex(
            kernel_lines[7],
            r"^\[KERN\] pmm pages total=[1-9][0-9]* free=[1-9][0-9]* reserved=[1-9][0-9]*$",
        )
        self.assertEqual(
            kernel_lines[8:10],
            [
                "[KERN] pmm self-test PASS",
                "[KERN] vmm ready identity=off wp=on",
            ],
        )
        self.assertEqual(
            kernel_lines[10:13],
            [
                "[KERN] vmm self-test PASS",
                "[KERN] heap ready",
                "[KERN] heap self-test PASS",
            ],
        )
        self.assertEqual(
            kernel_lines[13:17],
            [
                "[KERN] user memory ready",
                "[KERN] user memory self-test PASS",
                "[KERN] scheduler ready",
                "[KERN] scheduler self-test PASS",
            ],
        )
        self.assertRegex(
            kernel_lines[17],
            r"^\[KERN\] ata ready sectors=[1-9][0-9]*$",
        )
        self.assertRegex(
            kernel_lines[18],
            r"^\[KERN\] block ready blocks=[1-9][0-9]*$",
        )
        self.assertEqual(kernel_lines[19], "[KERN] block self-test PASS")
        self.assertRegex(
            kernel_lines[20],
            r"^\[KERN\] minifs mounted blocks=16128 inodes=1024$",
        )
        self.assertEqual(kernel_lines[21], "[KERN] minifs self-test PASS")
        self.assertEqual(
            kernel_lines[22:],
            [
                "[KERN] vfs ready",
                "[KERN] vfs self-test PASS",
                "[KERN] pic ready",
                "[KERN] pit ready hz=100",
                "[KERN] keyboard ready",
                "[KERN] interrupts enabled",
                "[KERN] pit tick=5",
                "[KERN] scheduler preemption PASS",
                "[KERN] process lifecycle self-test PASS",
                "[KERN] ring3 syscall self-test PASS",
                "[KERN] ELF user process self-test PASS",
                "[KERN] user fault isolation PASS",
            ],
        )
        self.assertIn("[USER] ring3 syscall PASS", output)
        self.assertIn("[USER] file syscall PASS", output)
        self.assertIn("[USER] directory syscall PASS", output)
        self.assertIn("[USER] cwd syscall PASS", output)
        self.assertIn("[USER] file commands PASS", output)
        self.assertIn("[USER] edit command PASS", output)
        self.assertTrue(
            "[USER] command persistence created PASS" in output or
            "[USER] command persistence verified PASS" in output
        )
        self.assertIn("[USER] elf init PASS", output)
        self.assertIn("[USER] echo child PASS", output)
        self.assertIn("[USER] shell command PASS", output)
        self.assertIn("[USER] quoted shell command PASS", output)
        self.assertIn("[USER] relative command PASS", output)
        self.assertIn("[USER] shell self-test PASS", output)
        self.assertIn("[USER] ps PASS", output)
        self.assertIn("[USER] time commands PASS", output)
        self.assertIn("[USER] memtest PASS", output)
        self.assertIn("[USER] fault isolation PASS", output)
        self.assertNotIn("[PANIC]", output)
        self.assertNotIn("[TEST]", output, "P1 正式镜像不得伪造测试 PASS")

    def test_corrupted_minifs_superblock_is_rejected_before_mount(self) -> None:
        layout = json.loads(
            (ROOT / "config/image-layout.json").read_text(encoding="utf-8")
        )
        component = next(
            item for item in layout["components"] if item["name"] == "minifs"
        )
        volume_offset = component["lba"] * layout["sector_size"]
        for name, corruption_offset in (("magic", 0), ("checksum", 100)):
            with self.subTest(name=name):
                image = self.build_directory / f"test-fixtures/minifs-{name}.img"
                image.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.image, image)
                with image.open("r+b") as stream:
                    stream.seek(volume_offset + corruption_offset)
                    original = stream.read(1)
                    self.assertEqual(1, len(original))
                    stream.seek(volume_offset + corruption_offset)
                    stream.write(bytes((original[0] ^ 0xFF,)))
                log = self.build_directory / f"test-logs/minifs-{name}.log"
                result = subprocess.run(
                    [
                        sys.executable,
                        "tools/qemu_test.py",
                        "--qemu",
                        QEMU,
                        "--image",
                        str(image),
                        "--log",
                        str(log),
                        "--timeout",
                        "2",
                        "--max-log-bytes",
                        "262144",
                        "--repo",
                        str(ROOT),
                        "--build-dir",
                        self.build_relative.as_posix(),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=12,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("QEMU 超时", result.stderr)
                output = log.read_text(encoding="utf-8", errors="replace")
                self.assertIn("[KERN] block self-test PASS", output)
                self.assertIn("[PANIC] MiniFS mount failed", output)
                self.assertNotIn("[KERN] minifs mounted", output)
                self.assertNotIn("[KERN] pic ready", output)

    def test_real_minifs_write_persists_across_reboot(self) -> None:
        test_build = Path(self.temporary_directory.name) / "minifs-write-build"
        test_build_relative = test_build.relative_to(ROOT)
        build = subprocess.run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={test_build_relative.as_posix()}",
                "KERNEL_TEST_MINIFS_WRITE=1",
                "-j4",
                "image",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

        image = test_build / "miniorangeos.img"
        expected_markers = (
            (
                "[KERN] minifs persistence created PASS",
                "[USER] command persistence created PASS",
            ),
            (
                "[KERN] minifs persistence verified and truncated PASS",
                "[USER] command persistence verified PASS",
            ),
        )
        for boot, expected in enumerate(expected_markers, start=1):
            log = test_build / f"test-logs/minifs-write-{boot}.log"
            result = subprocess.run(
                [
                    sys.executable,
                    "tools/qemu_test.py",
                    "--qemu",
                    QEMU,
                    "--image",
                    str(image),
                    "--log",
                    str(log),
                    "--timeout",
                    "15",
                    "--max-log-bytes",
                    "262144",
                    "--repo",
                    str(ROOT),
                    "--build-dir",
                    test_build_relative.as_posix(),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("QEMU 超时", result.stderr)
            output = log.read_text(encoding="utf-8", errors="replace")
            self.assertIn(expected[0], output)
            self.assertIn(expected[1], output)
            self.assertIn("[USER] directory syscall PASS", output)
            self.assertIn("[USER] file commands PASS", output)
            self.assertIn("[USER] edit command PASS", output)
            self.assertNotIn("[PANIC]", output)
            checked = subprocess.run(
                [
                    sys.executable,
                    "tools/fsck.py",
                    "--layout",
                    "config/image-layout.json",
                    "--image",
                    str(image),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            self.assertEqual(
                checked.returncode,
                0,
                checked.stdout + checked.stderr,
            )

    def test_real_qemu_keyboard_input_executes_shell_command(self) -> None:
        image = self.build_directory / "test-fixtures/keyboard-input.img"
        log = self.build_directory / "test-logs/keyboard-input.log"
        image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.image, image)
        log.parent.mkdir(parents=True, exist_ok=True)
        drive = f"file={image},format=raw,if=ide,index=0,media=disk"
        process = subprocess.Popen(
            [
                QEMU,
                "-machine",
                "pc,accel=tcg",
                "-m",
                "32M",
                "-drive",
                drive,
                "-boot",
                "c",
                "-display",
                "none",
                "-monitor",
                "stdio",
                "-serial",
                f"file:{log}",
                "-no-reboot",
                "-no-shutdown",
                "-device",
                "isa-debug-exit,iobase=0xf4,iosize=0x04",
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
                if "MiniOrangeOS shell\n/$ " in output:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"QEMU 未到达 Shell 提示符：\n{output}")

            assert process.stdin is not None

            def send_keys(*keys: bytes) -> None:
                for key in keys:
                    process.stdin.write(b"sendkey " + key + b"\n")
                    process.stdin.flush()
                    time.sleep(0.05)

            def send_text(value: str) -> None:
                key_names = {" ": b"spc", "-": b"minus", "=": b"equal", "/": b"slash"}
                send_keys(*(key_names.get(character, character.encode("ascii")) for character in value))

            send_text("help")
            send_keys(b"ret")
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace")
                if "builtins: help clear cd pwd exit shutdown" in output:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"键盘输入未执行 help 命令：\n{output}")

            send_text("echo backspacz")
            send_keys(b"backspace")
            send_text("e")
            send_keys(b"ret")

            send_text("echo leftrght")
            send_keys(b"left", b"left", b"left")
            send_text("i")
            send_keys(b"ret")

            send_text("echo deleqte")
            send_keys(b"left", b"left", b"left", b"delete", b"ret")

            send_text("cho homeend")
            send_keys(b"home")
            send_text("e")
            send_keys(b"end", b"ret")

            send_text("echo history")
            send_keys(b"ret", b"up", b"ret", b"up", b"down")
            send_text("echo down")
            send_keys(b"ret")

            send_text("echo cancel")
            send_keys(b"ctrl-c")
            send_text("echo control")
            send_keys(b"ret")

            send_text("echo a/b-c=d")
            send_keys(b"ret")

            expected_lines = {
                "backspace": 1,
                "leftright": 1,
                "delete": 1,
                "homeend": 1,
                "history": 2,
                "down": 1,
                "control": 1,
                "a/b-c=d": 1,
            }
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace")
                normalized_output = output.replace("\r\n", "\n").replace("\r", "\n")
                if all(
                    len(re.findall(rf"(?m)^{re.escape(line)}$", normalized_output)) >= count
                    for line, count in expected_lines.items()
                ):
                    break
                time.sleep(0.05)
            else:
                self.fail(f"特殊键位未完成行编辑验收：\n{output}")
            self.assertIsNone(re.search(r"(?m)^cancel$", normalized_output))
            self.assertNotIn(
                "[KERN] keyboard input=",
                output,
                "键盘 IRQ 不得把每次按键作为内核日志写入终端",
            )
            send_text("shutdown")
            send_keys(b"ret")
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.fail("shutdown 命令未主动退出 QEMU")
            self.assertEqual(85, returncode, "shutdown 未使用约定的 debug-exit 状态")
            output = log.read_text(encoding="utf-8", errors="replace")
            self.assertIn("Shutting down MiniOrangeOS...", output)
            self.assertIn("[KERN] shutdown requested", output)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            if process.stdin is not None:
                process.stdin.close()
            if process.stderr is not None:
                process.stderr.close()

    def test_real_breakpoint_exception_reaches_panic(self) -> None:
        test_build = Path(self.temporary_directory.name) / "breakpoint-build"
        test_build_relative = test_build.relative_to(ROOT)
        build = subprocess.run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={test_build_relative.as_posix()}",
                "KERNEL_TEST_BREAKPOINT=1",
                "-j4",
                "image",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

        log = test_build / "test-logs/breakpoint.log"
        result = subprocess.run(
            [
                sys.executable,
                "tools/qemu_test.py",
                "--qemu",
                QEMU,
                "--image",
                str(test_build / "miniorangeos.img"),
                "--log",
                str(log),
                "--timeout",
                "2",
                "--max-log-bytes",
                "262144",
                "--repo",
                str(ROOT),
                "--build-dir",
                test_build_relative.as_posix(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("QEMU 超时", result.stderr)
        output = log.read_text(encoding="utf-8", errors="replace")
        self.assertIn("[KERN] idt ready", output)
        self.assertRegex(
            output,
            r"(?m)^\[PANIC\] exception vector=3 error=0 eip=0x[0-9a-f]{8}\r?$",
        )

    def test_real_kernel_page_fault_reports_cr2_and_context(self) -> None:
        test_build = Path(self.temporary_directory.name) / "page-fault-build"
        test_build_relative = test_build.relative_to(ROOT)
        build = subprocess.run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={test_build_relative.as_posix()}",
                "KERNEL_TEST_PAGE_FAULT=1",
                "-j4",
                "image",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

        log = test_build / "test-logs/page-fault.log"
        result = subprocess.run(
            [
                sys.executable,
                "tools/qemu_test.py",
                "--qemu",
                QEMU,
                "--image",
                str(test_build / "miniorangeos.img"),
                "--log",
                str(log),
                "--timeout",
                "2",
                "--max-log-bytes",
                "262144",
                "--repo",
                str(ROOT),
                "--build-dir",
                test_build_relative.as_posix(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("QEMU 超时", result.stderr)
        output = log.read_text(encoding="utf-8", errors="replace")
        self.assertIn("[KERN] idt ready", output)
        self.assertRegex(
            output,
            r"(?m)^\[PANIC\] kernel page fault address=0x00400000 "
            r"error=0 eip=0x[0-9a-f]{8}\r?$",
        )

    def test_fault_build_toggles_fail_closed(self) -> None:
        build_relative = (
            Path(self.temporary_directory.name).relative_to(ROOT) / "invalid"
        )
        marker = Path(self.temporary_directory.name) / "must-not-exist"
        for variable in (
            "KERNEL_TEST_BREAKPOINT",
            "KERNEL_TEST_PAGE_FAULT",
            "KERNEL_TEST_MINIFS_WRITE",
        ):
            for value in ("2", f"$(shell touch {marker.as_posix()})"):
                with self.subTest(variable=variable, value=value):
                    result = subprocess.run(
                        [
                            "bash",
                            "environment/with-env.sh",
                            "make",
                            f"BUILD_DIR={build_relative.as_posix()}",
                            f"{variable}={value}",
                            "image",
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=15,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(marker.exists(), "非法测试开关不得执行 Make 函数")

    def test_corrupted_kernel_elf_is_rejected_before_entry(self) -> None:
        layout = json.loads((ROOT / "config/image-layout.json").read_text(encoding="utf-8"))
        kernel = next(
            component
            for component in layout["components"]
            if component["name"] == "kernel"
        )
        kernel_payload = self.kernel_elf.read_bytes()
        program_offset = struct.unpack_from("<I", kernel_payload, 28)[0]
        memory_size = struct.unpack_from("<I", kernel_payload, program_offset + 20)[0]
        corruptions = {
            "bad-magic": ((0, b"BAD!"),),
            "filesz-over-memsz": (
                (program_offset + 16, struct.pack("<I", memory_size + 1)),
            ),
            "segment-over-loader": (
                (program_offset + 8, struct.pack("<I", 0xC0008000)),
                (program_offset + 12, struct.pack("<I", 0x00008000)),
            ),
            "load-segments-overlap": (
                (program_offset + 32 + 8, struct.pack("<I", 0xC0100800)),
                (program_offset + 32 + 12, struct.pack("<I", 0x00100800)),
                (program_offset + 32 + 20, struct.pack("<I", 0x00000100)),
                (program_offset + 32 + 28, struct.pack("<I", 1)),
            ),
        }
        for name, writes in corruptions.items():
            with self.subTest(name=name):
                corrupted = (
                    self.build_directory / f"test-fixtures/kernel-{name}.img"
                )
                corrupted.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.image, corrupted)
                with corrupted.open("r+b") as image_file:
                    for offset, payload in writes:
                        image_file.seek(int(kernel["lba"]) * 512 + offset)
                        image_file.write(payload)

                log = self.build_directory / f"test-logs/kernel-{name}.log"
                result = subprocess.run(
                    [
                        sys.executable,
                        "tools/qemu_test.py",
                        "--qemu",
                        QEMU,
                        "--image",
                        str(corrupted),
                        "--log",
                        str(log),
                        "--timeout",
                        "2",
                        "--max-log-bytes",
                        "262144",
                        "--repo",
                        str(ROOT),
                        "--build-dir",
                        self.build_relative.as_posix(),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=12,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("QEMU 超时", result.stderr)
                output = log.read_text(encoding="utf-8", errors="replace")
                self.assertIn("[S2] ELF failure", output)
                self.assertNotIn("[KERN]", output)


if __name__ == "__main__":
    unittest.main()
