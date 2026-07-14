#!/usr/bin/env python3
"""MiniFS 宿主工具共享的磁盘 ABI 与显式编解码。"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn


sys.dont_write_bytecode = True

MAGIC = 0x3153464D
VERSION = 1
SECTOR_SIZE = 512
BLOCK_SIZE = 4096
SECTORS_PER_BLOCK = BLOCK_SIZE // SECTOR_SIZE
INODE_SIZE = 64
DIRECTORY_ENTRY_SIZE = 64
DIRECT_COUNT = 10
INDIRECT_COUNT = BLOCK_SIZE // 4
NAME_MAX = 58
MODE_REGULAR = 1
MODE_DIRECTORY = 2
ENTRY_UNUSED = 0
ENTRY_REGULAR = 1
ENTRY_DIRECTORY = 2
DEFAULT_INODE_COUNT = 1024
SUPERBLOCK_HEADER = struct.Struct("<14I")
INODE_STRUCT = struct.Struct("<HHI10I4I")
DIRECTORY_ENTRY_STRUCT = struct.Struct("<IB59s")
CHECKSUM_OFFSET = 52
MAX_FILE_BLOCKS = DIRECT_COUNT + INDIRECT_COUNT
MAX_FILE_SIZE = MAX_FILE_BLOCKS * BLOCK_SIZE
ROOT_FIELDS = {"format_version", "sector_size", "image_size_bytes", "components"}
COMPONENT_FIELDS = {"name", "artifact", "lba", "max_sectors"}


class MiniFsError(Exception):
    """表示 MiniFS 输入或磁盘结构不满足契约。"""


def fail(message: str) -> NoReturn:
    raise MiniFsError(message)


@dataclass(frozen=True)
class VolumeLayout:
    image_size_bytes: int
    artifact: str
    lba: int
    sector_count: int

    @property
    def byte_offset(self) -> int:
        return self.lba * SECTOR_SIZE

    @property
    def byte_size(self) -> int:
        return self.sector_count * SECTOR_SIZE

    @property
    def block_count(self) -> int:
        return self.sector_count // SECTORS_PER_BLOCK


@dataclass(frozen=True)
class Superblock:
    magic: int
    version: int
    block_size: int
    total_blocks: int
    total_inodes: int
    block_bitmap_start: int
    block_bitmap_blocks: int
    inode_bitmap_start: int
    inode_bitmap_blocks: int
    inode_table_start: int
    inode_table_blocks: int
    data_start: int
    root_inode: int
    checksum: int


@dataclass(frozen=True)
class Inode:
    mode: int
    link_count: int
    size: int
    direct: tuple[int, ...]
    indirect: int
    created_tick: int = 0
    modified_tick: int = 0
    reserved: int = 0


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"JSON 包含重复字段：{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    fail(f"JSON 不允许非标准数值：{value}")


def _integer(value: object, location: str) -> int:
    if type(value) is not int:
        fail(f"{location} 必须是 integer 且不能是 boolean")
    assert isinstance(value, int)
    return value


def _string(value: object, location: str) -> str:
    if type(value) is not str or not value or "\0" in value:
        fail(f"{location} 必须是非空且不含 NUL 的 string")
    assert isinstance(value, str)
    return value


def load_volume_layout(path: Path) -> VolumeLayout:
    try:
        raw = path.read_bytes()
    except OSError as error:
        fail(f"无法读取镜像布局：{error}")
    if not raw or len(raw) > 1024 * 1024:
        fail("镜像布局大小不合理")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"镜像布局不是严格 UTF-8 JSON：{error}")
    if type(value) is not dict or set(value) != ROOT_FIELDS:
        fail("镜像布局顶层 schema 无效")
    assert isinstance(value, dict)
    if _integer(value["format_version"], "format_version") != 1:
        fail("仅支持镜像布局 format_version=1")
    if _integer(value["sector_size"], "sector_size") != SECTOR_SIZE:
        fail("MiniFS 仅支持 512 字节镜像扇区")
    image_size = _integer(value["image_size_bytes"], "image_size_bytes")
    if image_size <= 0 or image_size % SECTOR_SIZE != 0:
        fail("image_size_bytes 必须是正的完整扇区倍数")
    components = value["components"]
    if type(components) is not list or not components:
        fail("components 必须是非空数组")
    assert isinstance(components, list)
    names: set[str] = set()
    regions: list[tuple[int, int, str]] = []
    minifs_components: list[tuple[str, int, int]] = []
    image_sectors = image_size // SECTOR_SIZE
    for index, item in enumerate(components):
        if type(item) is not dict or set(item) != COMPONENT_FIELDS:
            fail(f"components[{index}] schema 无效")
        assert isinstance(item, dict)
        name = _string(item["name"], f"components[{index}].name")
        artifact = _string(item["artifact"], f"components[{index}].artifact")
        if name in names:
            fail(f"镜像布局包含重复组件：{name}")
        names.add(name)
        posix = PurePosixPath(artifact)
        if (
            posix.is_absolute()
            or PureWindowsPath(artifact).is_absolute()
            or "\\" in artifact
            or any(part in {"", ".", ".."} for part in artifact.split("/"))
        ):
            fail(f"组件 {name} 的 artifact 不是安全 POSIX 相对路径")
        lba = _integer(item["lba"], f"components[{index}].lba")
        sectors = _integer(
            item["max_sectors"], f"components[{index}].max_sectors"
        )
        if lba < 0 or sectors <= 0 or lba + sectors > image_sectors:
            fail(f"组件 {name} 越过镜像边界")
        regions.append((lba, lba + sectors, name))
        if name == "minifs":
            minifs_components.append((artifact, lba, sectors))
    regions.sort()
    for previous, current in zip(regions, regions[1:]):
        if current[0] < previous[1]:
            fail(f"镜像组件重叠：{previous[2]} 与 {current[2]}")
    if len(minifs_components) != 1:
        fail("镜像布局必须且只能包含一个 minifs 组件")
    artifact, lba, sectors = minifs_components[0]
    if lba % SECTORS_PER_BLOCK != 0 or sectors % SECTORS_PER_BLOCK != 0:
        fail("MiniFS 起点和大小必须按 4 KiB 块对齐")
    if lba + sectors != image_sectors:
        fail("MiniFS 必须占满镜像尾部区域")
    return VolumeLayout(image_size, artifact, lba, sectors)


def blocks_for_bytes(size: int, unit: int) -> int:
    if size < 0 or unit <= 0:
        fail("块数量计算参数无效")
    return (size + unit - 1) // unit


def make_superblock(total_blocks: int, total_inodes: int) -> Superblock:
    if total_blocks <= 0 or total_inodes <= 0:
        fail("MiniFS 容量必须为正数")
    block_bitmap_blocks = blocks_for_bytes(total_blocks, BLOCK_SIZE * 8)
    inode_bitmap_blocks = blocks_for_bytes(total_inodes, BLOCK_SIZE * 8)
    inode_table_blocks = blocks_for_bytes(total_inodes * INODE_SIZE, BLOCK_SIZE)
    inode_bitmap_start = 1 + block_bitmap_blocks
    inode_table_start = inode_bitmap_start + inode_bitmap_blocks
    data_start = inode_table_start + inode_table_blocks
    if data_start >= total_blocks:
        fail("MiniFS 容量不足以容纳元数据")
    return Superblock(
        MAGIC,
        VERSION,
        BLOCK_SIZE,
        total_blocks,
        total_inodes,
        1,
        block_bitmap_blocks,
        inode_bitmap_start,
        inode_bitmap_blocks,
        inode_table_start,
        inode_table_blocks,
        data_start,
        0,
        0,
    )


def encode_superblock(value: Superblock) -> bytes:
    block = bytearray(BLOCK_SIZE)
    fields = list(value.__dict__.values())
    fields[-1] = 0
    SUPERBLOCK_HEADER.pack_into(block, 0, *fields)
    checksum = zlib.crc32(block) & 0xFFFFFFFF
    struct.pack_into("<I", block, CHECKSUM_OFFSET, checksum)
    return bytes(block)


def decode_superblock(block: bytes | bytearray | memoryview) -> Superblock:
    if len(block) < BLOCK_SIZE:
        fail("Superblock 读取不完整")
    fields = SUPERBLOCK_HEADER.unpack_from(block)
    value = Superblock(*fields)
    if value.magic != MAGIC:
        fail("Superblock magic 无效")
    if value.version != VERSION:
        fail("Superblock version 不受支持")
    if value.block_size != BLOCK_SIZE:
        fail("Superblock block_size 无效")
    copy = bytearray(block[:BLOCK_SIZE])
    struct.pack_into("<I", copy, CHECKSUM_OFFSET, 0)
    if (zlib.crc32(copy) & 0xFFFFFFFF) != value.checksum:
        fail("Superblock checksum 无效")
    if any(block[SUPERBLOCK_HEADER.size:BLOCK_SIZE]):
        fail("Superblock 保留区域必须为 0")
    return value


def encode_inode(value: Inode) -> bytes:
    if len(value.direct) != DIRECT_COUNT:
        fail("inode direct 指针数量无效")
    return INODE_STRUCT.pack(
        value.mode,
        value.link_count,
        value.size,
        *value.direct,
        value.indirect,
        value.created_tick,
        value.modified_tick,
        value.reserved,
    )


def decode_inode(payload: bytes | bytearray | memoryview, offset: int) -> Inode:
    fields = INODE_STRUCT.unpack_from(payload, offset)
    return Inode(
        fields[0],
        fields[1],
        fields[2],
        tuple(fields[3:13]),
        fields[13],
        fields[14],
        fields[15],
        fields[16],
    )


def encode_directory_entry(inode: int, entry_type: int, name: str) -> bytes:
    try:
        encoded = name.encode("ascii")
    except UnicodeEncodeError:
        fail(f"最低版本仅支持 ASCII 目录名：{name!r}")
    if (
        not encoded
        or len(encoded) > NAME_MAX
        or b"/" in encoded
        or b"\0" in encoded
        or entry_type not in {ENTRY_REGULAR, ENTRY_DIRECTORY}
    ):
        fail(f"目录项无效：{name!r}")
    return DIRECTORY_ENTRY_STRUCT.pack(
        inode, entry_type, encoded + bytes(59 - len(encoded))
    )


def bitmap_get(payload: bytes | bytearray | memoryview, bit: int) -> bool:
    if bit < 0 or bit // 8 >= len(payload):
        fail("bitmap bit 越界")
    return (payload[bit // 8] & (1 << (bit % 8))) != 0


def bitmap_set(payload: bytearray, offset: int, bit: int) -> None:
    if bit < 0 or offset + bit // 8 >= len(payload):
        fail("bitmap bit 越界")
    payload[offset + bit // 8] |= 1 << (bit % 8)
