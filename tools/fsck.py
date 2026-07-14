#!/usr/bin/env python3
"""只读检查 MiniFS superblock、bitmap、inode、目录与块所有权。"""

from __future__ import annotations

import argparse
import os
import stat
import struct
import sys
from collections import deque
from pathlib import Path


sys.dont_write_bytecode = True

import minifs


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable(path: Path, expected_size: int) -> bytes:
    try:
        named_before = path.lstat()
        if (
            not stat.S_ISREG(named_before.st_mode)
            or named_before.st_nlink != 1
            or named_before.st_size != expected_size
        ):
            minifs.fail(f"检查输入必须是大小正确的单链接普通文件：{path}")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        minifs.fail(f"无法安全打开检查输入：{error}")
    try:
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(named_before):
            minifs.fail("检查输入在打开前被替换")
        chunks: list[bytes] = []
        remaining = expected_size
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 256 * 1024))
            if not chunk:
                minifs.fail("检查输入读取不完整")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            minifs.fail("检查输入在读取过程中增长")
        if _identity(os.fstat(descriptor)) != _identity(opened):
            minifs.fail("检查输入在读取过程中变化")
        if _identity(path.lstat()) != _identity(opened):
            minifs.fail("检查输入路径在读取过程中被替换")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


class Checker:
    def __init__(self, volume: memoryview, expected_blocks: int) -> None:
        self.volume = volume
        self.superblock = minifs.decode_superblock(volume[: minifs.BLOCK_SIZE])
        if self.superblock.total_blocks != expected_blocks:
            minifs.fail("Superblock total_blocks 与镜像布局不一致")
        expected = minifs.make_superblock(
            self.superblock.total_blocks, self.superblock.total_inodes
        )
        actual_geometry = (
            self.superblock.block_bitmap_start,
            self.superblock.block_bitmap_blocks,
            self.superblock.inode_bitmap_start,
            self.superblock.inode_bitmap_blocks,
            self.superblock.inode_table_start,
            self.superblock.inode_table_blocks,
            self.superblock.data_start,
            self.superblock.root_inode,
        )
        expected_geometry = (
            expected.block_bitmap_start,
            expected.block_bitmap_blocks,
            expected.inode_bitmap_start,
            expected.inode_bitmap_blocks,
            expected.inode_table_start,
            expected.inode_table_blocks,
            expected.data_start,
            expected.root_inode,
        )
        if actual_geometry != expected_geometry:
            minifs.fail("Superblock 元数据区域不连续或大小不足")
        if self.superblock.total_inodes <= 0:
            minifs.fail("Superblock total_inodes 无效")
        self.block_bitmap = volume[
            self.superblock.block_bitmap_start * minifs.BLOCK_SIZE :
            (self.superblock.block_bitmap_start + self.superblock.block_bitmap_blocks)
            * minifs.BLOCK_SIZE
        ]
        self.inode_bitmap = volume[
            self.superblock.inode_bitmap_start * minifs.BLOCK_SIZE :
            (self.superblock.inode_bitmap_start + self.superblock.inode_bitmap_blocks)
            * minifs.BLOCK_SIZE
        ]
        self.inodes: dict[int, minifs.Inode] = {}
        self.file_blocks: dict[int, tuple[int, ...]] = {}
        self.claimed_blocks: dict[int, str] = {
            block: "metadata" for block in range(self.superblock.data_start)
        }

    def _inode_raw(self, number: int) -> memoryview:
        offset = (
            self.superblock.inode_table_start * minifs.BLOCK_SIZE
            + number * minifs.INODE_SIZE
        )
        return self.volume[offset : offset + minifs.INODE_SIZE]

    def _claim_data_block(self, block: int, owner: str) -> None:
        if block < self.superblock.data_start or block >= self.superblock.total_blocks:
            minifs.fail(f"{owner} 引用了非数据区域块 {block}")
        previous = self.claimed_blocks.get(block)
        if previous is not None:
            minifs.fail(f"数据块 {block} 被重复引用：{previous} 与 {owner}")
        if not minifs.bitmap_get(self.block_bitmap, block):
            minifs.fail(f"{owner} 引用的块 {block} 未在 block bitmap 标记")
        self.claimed_blocks[block] = owner

    def _load_inodes(self) -> None:
        for number in range(self.superblock.total_inodes):
            allocated = minifs.bitmap_get(self.inode_bitmap, number)
            raw = self._inode_raw(number)
            if not allocated:
                if any(raw):
                    minifs.fail(f"未分配 inode {number} 的磁盘记录非零")
                continue
            inode = minifs.decode_inode(raw, 0)
            if inode.mode not in {minifs.MODE_REGULAR, minifs.MODE_DIRECTORY}:
                minifs.fail(f"inode {number} mode 无效")
            if inode.link_count == 0 or inode.reserved != 0:
                minifs.fail(f"inode {number} link_count 或 reserved 无效")
            if inode.size > minifs.MAX_FILE_SIZE:
                minifs.fail(f"inode {number} size 超过文件上限")
            if inode.mode == minifs.MODE_DIRECTORY and (
                inode.size == 0 or inode.size % minifs.DIRECTORY_ENTRY_SIZE != 0
            ):
                minifs.fail(f"目录 inode {number} size 无效")
            required = minifs.blocks_for_bytes(inode.size, minifs.BLOCK_SIZE)
            direct_required = min(required, minifs.DIRECT_COUNT)
            blocks: list[int] = []
            for index, block in enumerate(inode.direct):
                if index < direct_required:
                    if block == 0:
                        minifs.fail(f"inode {number} 缺少 direct[{index}]")
                    self._claim_data_block(block, f"inode {number} direct[{index}]")
                    blocks.append(block)
                elif block != 0:
                    minifs.fail(f"inode {number} 存在超出 size 的 direct[{index}]")
            indirect_required = required - direct_required
            if indirect_required > 0:
                if inode.indirect == 0:
                    minifs.fail(f"inode {number} 缺少 indirect 块")
                self._claim_data_block(inode.indirect, f"inode {number} indirect")
                pointer_offset = inode.indirect * minifs.BLOCK_SIZE
                pointers = struct.unpack_from(
                    f"<{minifs.INDIRECT_COUNT}I", self.volume, pointer_offset
                )
                for index, block in enumerate(pointers):
                    if index < indirect_required:
                        if block == 0:
                            minifs.fail(f"inode {number} indirect[{index}] 为空")
                        self._claim_data_block(
                            block, f"inode {number} indirect[{index}]"
                        )
                        blocks.append(block)
                    elif block != 0:
                        minifs.fail(f"inode {number} 存在超出 size 的 indirect[{index}]")
            elif inode.indirect != 0:
                minifs.fail(f"inode {number} 存在不需要的 indirect 块")
            self.inodes[number] = inode
            self.file_blocks[number] = tuple(blocks)
        if self.superblock.root_inode not in self.inodes:
            minifs.fail("root_inode 未分配")
        if self.inodes[self.superblock.root_inode].mode != minifs.MODE_DIRECTORY:
            minifs.fail("root_inode 不是目录")

    def _check_bitmap_coverage(self) -> None:
        for block in range(self.superblock.total_blocks):
            marked = minifs.bitmap_get(self.block_bitmap, block)
            claimed = block in self.claimed_blocks
            if marked != claimed:
                minifs.fail(f"block bitmap 与块 {block} 的所有权不一致")
        block_capacity = len(self.block_bitmap) * 8
        for block in range(self.superblock.total_blocks, block_capacity):
            if not minifs.bitmap_get(self.block_bitmap, block):
                minifs.fail("block bitmap 容量外尾部 bit 必须置 1")
        inode_capacity = len(self.inode_bitmap) * 8
        for inode in range(self.superblock.total_inodes, inode_capacity):
            if not minifs.bitmap_get(self.inode_bitmap, inode):
                minifs.fail("inode bitmap 容量外尾部 bit 必须置 1")

    def _read_inode_content(self, number: int) -> bytes:
        inode = self.inodes[number]
        content = b"".join(
            self.volume[
                block * minifs.BLOCK_SIZE : (block + 1) * minifs.BLOCK_SIZE
            ].tobytes()
            for block in self.file_blocks[number]
        )
        return content[: inode.size]

    def _decode_name(self, raw: bytes, owner: int) -> str:
        terminator = raw.find(b"\0")
        if terminator <= 0 or terminator > minifs.NAME_MAX:
            minifs.fail(f"目录 inode {owner} 包含未终止或空名称")
        if any(raw[terminator + 1 :]):
            minifs.fail(f"目录 inode {owner} 的名称填充非零")
        name_bytes = raw[:terminator]
        if b"/" in name_bytes:
            minifs.fail(f"目录 inode {owner} 的名称包含斜杠")
        try:
            return name_bytes.decode("ascii")
        except UnicodeDecodeError:
            minifs.fail(f"目录 inode {owner} 包含非 ASCII 初始名称")

    def _check_directories(self) -> tuple[int, int]:
        root = self.superblock.root_inode
        queue: deque[tuple[int, int]] = deque([(root, root)])
        visited_directories: set[int] = set()
        reachable: set[int] = {root}
        references = {number: 0 for number in self.inodes}
        while queue:
            number, parent = queue.popleft()
            if number in visited_directories:
                minifs.fail(f"目录 inode {number} 被多个父目录引用")
            visited_directories.add(number)
            content = self._read_inode_content(number)
            names: dict[str, tuple[int, int]] = {}
            for offset in range(0, len(content), minifs.DIRECTORY_ENTRY_SIZE):
                child, entry_type, raw_name = minifs.DIRECTORY_ENTRY_STRUCT.unpack_from(
                    content, offset
                )
                if entry_type not in {minifs.ENTRY_REGULAR, minifs.ENTRY_DIRECTORY}:
                    minifs.fail(f"目录 inode {number} 包含无效 type")
                name = self._decode_name(raw_name, number)
                if name in names:
                    minifs.fail(f"目录 inode {number} 包含重复名称 {name!r}")
                if child not in self.inodes:
                    minifs.fail(f"目录 inode {number} 引用未分配 inode {child}")
                expected_type = (
                    minifs.ENTRY_DIRECTORY
                    if self.inodes[child].mode == minifs.MODE_DIRECTORY
                    else minifs.ENTRY_REGULAR
                )
                if entry_type != expected_type:
                    minifs.fail(f"目录项 {name!r} type 与 inode mode 不一致")
                names[name] = (child, entry_type)
                references[child] += 1
            if names.get(".") != (number, minifs.ENTRY_DIRECTORY):
                minifs.fail(f"目录 inode {number} 的 . 项无效")
            if names.get("..") != (parent, minifs.ENTRY_DIRECTORY):
                minifs.fail(f"目录 inode {number} 的 .. 项无效")
            for name, (child, entry_type) in names.items():
                if name in {".", ".."}:
                    continue
                reachable.add(child)
                if entry_type == minifs.ENTRY_DIRECTORY:
                    queue.append((child, number))
        allocated = set(self.inodes)
        if reachable != allocated:
            missing = sorted(allocated - reachable)
            minifs.fail(f"存在不可达 inode：{missing}")
        for number, inode in self.inodes.items():
            if references[number] != inode.link_count:
                minifs.fail(
                    f"inode {number} link_count={inode.link_count}，"
                    f"目录引用数={references[number]}"
                )
        regular = sum(
            inode.mode == minifs.MODE_REGULAR for inode in self.inodes.values()
        )
        return regular, len(visited_directories)

    def run(self) -> tuple[int, int, int]:
        self._load_inodes()
        self._check_bitmap_coverage()
        regular, directories = self._check_directories()
        return len(self.inodes), regular, directories


def _parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--layout", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--volume", type=Path)
    source.add_argument("--image", type=Path)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    try:
        layout = minifs.load_volume_layout(options.layout)
        if options.volume is not None:
            payload = _read_stable(options.volume, layout.byte_size)
            volume = memoryview(payload)
        else:
            payload = _read_stable(options.image, layout.image_size_bytes)
            volume = memoryview(payload)[
                layout.byte_offset : layout.byte_offset + layout.byte_size
            ]
        checker = Checker(volume, layout.block_count)
        allocated, regular, directories = checker.run()
    except (minifs.MiniFsError, OSError, struct.error) as error:
        print(f"fsck.py: error: {error}", file=sys.stderr)
        return 2
    print(
        f"MiniFS fsck PASS blocks={layout.block_count} allocated_inodes={allocated} "
        f"files={regular} directories={directories}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
