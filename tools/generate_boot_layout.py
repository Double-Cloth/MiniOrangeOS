#!/usr/bin/env python3
"""从可信镜像布局原子生成 Stage 1 使用的 NASM 常量。"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import NoReturn

import build_dir_guard as guard


SECTOR_SIZE = 512
STAGE2_LOAD_ADDRESS = 0x8000
FIRST_DMA_BOUNDARY = 0x10000
MIN_STAGE2_SECTORS = 65
MAX_STAGE2_SECTORS = 127
MAX_DAP_LBA = (1 << 64) - 1
MAX_LAYOUT_BYTES = 1024 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
DIRECTORY_FLAGS |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
FILE_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
FILE_FLAGS |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
EXPECTED_LAYOUT_PARTS = ("config", "image-layout.json")
EXPECTED_OUTPUT_PARTS = ("boot", "image-layout.inc")


class LayoutError(Exception):
    """表示输入边界或镜像布局不满足 Stage 1 契约。"""


def _fail(message: str) -> NoReturn:
    raise LayoutError(message)


def _identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def _file_identity(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _stable_file_identity(status: os.stat_result) -> tuple[int, ...]:
    """返回 rename 不会改变的普通文件身份字段。"""

    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_size,
    )


def _relative_parts(base: str, argument: str, label: str) -> tuple[str, ...]:
    if not argument or "\x00" in argument or "\\" in argument:
        _fail(f"{label} 路径为空或含非法字符")
    raw_parts = argument.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        if not os.path.isabs(argument) or any(
            part in {".", ".."} for part in raw_parts
        ):
            _fail(f"{label} 路径含无效目录段")
    absolute = os.path.abspath(argument)
    try:
        common = os.path.commonpath((base, absolute))
    except ValueError as error:
        _fail(f"无法比较{label}路径：{error}")
    if common != base or absolute == base:
        _fail(f"{label} 必须位于受信目录内")
    relative = os.path.relpath(absolute, base)
    parts = tuple(relative.split(os.sep))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail(f"{label} 相对路径无效")
    return parts


def _open_parent(
    root_descriptor: int, parts: tuple[str, ...]
) -> tuple[int, tuple[tuple[int, int], ...]]:
    descriptor = os.dup(root_descriptor)
    identities: list[tuple[int, int]] = []
    try:
        for part in parts[:-1]:
            next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            identities.append(_identity(os.fstat(descriptor)))
        return descriptor, tuple(identities)
    except BaseException:
        os.close(descriptor)
        raise


@dataclass
class BoundTree:
    """持有经 T02 marker 验证的 repo 与 BUILD_DIR。"""

    repo_descriptor: int
    build_descriptor: int
    location: guard.Location
    repo_identity: tuple[int, int]
    build_identity: tuple[int, int]

    @classmethod
    def open(cls, repo_argument: str, build_argument: str) -> BoundTree:
        try:
            location = guard._validate_arguments(repo_argument, build_argument)
            repo_descriptor = guard._open_repo(location)
            parent_descriptor: int | None = None
            build_descriptor = -1
            try:
                parent_descriptor, name = guard._open_parent(
                    repo_descriptor, location
                )
                if parent_descriptor is None:
                    _fail("BUILD_DIR 不存在")
                build_descriptor = guard._open_named_directory(
                    parent_descriptor, name
                )
                repo_status = os.fstat(repo_descriptor)
                build_status = os.fstat(build_descriptor)
                guard._validate_marker(
                    build_descriptor, location, repo_status, build_status
                )
                return cls(
                    repo_descriptor,
                    build_descriptor,
                    location,
                    _identity(repo_status),
                    _identity(build_status),
                )
            except BaseException:
                if build_descriptor >= 0:
                    os.close(build_descriptor)
                os.close(repo_descriptor)
                raise
            finally:
                if parent_descriptor is not None:
                    os.close(parent_descriptor)
        except (guard.GuardError, OSError) as error:
            _fail(f"无法绑定可信 repo/BUILD_DIR：{error}")

    def _fresh_repo(self) -> int:
        descriptor = guard._open_repo(self.location)
        if _identity(os.fstat(descriptor)) != self.repo_identity:
            os.close(descriptor)
            _fail("repo 在生成过程中被替换")
        return descriptor

    def _fresh_build(self) -> int:
        repo_descriptor = self._fresh_repo()
        parent_descriptor: int | None = None
        build_descriptor = -1
        try:
            parent_descriptor, name = guard._open_parent(
                repo_descriptor, self.location
            )
            if parent_descriptor is None:
                _fail("BUILD_DIR 在生成过程中消失")
            build_descriptor = guard._open_named_directory(parent_descriptor, name)
            status = os.fstat(build_descriptor)
            if _identity(status) != self.build_identity:
                _fail("BUILD_DIR 在生成过程中被替换")
            guard._validate_marker(
                build_descriptor,
                self.location,
                os.fstat(repo_descriptor),
                status,
            )
            return build_descriptor
        except BaseException:
            if build_descriptor >= 0:
                os.close(build_descriptor)
            raise
        finally:
            if parent_descriptor is not None:
                os.close(parent_descriptor)
            os.close(repo_descriptor)

    def read_layout(self, argument: str) -> bytes:
        parts = _relative_parts(self.location.repo_path, argument, "layout")
        if parts != EXPECTED_LAYOUT_PARTS:
            _fail("layout 必须是 repo 内的 config/image-layout.json")
        parent_descriptor, parent_identities = _open_parent(
            self.repo_descriptor, parts
        )
        file_descriptor = -1
        try:
            named_before = os.stat(
                parts[-1], dir_fd=parent_descriptor, follow_symlinks=False
            )
            file_descriptor = os.open(
                parts[-1], FILE_FLAGS, dir_fd=parent_descriptor
            )
            before = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size <= 0
                or before.st_size > MAX_LAYOUT_BYTES
                or _file_identity(named_before) != _file_identity(before)
            ):
                _fail("layout 必须是大小受限的单链接普通文件")
            remaining = before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(file_descriptor, min(remaining, 65536))
                if not chunk:
                    _fail("layout 读取不完整")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(file_descriptor, 1):
                _fail("layout 在读取过程中增长")
            after = os.fstat(file_descriptor)
            named_after = os.stat(
                parts[-1], dir_fd=parent_descriptor, follow_symlinks=False
            )
            if (
                _file_identity(after) != _file_identity(before)
                or _file_identity(named_after) != _file_identity(before)
            ):
                _fail("layout 在读取过程中发生变化")

            fresh_repo = self._fresh_repo()
            try:
                fresh_parent, fresh_identities = _open_parent(fresh_repo, parts)
                try:
                    if fresh_identities != parent_identities:
                        _fail("layout 父目录在读取过程中被替换")
                    fresh_status = os.stat(
                        parts[-1],
                        dir_fd=fresh_parent,
                        follow_symlinks=False,
                    )
                    if _file_identity(fresh_status) != _file_identity(before):
                        _fail("layout 名称在读取过程中被替换")
                finally:
                    os.close(fresh_parent)
            finally:
                os.close(fresh_repo)
            return b"".join(chunks)
        except OSError as error:
            _fail(f"无法安全读取 layout：{error}")
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            os.close(parent_descriptor)

    def _fresh_boot(self, expected_identity: tuple[int, int]) -> int:
        build_descriptor = self._fresh_build()
        try:
            boot_descriptor = os.open(
                EXPECTED_OUTPUT_PARTS[0], DIRECTORY_FLAGS, dir_fd=build_descriptor
            )
        finally:
            os.close(build_descriptor)
        if _identity(os.fstat(boot_descriptor)) != expected_identity:
            os.close(boot_descriptor)
            _fail("输出 boot 目录在生成过程中被替换")
        return boot_descriptor

    def write_output(self, argument: str, payload: bytes) -> None:
        parts = _relative_parts(self.location.build_path, argument, "output")
        if parts != EXPECTED_OUTPUT_PARTS:
            _fail("output 必须是 BUILD_DIR/boot/image-layout.inc")
        boot_descriptor = os.open(
            parts[0], DIRECTORY_FLAGS, dir_fd=self.build_descriptor
        )
        boot_identity = _identity(os.fstat(boot_descriptor))
        target_name = parts[1]
        temporary_name = (
            f".{target_name}.{os.getpid()}.{secrets.token_hex(12)}.tmp"
        )
        temporary_descriptor = -1
        try:
            original_target = self._target_identity(boot_descriptor, target_name)
            temporary_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=boot_descriptor,
            )
            os.fchmod(temporary_descriptor, 0o644)
            view = memoryview(payload)
            while view:
                written = os.write(temporary_descriptor, view)
                if written <= 0:
                    _fail("生成文件写入没有取得进展")
                view = view[written:]
            os.fsync(temporary_descriptor)
            expected = os.fstat(temporary_descriptor)
            if not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1:
                _fail("生成临时文件身份无效")
            expected_identity = _stable_file_identity(expected)

            fresh_boot = self._fresh_boot(boot_identity)
            try:
                if self._target_identity(fresh_boot, target_name) != original_target:
                    _fail("输出目标在提交前发生变化")
                temporary_status = os.stat(
                    temporary_name,
                    dir_fd=fresh_boot,
                    follow_symlinks=False,
                )
                if _stable_file_identity(temporary_status) != expected_identity:
                    _fail("生成临时文件在提交前被替换")
                os.replace(
                    temporary_name,
                    target_name,
                    src_dir_fd=fresh_boot,
                    dst_dir_fd=fresh_boot,
                )
            finally:
                os.close(fresh_boot)

            # DrvFS 在打开的临时文件完成 rename 后可能延迟发布新名称。
            os.close(temporary_descriptor)
            temporary_descriptor = -1
            committed_boot = self._fresh_boot(boot_identity)
            try:
                committed = os.stat(
                    target_name,
                    dir_fd=committed_boot,
                    follow_symlinks=False,
                )
                if (
                    _stable_file_identity(committed) != expected_identity
                    or not stat.S_ISREG(committed.st_mode)
                    or committed.st_nlink != 1
                ):
                    _fail("提交后的生成文件身份不匹配")
                os.fsync(committed_boot)
            finally:
                os.close(committed_boot)
        except OSError as error:
            _fail(f"无法安全原子写入 output：{error}")
        finally:
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            try:
                os.unlink(temporary_name, dir_fd=boot_descriptor)
            except FileNotFoundError:
                pass
            os.close(boot_descriptor)

    @staticmethod
    def _target_identity(
        directory_descriptor: int, name: str
    ) -> tuple[int, ...] | None:
        try:
            status = os.stat(
                name, dir_fd=directory_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            _fail("已有输出目标必须是单链接普通文件")
        return _file_identity(status)

    def close(self) -> None:
        if self.build_descriptor >= 0:
            os.close(self.build_descriptor)
            self.build_descriptor = -1
        if self.repo_descriptor >= 0:
            os.close(self.repo_descriptor)
            self.repo_descriptor = -1

    def __enter__(self) -> BoundTree:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        _fail(f"{name} 必须是整数")
    assert isinstance(value, int)
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"JSON 包含重复键：{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    _fail(f"JSON 不允许非有限数字：{value}")


def _load_stage2(raw: bytes) -> tuple[int, int]:
    try:
        text = raw.decode("utf-8", errors="strict")
        layout = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"layout 不是严格 UTF-8 JSON：{error}")

    if type(layout) is not dict:
        _fail("布局顶层必须是 object")
    assert isinstance(layout, dict)
    expected_fields = {
        "format_version",
        "sector_size",
        "image_size_bytes",
        "components",
    }
    if set(layout) != expected_fields:
        _fail("布局顶层 schema 无效")
    if _integer(layout["format_version"], "format_version") != 1:
        _fail("仅支持 format_version=1")
    if _integer(layout["sector_size"], "sector_size") != SECTOR_SIZE:
        _fail("Stage 1 仅支持 512 字节扇区")

    image_size = _integer(layout["image_size_bytes"], "image_size_bytes")
    if image_size <= 0 or image_size % SECTOR_SIZE != 0:
        _fail("image_size_bytes 必须是正的完整扇区倍数")
    image_sectors = image_size // SECTOR_SIZE

    components = layout["components"]
    if type(components) is not list:
        _fail("components 必须是数组")
    stage2_components: list[dict[str, object]] = []
    component_names: set[str] = set()
    regions: list[tuple[int, int, str]] = []
    for index, component in enumerate(components):
        if type(component) is not dict:
            _fail(f"components[{index}] 必须是 object")
        assert isinstance(component, dict)
        if set(component) != {"name", "artifact", "lba", "max_sectors"}:
            _fail(f"components[{index}] schema 无效")
        name = component["name"]
        artifact = component["artifact"]
        if type(name) is not str or not name:
            _fail(f"components[{index}].name 必须是非空字符串")
        if name in component_names:
            _fail(f"重复组件：{name}")
        component_names.add(name)
        if type(artifact) is not str or not artifact:
            _fail(f"components[{index}].artifact 必须是非空字符串")
        if (
            PurePosixPath(artifact).is_absolute()
            or PureWindowsPath(artifact).is_absolute()
            or "\\" in artifact
            or "\x00" in artifact
        ):
            _fail(f"components[{index}].artifact 必须是 POSIX 相对路径")
        artifact_parts = artifact.split("/")
        if any(part in {"", ".", ".."} for part in artifact_parts):
            _fail(f"components[{index}].artifact 含无效目录段")
        lba = _integer(component["lba"], f"components[{index}].lba")
        count = _integer(
            component["max_sectors"], f"components[{index}].max_sectors"
        )
        if lba < 0 or count <= 0 or lba + count > image_sectors:
            _fail(f"组件区域越过镜像边界：{name}")
        regions.append((lba, lba + count, name))
        if name == "stage2":
            stage2_components.append(component)
    if len(stage2_components) != 1:
        _fail("布局必须且只能包含一个 stage2 组件")
    regions.sort()
    for previous, current in zip(regions, regions[1:]):
        if current[0] < previous[1]:
            _fail(f"组件区域重叠：{previous[2]} 与 {current[2]}")

    stage2 = stage2_components[0]
    lba = _integer(stage2["lba"], "stage2.lba")
    sector_count = _integer(stage2["max_sectors"], "stage2.max_sectors")
    if not 0 <= lba <= MAX_DAP_LBA:
        _fail("stage2.lba 超出 DAP 64 位 LBA 范围")
    if not MIN_STAGE2_SECTORS <= sector_count <= MAX_STAGE2_SECTORS:
        _fail("stage2.max_sectors 必须位于 65..127")
    if lba + sector_count > MAX_DAP_LBA + 1:
        _fail("stage2 区域越过 DAP LBA 边界")

    first_count = (FIRST_DMA_BOUNDARY - STAGE2_LOAD_ADDRESS) // SECTOR_SIZE
    second_count = sector_count - first_count
    if STAGE2_LOAD_ADDRESS + first_count * SECTOR_SIZE != FIRST_DMA_BOUNDARY:
        _fail("第一个 Stage 2 DAP 未在 64 KiB DMA 边界结束")
    if not 1 <= second_count <= MAX_STAGE2_SECTORS - first_count:
        _fail("第二个 Stage 2 DAP 扇区数无效")
    if FIRST_DMA_BOUNDARY + second_count * SECTOR_SIZE > 0x20000:
        _fail("第二个 Stage 2 DAP 跨越 64 KiB DMA 边界")
    return lba, sector_count


def _render(lba: int, sector_count: int) -> bytes:
    return (
        "; Generated by tools/generate_boot_layout.py; do not edit.\n"
        f"%define STAGE2_LBA 0x{lba:016X}\n"
        f"%define STAGE2_MAX_SECTORS {sector_count}\n"
    ).encode("ascii")


def _parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    try:
        repo = os.path.abspath(options.repo)
        with BoundTree.open(repo, options.build_dir) as tree:
            raw = tree.read_layout(options.layout)
            lba, sector_count = _load_stage2(raw)
            tree.write_output(options.output, _render(lba, sector_count))
    except (LayoutError, guard.GuardError, OSError) as error:
        print(f"generate_boot_layout.py: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
