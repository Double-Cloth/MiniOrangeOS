#!/usr/bin/env python3
"""创建确定性的 MiniFS 卷并导入 /bin 静态 ELF。"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


sys.dont_write_bytecode = True

import minifs


@dataclass(frozen=True)
class ImportedFile:
    name: str
    payload: bytes


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_file(path: Path) -> bytes:
    try:
        named_before = path.lstat()
        if not stat.S_ISREG(named_before.st_mode) or named_before.st_nlink != 1:
            minifs.fail(f"导入源必须是单链接普通文件：{path}")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        minifs.fail(f"无法安全打开导入源 {path}：{error}")
    try:
        opened = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(named_before):
            minifs.fail(f"导入源在打开前被替换：{path}")
        if opened.st_size <= 0 or opened.st_size > minifs.MAX_FILE_SIZE:
            minifs.fail(f"导入源大小超出 MiniFS 文件上限：{path}")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 256 * 1024))
            if not chunk:
                minifs.fail(f"导入源读取不完整：{path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            minifs.fail(f"导入源在读取过程中增长：{path}")
        if _file_identity(os.fstat(descriptor)) != _file_identity(opened):
            minifs.fail(f"导入源在读取过程中变化：{path}")
        named_after = path.lstat()
        if _file_identity(named_after) != _file_identity(opened):
            minifs.fail(f"导入源路径在读取过程中被替换：{path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_imports(values: list[str]) -> tuple[ImportedFile, ...]:
    result: list[ImportedFile] = []
    destinations: set[str] = set()
    for value in values:
        destination, separator, source = value.partition("=")
        parts = destination.split("/")
        if separator != "=" or len(parts) != 3 or parts[:2] != ["", "bin"]:
            minifs.fail(f"导入参数必须使用 /bin/name=source：{value!r}")
        name = parts[2]
        minifs.encode_directory_entry(0, minifs.ENTRY_REGULAR, name)
        if destination in destinations:
            minifs.fail(f"重复导入路径：{destination}")
        destinations.add(destination)
        payload = _read_stable_file(Path(source))
        if not payload.startswith(b"\x7fELF"):
            minifs.fail(f"/bin 导入源不是 ELF：{source}")
        result.append(ImportedFile(name, payload))
    result.sort(key=lambda item: item.name.encode("ascii"))
    if not result:
        minifs.fail("至少需要导入一个 /bin 程序")
    if len(result) + 2 > minifs.BLOCK_SIZE // minifs.DIRECTORY_ENTRY_SIZE:
        minifs.fail("/bin 初始目录项超过一个目录块")
    return tuple(result)


class Builder:
    def __init__(self, total_blocks: int, total_inodes: int) -> None:
        self.superblock = minifs.make_superblock(total_blocks, total_inodes)
        self.payload = bytearray(total_blocks * minifs.BLOCK_SIZE)
        self.next_block = self.superblock.data_start
        self.block_bitmap_offset = (
            self.superblock.block_bitmap_start * minifs.BLOCK_SIZE
        )
        self.inode_bitmap_offset = (
            self.superblock.inode_bitmap_start * minifs.BLOCK_SIZE
        )
        for block in range(self.superblock.data_start):
            self._mark_block(block)
        block_capacity = (
            self.superblock.block_bitmap_blocks * minifs.BLOCK_SIZE * 8
        )
        for block in range(total_blocks, block_capacity):
            self._mark_block(block)
        inode_capacity = (
            self.superblock.inode_bitmap_blocks * minifs.BLOCK_SIZE * 8
        )
        for inode in range(total_inodes, inode_capacity):
            self._mark_inode(inode)

    def _mark_block(self, block: int) -> None:
        minifs.bitmap_set(self.payload, self.block_bitmap_offset, block)

    def _mark_inode(self, inode: int) -> None:
        minifs.bitmap_set(self.payload, self.inode_bitmap_offset, inode)

    def allocate_block(self) -> int:
        if self.next_block >= self.superblock.total_blocks:
            minifs.fail("MiniFS 数据块耗尽")
        block = self.next_block
        self.next_block += 1
        self._mark_block(block)
        return block

    def write_inode(self, number: int, value: minifs.Inode) -> None:
        if number < 0 or number >= self.superblock.total_inodes:
            minifs.fail("MiniFS inode 耗尽")
        offset = (
            self.superblock.inode_table_start * minifs.BLOCK_SIZE
            + number * minifs.INODE_SIZE
        )
        self.payload[offset : offset + minifs.INODE_SIZE] = minifs.encode_inode(value)
        self._mark_inode(number)

    def write_file(self, number: int, payload: bytes) -> None:
        block_count = minifs.blocks_for_bytes(len(payload), minifs.BLOCK_SIZE)
        if block_count > minifs.MAX_FILE_BLOCKS:
            minifs.fail("导入文件超过 MiniFS 一级间接块上限")
        blocks: list[int] = []
        for index in range(block_count):
            block = self.allocate_block()
            blocks.append(block)
            start = index * minifs.BLOCK_SIZE
            chunk = payload[start : start + minifs.BLOCK_SIZE]
            offset = block * minifs.BLOCK_SIZE
            self.payload[offset : offset + len(chunk)] = chunk
        direct = blocks[: minifs.DIRECT_COUNT]
        direct.extend([0] * (minifs.DIRECT_COUNT - len(direct)))
        indirect = 0
        if block_count > minifs.DIRECT_COUNT:
            indirect = self.allocate_block()
            offset = indirect * minifs.BLOCK_SIZE
            for index, block in enumerate(blocks[minifs.DIRECT_COUNT :]):
                self.payload[offset + index * 4 : offset + index * 4 + 4] = (
                    block.to_bytes(4, "little")
                )
        self.write_inode(
            number,
            minifs.Inode(
                minifs.MODE_REGULAR,
                1,
                len(payload),
                tuple(direct),
                indirect,
            ),
        )

    def write_directory(
        self,
        number: int,
        link_count: int,
        entries: tuple[tuple[int, int, str], ...],
    ) -> None:
        content = b"".join(
            minifs.encode_directory_entry(inode, entry_type, name)
            for inode, entry_type, name in entries
        )
        if len(content) > minifs.BLOCK_SIZE:
            minifs.fail("初始目录超过一个数据块")
        block = self.allocate_block()
        offset = block * minifs.BLOCK_SIZE
        self.payload[offset : offset + len(content)] = content
        direct = (block,) + (0,) * (minifs.DIRECT_COUNT - 1)
        self.write_inode(
            number,
            minifs.Inode(
                minifs.MODE_DIRECTORY,
                link_count,
                len(content),
                direct,
                0,
            ),
        )

    def finish(self) -> bytes:
        self.payload[: minifs.BLOCK_SIZE] = minifs.encode_superblock(self.superblock)
        return bytes(self.payload)


def _build_volume(layout: minifs.VolumeLayout, imports: tuple[ImportedFile, ...]) -> bytes:
    if len(imports) + 2 > minifs.DEFAULT_INODE_COUNT:
        minifs.fail("初始文件数量超过 inode 容量")
    builder = Builder(layout.block_count, minifs.DEFAULT_INODE_COUNT)
    root_inode = 0
    bin_inode = 1
    file_numbers = {item.name: index + 2 for index, item in enumerate(imports)}

    builder.write_directory(
        root_inode,
        3,
        (
            (root_inode, minifs.ENTRY_DIRECTORY, "."),
            (root_inode, minifs.ENTRY_DIRECTORY, ".."),
            (bin_inode, minifs.ENTRY_DIRECTORY, "bin"),
        ),
    )
    builder.write_directory(
        bin_inode,
        2,
        (
            (bin_inode, minifs.ENTRY_DIRECTORY, "."),
            (root_inode, minifs.ENTRY_DIRECTORY, ".."),
            *tuple(
                (file_numbers[item.name], minifs.ENTRY_REGULAR, item.name)
                for item in imports
            ),
        ),
    )
    for item in imports:
        builder.write_file(file_numbers[item.name], item.payload)
    return builder.finish()


def _write_atomic(path: Path, payload: bytes) -> None:
    try:
        path.parent.mkdir(parents=False, exist_ok=True)
        parent_status = path.parent.stat()
        if not stat.S_ISDIR(parent_status.st_mode):
            minifs.fail("输出父路径不是目录")
        try:
            target_status = path.lstat()
        except FileNotFoundError:
            target_status = None
        if target_status is not None and (
            not stat.S_ISREG(target_status.st_mode) or target_status.st_nlink != 1
        ):
            minifs.fail("已有输出必须是单链接普通文件")
        temporary = path.parent / (
            f".{path.name}.{os.getpid()}.{secrets.token_hex(12)}.tmp"
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
    except OSError as error:
        minifs.fail(f"无法创建 MiniFS 输出：{error}")
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                minifs.fail("MiniFS 输出写入没有取得进展")
            view = view[written:]
        os.fsync(descriptor)
        if os.fstat(descriptor).st_size != len(payload):
            minifs.fail("MiniFS 输出大小不完整")
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        minifs.fail(f"无法原子提交 MiniFS 输出：{error}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--import", dest="imports", action="append", default=[])
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    try:
        layout = minifs.load_volume_layout(options.layout)
        imports = _parse_imports(options.imports)
        payload = _build_volume(layout, imports)
        if len(payload) != layout.byte_size:
            minifs.fail("生成卷大小与镜像布局不一致")
        _write_atomic(options.output, payload)
    except (minifs.MiniFsError, OSError) as error:
        print(f"mkfs.py: error: {error}", file=sys.stderr)
        return 2
    print(
        f"MiniFS mkfs PASS blocks={layout.block_count} "
        f"inodes={minifs.DEFAULT_INODE_COUNT} files={len(imports)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
