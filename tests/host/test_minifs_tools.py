"""验证 MiniFS 磁盘 ABI、mkfs、镜像装配和只读 fsck。"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BLOCK_SIZE = 4096
SUPERBLOCK = struct.Struct("<14I")
INODE = struct.Struct("<HHI10I4I")
DIRECTORY_ENTRY = struct.Struct("<IB59s")
MAGIC = 0x3153464D
VERSION = 1
INODE_SIZE = 64
MODE_REGULAR = 1
MODE_DIRECTORY = 2
CHECKSUM_OFFSET = 52
PROGRAMS = ("init", "echo", "sh", "ps", "memtest", "fault")


@unittest.skipUnless(sys.platform.startswith("linux"), "MiniFS 宿主工具只在 Linux/WSL 验证")
class MiniFsToolTests(unittest.TestCase):
    temporary_directory: tempfile.TemporaryDirectory[str]
    build_directory: Path
    volume: Path
    image: Path
    layout: dict[str, object]
    fields: tuple[int, ...]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix=".p6-minifs-host-", dir=ROOT
        )
        cls.build_directory = Path(cls.temporary_directory.name) / "build"
        build_relative = cls.build_directory.relative_to(ROOT).as_posix()
        result = subprocess.run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={build_relative}",
                "-j4",
                "image",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.volume = cls.build_directory / "fs/minifs.img"
        cls.image = cls.build_directory / "miniorangeos.img"
        cls.layout = json.loads(
            (ROOT / "config/image-layout.json").read_text(encoding="utf-8")
        )
        cls.fields = SUPERBLOCK.unpack_from(cls.volume.read_bytes())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def _inode(self, number: int, payload: bytes | None = None) -> tuple[int, ...]:
        data = self.volume.read_bytes() if payload is None else payload
        inode_table_start = self.fields[9]
        return INODE.unpack_from(data, inode_table_start * BLOCK_SIZE + number * INODE_SIZE)

    def _directory(self, number: int, payload: bytes | None = None) -> dict[str, tuple[int, int]]:
        data = self.volume.read_bytes() if payload is None else payload
        inode = self._inode(number, data)
        result: dict[str, tuple[int, int]] = {}
        remaining = inode[2]
        for block in inode[3:13]:
            if remaining == 0:
                break
            chunk = data[block * BLOCK_SIZE : (block + 1) * BLOCK_SIZE]
            for offset in range(0, min(remaining, BLOCK_SIZE), DIRECTORY_ENTRY.size):
                child, entry_type, raw_name = DIRECTORY_ENTRY.unpack_from(chunk, offset)
                self.assertNotEqual(0, entry_type)
                name = raw_name.split(b"\0", 1)[0].decode("ascii")
                result[name] = (child, entry_type)
            remaining -= min(remaining, BLOCK_SIZE)
        self.assertEqual(0, remaining)
        return result

    def _file(self, number: int) -> bytes:
        data = self.volume.read_bytes()
        inode = self._inode(number, data)
        blocks = list(inode[3:13])
        if inode[2] > 10 * BLOCK_SIZE:
            blocks.extend(struct.unpack_from("<1024I", data, inode[13] * BLOCK_SIZE))
        content = b"".join(
            data[block * BLOCK_SIZE : (block + 1) * BLOCK_SIZE]
            for block in blocks
            if block != 0
        )
        return content[: inode[2]]

    def _fsck(self, path: Path, *, whole_image: bool = False) -> subprocess.CompletedProcess[str]:
        option = "--image" if whole_image else "--volume"
        return subprocess.run(
            [
                sys.executable,
                "tools/fsck.py",
                "--layout",
                "config/image-layout.json",
                option,
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    def test_superblock_and_layout_contract(self) -> None:
        component = next(
            item for item in self.layout["components"] if item["name"] == "minifs"
        )
        self.assertEqual(("fs/minifs.img", 2048, 129024), (
            component["artifact"], component["lba"], component["max_sectors"]
        ))
        self.assertEqual(129024 * 512, self.volume.stat().st_size)
        self.assertEqual(
            (MAGIC, VERSION, BLOCK_SIZE, 16128, 1024), self.fields[:5]
        )
        self.assertEqual(0, self.fields[12])
        superblock = bytearray(self.volume.read_bytes()[:BLOCK_SIZE])
        checksum = self.fields[13]
        struct.pack_into("<I", superblock, CHECKSUM_OFFSET, 0)
        self.assertEqual(checksum, zlib.crc32(superblock) & 0xFFFFFFFF)

        abi = (ROOT / "include/minios/abi/minifs.h").read_text(encoding="utf-8")
        for contract in (
            "MINIFS_MAGIC 0x3153464DU",
            "MINIFS_BLOCK_SIZE 4096U",
            "MINIFS_INODE_SIZE 64U",
            "MINIFS_DIRECTORY_ENTRY_SIZE 64U",
            "MINIFS_DIRECT_COUNT 10U",
            "MINIFS_SUPERBLOCK_CHECKSUM_OFFSET 52U",
            "MINIFS_INODE_INDIRECT_OFFSET 48U",
            "MINIFS_DIRECTORY_NAME_BYTES 59U",
        ):
            self.assertIn(contract, abi)

    def test_image_contains_exact_volume_and_imported_programs(self) -> None:
        component = next(
            item for item in self.layout["components"] if item["name"] == "minifs"
        )
        image = self.image.read_bytes()
        volume = self.volume.read_bytes()
        offset = component["lba"] * self.layout["sector_size"]
        self.assertEqual(volume, image[offset : offset + len(volume)])

        root = self._directory(0)
        self.assertEqual((0, MODE_DIRECTORY), root["."])
        self.assertEqual((0, MODE_DIRECTORY), root[".."])
        bin_inode, bin_type = root["bin"]
        self.assertEqual(MODE_DIRECTORY, bin_type)
        directory = self._directory(bin_inode)
        self.assertEqual((bin_inode, MODE_DIRECTORY), directory["."])
        self.assertEqual((0, MODE_DIRECTORY), directory[".."])
        for name in PROGRAMS:
            inode_number, entry_type = directory[name]
            self.assertEqual(MODE_REGULAR, entry_type)
            self.assertEqual(
                (self.build_directory / f"user/bin/{name}.elf").read_bytes(),
                self._file(inode_number),
            )

    def test_fsck_accepts_volume_and_whole_image_without_writing(self) -> None:
        for path, whole_image in ((self.volume, False), (self.image, True)):
            with self.subTest(path=path.name):
                before = hashlib.sha256(path.read_bytes()).digest()
                result = self._fsck(path, whole_image=whole_image)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("MiniFS fsck PASS", result.stdout)
                self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())

    def test_fsck_rejects_corruption_without_modifying_input(self) -> None:
        original = self.volume.read_bytes()
        root = self._inode(0, original)
        cases: dict[str, bytearray] = {}

        bad_magic = bytearray(original)
        bad_magic[0] ^= 0xFF
        cases["bad-magic"] = bad_magic

        bad_checksum = bytearray(original)
        bad_checksum[100] ^= 0x01
        cases["bad-checksum"] = bad_checksum

        bad_bitmap = bytearray(original)
        bitmap_offset = self.fields[5] * BLOCK_SIZE
        root_block = root[3]
        bad_bitmap[bitmap_offset + root_block // 8] &= ~(1 << (root_block % 8))
        cases["bitmap-mismatch"] = bad_bitmap

        directory = self._directory(self._directory(0)["bin"][0])
        init_inode = directory["init"][0]
        echo_inode = directory["echo"][0]
        duplicate = bytearray(original)
        inode_table = self.fields[9] * BLOCK_SIZE
        init_block = self._inode(init_inode, original)[3]
        struct.pack_into("<I", duplicate, inode_table + echo_inode * INODE_SIZE + 8, init_block)
        cases["duplicate-block"] = duplicate

        orphan = bytearray(original)
        orphan_inode = 8
        inode_bitmap = self.fields[7] * BLOCK_SIZE
        orphan[inode_bitmap + orphan_inode // 8] |= 1 << (orphan_inode % 8)
        INODE.pack_into(
            orphan,
            inode_table + orphan_inode * INODE_SIZE,
            MODE_REGULAR,
            1,
            0,
            *([0] * 10),
            0,
            0,
            0,
            0,
        )
        cases["orphan-inode"] = orphan

        for name, payload in cases.items():
            with self.subTest(name=name):
                path = Path(self.temporary_directory.name) / f"{name}.img"
                path.write_bytes(payload)
                before = hashlib.sha256(path.read_bytes()).digest()
                result = self._fsck(path)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("fsck.py: error:", result.stderr)
                self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())

    def test_mkfs_rejects_invalid_import_without_clobbering_output(self) -> None:
        output = Path(self.temporary_directory.name) / "preserved.img"
        invalid = Path(self.temporary_directory.name) / "not-elf.bin"
        marker = b"preserve-existing-output"
        output.write_bytes(marker)
        invalid.write_bytes(b"not an ELF")
        result = subprocess.run(
            [
                sys.executable,
                "tools/mkfs.py",
                "--layout",
                "config/image-layout.json",
                "--output",
                str(output),
                "--import",
                f"/bin/bad={invalid}",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("mkfs.py: error:", result.stderr)
        self.assertEqual(marker, output.read_bytes())

    def test_mkfs_output_is_deterministic(self) -> None:
        second_build = Path(self.temporary_directory.name) / "second-build"
        relative = second_build.relative_to(ROOT).as_posix()
        result = subprocess.run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={relative}",
                "-j4",
                "image",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            hashlib.sha256(self.volume.read_bytes()).digest(),
            hashlib.sha256((second_build / "fs/minifs.img").read_bytes()).digest(),
        )


if __name__ == "__main__":
    unittest.main()
