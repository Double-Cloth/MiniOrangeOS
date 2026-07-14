"""在 Linux/WSL 中验证 Stage 2 实模式接口与 P1 模式切换。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE2_SOURCE = ROOT / "boot/stage2/entry.asm"
BIOS_FIXTURE_SOURCE = ROOT / "tests/fixtures/boot/stage2_bios_interfaces.asm"


def _is_supported_linux() -> bool:
    return sys.platform.startswith("linux")


@unittest.skipUnless(_is_supported_linux(), "Stage 2 构建与真实 QEMU 验证只在 Linux 环境执行")
class BootStage2Tests(unittest.TestCase):
    temporary_directory: tempfile.TemporaryDirectory[str]
    build_relative: Path
    build_directory: Path
    stage2_binary: Path
    stage2_elf: Path
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
            ("nasm", "-f", "elf32", "-o", str(stage2_object), str(STAGE2_SOURCE)),
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
        log = self.build_directory / "test-logs/stage2-product.log"
        result = subprocess.run(
            [
                sys.executable,
                "tools/qemu_test.py",
                "--image",
                str(self.image),
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
        self.assertNotEqual(result.returncode, 0, "P1 尚未定义最终测试 PASS/退出握手")
        self.assertIn("QEMU 超时", result.stderr, "正式 Loader 必须由安全 runner 超时清理")
        output = log.read_text(encoding="utf-8", errors="replace")
        boot_lines = re.findall(r"(?m)^\[(?:S1|S2)\][^\r\n]*", output)
        self.assertEqual(len(boot_lines), 7, f"启动阶段日志数量异常：\n{output}")
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
        self.assertNotIn("[TEST]", output, "P1 正式镜像不得伪造测试 PASS")
        self.assertNotIn("kernel loaded", output.lower(), "内核加载未完成前不得提前宣称成功")


if __name__ == "__main__":
    unittest.main()
