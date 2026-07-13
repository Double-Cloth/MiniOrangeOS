"""在 Linux/WSL 中验证 T10 BIOS Stage 1 启动扇区。"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE1_SOURCE = ROOT / "boot/stage1/boot.asm"
LAYOUT_PATH = ROOT / "config/image-layout.json"


def _is_supported_linux() -> bool:
    return platform.system() == "Linux"


@unittest.skipUnless(_is_supported_linux(), "T10 构建与真实 QEMU 验证只在 Linux 环境执行")
class BootStage1Tests(unittest.TestCase):
    temporary_directory: tempfile.TemporaryDirectory[str]
    build_relative: Path
    build_directory: Path
    stage1_binary: Path
    image: Path
    stage2_layout: dict[str, object]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix=".t10-host-", dir=ROOT
        )
        temporary_root = Path(cls.temporary_directory.name)
        cls.build_directory = temporary_root / "build"
        cls.build_relative = cls.build_directory.relative_to(ROOT)

        layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        cls.stage2_layout = next(
            component
            for component in layout["components"]
            if component["name"] == "stage2"
        )

        result = cls._run_make("-j4", "image", timeout=90)
        if result.returncode != 0:
            raise AssertionError(
                "T10 测试镜像构建失败：\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        cls.stage1_binary = cls.build_directory / "boot/stage1.bin"
        cls.image = cls.build_directory / "miniorangeos.img"

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

    def test_stage1_binary_is_exact_boot_sector(self) -> None:
        payload = self.stage1_binary.read_bytes()
        self.assertEqual(len(payload), 512, "stage1.bin 必须严格为 512 字节")
        self.assertEqual(payload[-2:], b"\x55\xaa", "启动签名必须是 0x55 0xAA")

    def test_stage1_dap_uses_generated_layout(self) -> None:
        source = STAGE1_SOURCE.read_text(encoding="utf-8")
        include_matches = re.findall(
            r"(?im)^\s*%include\s+[\"']([^\"']*image[-_]layout[^\"']*\.inc)[\"']",
            source,
        )
        self.assertEqual(
            len(include_matches),
            1,
            "Stage 1 必须包含唯一的、由 config/image-layout.json 生成的 NASM 布局文件",
        )

        generated = sorted(self.build_directory.rglob("*image*layout*.inc"))
        self.assertEqual(len(generated), 1, "构建必须生成唯一的 image-layout NASM include")
        generated_text = generated[0].read_text(encoding="utf-8")
        expected_lba = int(self.stage2_layout["lba"])
        definitions = re.findall(
            r"(?im)^\s*%define\s+(\w+)\s+([^;\s]+)", generated_text
        )

        def matching_definitions(keywords: tuple[str, ...], expected: int) -> list[str]:
            matches: list[str] = []
            for name, value in definitions:
                if not all(keyword in name.upper() for keyword in keywords):
                    continue
                try:
                    generated_value = int(value, 0)
                except ValueError:
                    continue
                if generated_value == expected:
                    matches.append(name)
            return matches

        lba_symbols = matching_definitions(("STAGE2", "LBA"), expected_lba)
        max_sectors = int(self.stage2_layout["max_sectors"])
        max_symbols = matching_definitions(
            ("STAGE2", "MAX", "SECTORS"), max_sectors
        )
        self.assertTrue(
            lba_symbols,
            "生成的 NASM include 必须从配置导出 Stage 2 LBA",
        )
        self.assertTrue(
            max_symbols,
            "生成的 NASM include 必须从配置导出 Stage 2 max_sectors",
        )
        for description, symbols in (
            ("Stage 2 LBA", lba_symbols),
            ("Stage 2 max_sectors", max_symbols),
        ):
            self.assertTrue(
                any(
                    re.search(rf"\b{re.escape(symbol)}\b", source)
                    for symbol in symbols
                ),
                f"Stage 1 的 DAP 必须引用生成的 {description} 符号",
            )

        self.assertGreater(max_sectors, 64, "T10 双 DAP 合同要求 Stage 2 区域超过 64 扇区")
        payload = self.stage1_binary.read_bytes()
        dap_candidates: list[tuple[int, int, int, int]] = []
        for offset in range(0, len(payload) - 15):
            if payload[offset : offset + 2] != b"\x10\x00":
                continue
            sector_count, target_offset, target_segment = struct.unpack_from(
                "<HHH", payload, offset + 2
            )
            lba = struct.unpack_from("<Q", payload, offset + 8)[0]
            physical = target_segment * 16 + target_offset
            if (
                1 <= sector_count <= max_sectors
                and expected_lba <= lba < expected_lba + max_sectors
                and 0x8000 <= physical < 0x8000 + max_sectors * 512
            ):
                self.assertLessEqual(
                    (physical & 0xFFFF) + sector_count * 512,
                    0x10000,
                    "单个 INT 13h 请求不得跨物理 64 KiB DMA 边界",
                )
                dap_candidates.append((lba, sector_count, physical, offset))

        actual_requests = sorted(
            (lba, sector_count, physical)
            for lba, sector_count, physical, _ in dap_candidates
        )
        expected_requests = [
            (expected_lba, 64, 0x8000),
            (expected_lba + 64, max_sectors - 64, 0x10000),
        ]
        self.assertEqual(
            actual_requests,
            expected_requests,
            "必须用两个唯一 DAP 连续覆盖 Stage 2：64 扇区到 0x8000，其余扇区到 0x10000",
        )
        self.assertEqual(
            sum(request[1] for request in actual_requests),
            max_sectors,
            "两个 DAP 必须正好覆盖配置中的 Stage 2 max_sectors",
        )

    def test_stage1_initializes_real_mode_and_checks_disk_status(self) -> None:
        result = subprocess.run(
            ["ndisasm", "-b", "16", str(self.stage1_binary)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        assembly = result.stdout.lower()

        required_patterns = {
            "关闭中断": r"\bcli\b",
            "清零段寄存器基值": r"\b(?:xor\s+ax,ax|mov\s+ax,0x0)\b",
            "初始化 DS": r"\bmov\s+ds,ax\b",
            "初始化 ES": r"\bmov\s+es,ax\b",
            "初始化 SS": r"\bmov\s+ss,ax\b",
            "初始化实模式栈": r"\bmov\s+sp,0x7c00\b",
            "清方向标志": r"\bcld\b",
            "保存 BIOS 启动盘 DL": r"\bmov\s+\[[^\]]+\],dl\b",
            "失败停机": r"\bhlt\b",
            "远跳 Stage 2": r"\bjmp\s+0x0:0x8000\b",
        }
        missing = [
            description
            for description, pattern in required_patterns.items()
            if re.search(pattern, assembly) is None
        ]
        self.assertEqual(missing, [], f"Stage 1 反汇编缺少：{', '.join(missing)}")

        instructions: list[tuple[int, str]] = []
        for line in assembly.splitlines():
            fields = line.split(None, 2)
            if len(fields) != 3:
                continue
            try:
                address = int(fields[0], 16)
            except ValueError:
                continue
            instructions.append((address, fields[2]))

        extension_reads = [
            index
            for index, (_, instruction) in enumerate(instructions)
            if re.fullmatch(r"mov\s+ah,0x42", instruction)
        ]
        all_disk_calls = [
            index
            for index, (_, instruction) in enumerate(instructions)
            if re.fullmatch(r"int\s+0x13", instruction)
        ]
        ah_setters = [
            index
            for index, (_, instruction) in enumerate(instructions)
            if re.fullmatch(r"mov\s+(?:ah|ax),0x[0-9a-f]+", instruction)
        ]
        disk_calls: list[int] = []
        for call_index in all_disk_calls:
            preceding_setters = [index for index in ah_setters if index < call_index]
            if not preceding_setters:
                continue
            last_setter = preceding_setters[-1]
            if last_setter in extension_reads:
                disk_calls.append(call_index)

        self.assertEqual(len(extension_reads), 2, "必须设置两次 AH=0x42")
        self.assertGreaterEqual(
            len(all_disk_calls),
            3,
            "必须至少执行一次 INT 13h extensions 探测和两次扩展读取",
        )
        self.assertEqual(
            len(disk_calls),
            2,
            "最近一次 AH 设置为 0x42 的 INT 13h 扩展读取必须恰好执行两次",
        )

        failure_targets: list[int] = []
        previous_call = -1
        for call_index in disk_calls:
            self.assertTrue(
                any(previous_call < index < call_index for index in extension_reads),
                "每次 INT 13h 前必须独立设置 AH=0x42",
            )
            following = [
                instruction
                for _, instruction in instructions[call_index + 1 : call_index + 6]
            ]
            self.assertGreaterEqual(len(following), 3, "INT 13h 后缺少完整状态检查")
            carry = re.fullmatch(r"jc(?:\s+short)?\s+(0x[0-9a-f]+)", following[0])
            self.assertIsNotNone(carry, "每次 INT 13h 后必须立即检查 CF")
            ah_index = next(
                (
                    index
                    for index, instruction in enumerate(following[1:], start=1)
                    if re.fullmatch(
                        r"(?:test\s+ah,ah|cmp\s+ah,(?:byte\s+\+)?0x0)",
                        instruction,
                    )
                ),
                None,
            )
            self.assertIsNotNone(ah_index, "每次 INT 13h 后必须检查 AH 返回状态")
            assert ah_index is not None and carry is not None
            status_jump = re.fullmatch(
                r"j(?:ne|nz)(?:\s+short)?\s+(0x[0-9a-f]+)", following[ah_index + 1]
            )
            self.assertIsNotNone(status_jump, "非零 AH 必须跳入失败路径")
            assert status_jump is not None
            carry_target = int(carry.group(1), 16)
            status_target = int(status_jump.group(1), 16)
            self.assertEqual(carry_target, status_target, "CF 与非零 AH 必须汇入同一失败路径")
            failure_targets.append(carry_target)
            previous_call = call_index

        self.assertEqual(
            len(set(failure_targets)),
            1,
            "两次磁盘读取失败必须汇入同一错误路径",
        )
        failure_target = failure_targets[0]
        failure_index = next(
            (
                index
                for index, (address, _) in enumerate(instructions)
                if address == failure_target
            ),
            None,
        )
        self.assertIsNotNone(failure_index, "失败分支目标必须位于启动扇区代码中")
        assert failure_index is not None
        failure_path = [
            instruction
            for _, instruction in instructions[failure_index : failure_index + 32]
        ]
        failure_text = "\n".join(failure_path)
        self.assertRegex(
            failure_text,
            r"(?s).*\bcli\b.*\bhlt\b.*\bjmp\b",
            "错误路径可先输出错误信息，但最终必须关中断并永久停机",
        )

    def test_real_qemu_serial_messages_are_exact_and_ordered(self) -> None:
        qemu = shutil.which("qemu-system-i386")
        self.assertIsNotNone(qemu, "专用 Linux/WSL 环境必须提供 qemu-system-i386")
        assert qemu is not None

        process = subprocess.Popen(
            [
                qemu,
                "-machine",
                "pc,accel=tcg",
                "-m",
                "16M",
                "-drive",
                f"file={self.image},format=raw,if=ide",
                "-boot",
                "c",
                "-snapshot",
                "-display",
                "none",
                "-serial",
                "stdio",
                "-monitor",
                "none",
                "-no-reboot",
                "-no-shutdown",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        output = b""
        try:
            try:
                output, _ = process.communicate(timeout=3)
            except subprocess.TimeoutExpired as error:
                output = error.output or b""
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            tail, _ = process.communicate(timeout=5)
            if tail and not output.endswith(tail):
                output += tail

        with self.assertRaises(ProcessLookupError, msg="本次 QEMU 进程必须已被回收"):
            os.kill(process.pid, 0)

        decoded = output.decode("utf-8", errors="replace")
        stage1_lines = re.findall(r"(?m)^\[S1\][^\r\n]*", decoded)
        self.assertEqual(
            stage1_lines,
            ["[S1] boot", "[S1] loader loaded"],
            f"Stage 1 串口日志必须精确且有序；QEMU 输出：\n{decoded}",
        )


if __name__ == "__main__":
    unittest.main()
