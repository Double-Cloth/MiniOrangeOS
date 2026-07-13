"""在 Linux/WSL 中验证 T10 BIOS Stage 1 启动扇区。"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE1_SOURCE = ROOT / "boot/stage1/boot.asm"
LAYOUT_PATH = ROOT / "config/image-layout.json"
HANDOFF_FIXTURE_SOURCE = ROOT / "tests/fixtures/boot/stage2_handoff.asm"


def _is_supported_linux() -> bool:
    return platform.system() == "Linux"


@unittest.skipUnless(_is_supported_linux(), "T10 构建与真实 QEMU 验证只在 Linux 环境执行")
class BootStage1Tests(unittest.TestCase):
    temporary_directory: tempfile.TemporaryDirectory[str]
    build_relative: Path
    build_directory: Path
    stage1_binary: Path
    image: Path
    handoff_fixture: Path
    handoff_image: Path
    floppy_image: Path
    stage2_layout: dict[str, object]
    layout_document: dict[str, object]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix=".t10-host-", dir=ROOT
        )
        temporary_root = Path(cls.temporary_directory.name)
        cls.build_directory = temporary_root / "build"
        cls.build_relative = cls.build_directory.relative_to(ROOT)

        layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        cls.layout_document = layout
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
        cls.handoff_fixture = cls.build_directory / "test-fixtures/stage2-handoff.bin"
        cls.handoff_fixture.parent.mkdir(parents=True, exist_ok=True)
        assembled = subprocess.run(
            [
                "nasm",
                "-f",
                "bin",
                "-o",
                str(cls.handoff_fixture),
                str(HANDOFF_FIXTURE_SOURCE),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if assembled.returncode != 0:
            raise AssertionError(assembled.stdout + assembled.stderr)

        cls.handoff_image = cls.build_directory / "test-fixtures/stage1-handoff.img"
        shutil.copyfile(cls.image, cls.handoff_image)
        fixture = cls.handoff_fixture.read_bytes()
        stage2_size = int(cls.stage2_layout["max_sectors"]) * 512
        if len(fixture) > stage2_size:
            raise AssertionError("Stage 2 handoff fixture 越过配置保留区域")
        with cls.handoff_image.open("r+b") as stream:
            stream.seek(int(cls.stage2_layout["lba"]) * 512)
            stream.write(fixture)
            stream.write(b"\x00" * (stage2_size - len(fixture)))

        cls.floppy_image = cls.build_directory / "test-fixtures/stage1-only.img"
        cls.floppy_image.write_bytes(cls.stage1_binary.read_bytes())

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

    @classmethod
    def _run_qemu_test(
        cls,
        image: Path,
        log: Path,
        *,
        timeout: int,
        drive_interface: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            sys.executable,
            "tools/qemu_test.py",
            "--image",
            str(image),
            "--log",
            str(log),
            "--timeout",
            str(timeout),
            "--max-log-bytes",
            "262144",
            "--repo",
            str(ROOT),
            "--build-dir",
            cls.build_relative.as_posix(),
        ]
        if drive_interface is not None:
            arguments.extend(("--drive-interface", drive_interface))
        return subprocess.run(
            arguments,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 10,
            check=False,
        )

    def _prepare_generator_workspace(self, parent: Path) -> Path:
        workspace = parent / "workspace"
        shutil.copytree(
            ROOT,
            workspace,
            ignore=shutil.ignore_patterns(
                ".git",
                ".superpowers",
                "build",
                ".t10-host-*",
                "__pycache__",
                ".pytest_cache",
            ),
        )
        prepared = subprocess.run(
            ["bash", "environment/with-env.sh", "make", "BUILD_DIR=build", "prepare-build-dir"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        (workspace / "build/boot").mkdir(parents=True, exist_ok=True)
        return workspace

    def _run_generator(
        self, workspace: Path, *, timeout: float = 2
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [
                    sys.executable,
                    "tools/generate_boot_layout.py",
                    "--repo",
                    str(workspace),
                    "--build-dir",
                    "build",
                    "--layout",
                    "config/image-layout.json",
                    "--output",
                    "build/boot/image-layout.inc",
                ],
                cwd=workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            self.fail(f"布局生成器阻塞且未及时拒绝特殊文件：{error}")

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

        self.assertTrue(dap_candidates, "未找到 Stage 2 DAP")
        self.assertTrue(
            all(offset % 4 == 0 for _, _, _, offset in dap_candidates),
            "两个 DAP 在 stage1.bin 中都必须按 4 字节对齐",
        )

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

        self.assertGreaterEqual(len(instructions), 2, "启动扇区缺少入口指令")
        self.assertEqual(instructions[0], (0, "cli"), "入口首条有效指令必须是 CLI")
        self.assertRegex(
            instructions[1][1],
            r"^jmp\s+0x0:0x[0-9a-f]+$",
            "CLI 后必须用远跳规范化 CS",
        )

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

        probe_setters = [
            index
            for index, (_, instruction) in enumerate(instructions)
            if re.fullmatch(r"mov\s+ah,0x41", instruction)
        ]
        probe_calls: list[int] = []
        for call_index in all_disk_calls:
            preceding_setters = [index for index in ah_setters if index < call_index]
            if preceding_setters and preceding_setters[-1] in probe_setters:
                probe_calls.append(call_index)
        self.assertEqual(len(probe_setters), 1, "必须恰好设置一次 AH=0x41")
        self.assertEqual(len(probe_calls), 1, "必须恰好执行一次 INT 13h extensions 探测")
        probe_call = probe_calls[0]
        probe_prefix = [
            instruction
            for _, instruction in instructions[max(0, probe_call - 6) : probe_call]
        ]
        self.assertTrue(
            any(re.fullmatch(r"mov\s+bx,0x55aa", item) for item in probe_prefix),
            "AH=0x41 探测前必须输入 BX=0x55AA",
        )
        probe_following = [
            instruction for _, instruction in instructions[probe_call + 1 : probe_call + 8]
        ]
        self.assertGreaterEqual(len(probe_following), 5, "AH=0x41 探测缺少完整返回检查")
        probe_patterns = (
            r"jc(?:\s+short)?\s+(0x[0-9a-f]+)",
            r"cmp\s+bx,0xaa55",
            r"j(?:ne|nz)(?:\s+short)?\s+(0x[0-9a-f]+)",
            r"test\s+cx,(?:byte\s+\+)?0x1",
            r"jz(?:\s+short)?\s+(0x[0-9a-f]+)",
        )
        probe_matches = [
            re.fullmatch(pattern, instruction)
            for pattern, instruction in zip(probe_patterns, probe_following)
        ]
        self.assertTrue(
            all(match is not None for match in probe_matches),
            "AH=0x41 返回后必须依次检查 CF、BX=0xAA55 与 CX bit 0",
        )
        probe_targets = [
            int(match.group(1), 16)
            for match in (probe_matches[0], probe_matches[2], probe_matches[4])
            if match is not None
        ]
        self.assertEqual(
            len(set(probe_targets)),
            1,
            "AH=0x41 的 CF/BX/CX 失败必须汇入同一错误路径",
        )
        failure_targets.extend(probe_targets)

        self.assertEqual(
            len(set(failure_targets)),
            1,
            "EDD 探测和两次磁盘读取失败必须汇入同一错误路径",
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

    def test_real_qemu_handoff_registers_and_protocol(self) -> None:
        log = self.build_directory / "test-logs/stage1-handoff.log"
        result = self._run_qemu_test(self.handoff_image, log, timeout=5)
        self.assertEqual(
            result.returncode,
            0,
            f"Stage 1 真实交接失败：\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        output = log.read_text(encoding="utf-8", errors="replace")
        stage1_lines = re.findall(r"(?m)^\[S1\][^\r\n]*", output)
        self.assertEqual(stage1_lines, ["[S1] boot", "[S1] loader loaded"])
        protocol_lines = re.findall(r"(?m)^\[TEST\][^\r\n]*", output)
        self.assertEqual(
            protocol_lines,
            [
                "[TEST] suite=stage1_handoff begin",
                "[TEST] case=registers PASS",
                "[TEST] suite=stage1_handoff PASS",
                "[TEST] all PASS",
            ],
            f"Stage 2 fixture 未证明完整寄存器交接：\n{output}",
        )

    def test_real_qemu_floppy_read_failure_is_logged_and_cleaned(self) -> None:
        log = self.build_directory / "test-logs/stage1-floppy-failure.log"
        result = self._run_qemu_test(
            self.floppy_image,
            log,
            timeout=2,
            drive_interface="floppy",
        )
        self.assertNotEqual(result.returncode, 0, "缺少 Stage 2 时不得报告测试成功")
        self.assertIn("QEMU 超时", result.stderr, "负测必须真实启动并由 runner 超时清理")
        output = log.read_text(encoding="utf-8", errors="replace")
        stage1_lines = re.findall(r"(?m)^\[S1\][^\r\n]*", output)
        self.assertEqual(
            stage1_lines,
            ["[S1] boot", "[S1] disk error"],
            f"软盘失败路径日志错误：\n{output}",
        )
        self.assertNotIn("[S1] loader loaded", output)

    def test_layout_generator_rejects_malformed_input_without_clobber(self) -> None:
        valid = json.dumps(self.layout_document, separators=(",", ":"))
        duplicate = valid.replace(
            '"format_version":1',
            '"format_version":1,"format_version":1',
            1,
        )
        nan_value = valid.replace(
            f'"image_size_bytes":{self.layout_document["image_size_bytes"]}',
            '"image_size_bytes":NaN',
            1,
        )
        cases = {
            "duplicate-key": duplicate.encode("utf-8"),
            "nan": nan_value.encode("utf-8"),
            "oversized": valid.encode("utf-8") + b" " * (2 * 1024 * 1024),
        }
        with tempfile.TemporaryDirectory(prefix="generator-invalid-") as directory:
            workspace = self._prepare_generator_workspace(Path(directory))
            layout = workspace / "config/image-layout.json"
            output = workspace / "build/boot/image-layout.inc"
            for name, payload in cases.items():
                with self.subTest(name=name):
                    layout.write_bytes(payload)
                    output.write_bytes(b"old-output\n")
                    result = self._run_generator(workspace)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output.read_bytes(), b"old-output\n")

    def test_layout_generator_rejects_special_input_files_without_clobber(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generator-input-") as directory:
            workspace = self._prepare_generator_workspace(Path(directory))
            layout = workspace / "config/image-layout.json"
            output = workspace / "build/boot/image-layout.inc"
            valid_payload = json.dumps(self.layout_document).encode("utf-8")
            backing = workspace / "config/layout-backing.json"
            backing.write_bytes(valid_payload)
            for name in ("symlink", "hardlink", "fifo"):
                with self.subTest(name=name):
                    layout.unlink(missing_ok=True)
                    if name == "symlink":
                        layout.symlink_to(backing)
                    elif name == "hardlink":
                        os.link(backing, layout)
                    else:
                        os.mkfifo(layout)
                    output.write_bytes(b"old-output\n")
                    result = self._run_generator(workspace, timeout=1)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output.read_bytes(), b"old-output\n")

    def test_layout_generator_rejects_special_output_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generator-output-") as directory:
            workspace = self._prepare_generator_workspace(Path(directory))
            output = workspace / "build/boot/image-layout.inc"
            peer = workspace / "build/boot/output-peer.inc"
            peer.write_bytes(b"old-output\n")
            for name in ("symlink", "fifo", "hardlink"):
                with self.subTest(name=name):
                    output.unlink(missing_ok=True)
                    if name == "symlink":
                        output.symlink_to(peer)
                    elif name == "fifo":
                        os.mkfifo(output)
                    else:
                        os.link(peer, output)
                    before = os.lstat(output)
                    result = self._run_generator(workspace)
                    after = os.lstat(output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
                    self.assertEqual(peer.read_bytes(), b"old-output\n")

    def test_layout_make_dependency_rebuilds_only_after_config_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minios-t10-rebuild-") as directory:
            workspace = Path(directory) / "workspace"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".superpowers",
                    "build",
                    ".t10-host-*",
                    "__pycache__",
                    ".pytest_cache",
                ),
            )
            target = workspace / "build/boot/image-layout.inc"

            def run_make() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        "bash",
                        "environment/with-env.sh",
                        "make",
                        "BUILD_DIR=build",
                        str(target),
                    ],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )

            first = run_make()
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_status = target.stat()
            first_payload = target.read_bytes()
            second = run_make()
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(target.stat().st_mtime_ns, first_status.st_mtime_ns)
            self.assertEqual(target.read_bytes(), first_payload)
            self.assertNotIn("tools/generate_boot_layout.py", second.stdout)

            config_path = workspace / "config/image-layout.json"
            changed = json.loads(config_path.read_text(encoding="utf-8"))
            stage2 = next(item for item in changed["components"] if item["name"] == "stage2")
            stage2["max_sectors"] = int(stage2["max_sectors"]) - 1
            time.sleep(0.02)
            config_path.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8")
            third = run_make()
            self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
            self.assertGreater(target.stat().st_mtime_ns, first_status.st_mtime_ns)
            self.assertNotEqual(target.read_bytes(), first_payload)
            self.assertIn("tools/generate_boot_layout.py", third.stdout)


if __name__ == "__main__":
    unittest.main()
