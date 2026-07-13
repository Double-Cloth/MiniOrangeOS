#!/usr/bin/env python3
"""按受控布局原子生成确定性的 MiniOrangeOS 原始磁盘镜像。"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn


ROOT_FIELDS = {"format_version", "sector_size", "image_size_bytes", "components"}
COMPONENT_FIELDS = {"name", "artifact", "lba", "max_sectors"}
FORMAT_VERSION = 1
SECTOR_SIZE = 512
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024 * 1024
COPY_CHUNK_SIZE = 1024 * 1024
_INTERRUPTED_SIGNAL: int | None = None


class ImageError(Exception):
    """表示可向调用者报告且不会覆盖目标镜像的失败。"""


@dataclass(frozen=True)
class Component:
    """已完成全部校验并读入内存的镜像组件。"""

    name: str
    path: Path
    offset: int
    payload: bytes


@dataclass(frozen=True)
class Layout:
    """已验证的镜像布局。"""

    image_size_bytes: int
    components: tuple[Component, ...]


def _fail(message: str) -> NoReturn:
    raise ImageError(message)


def _require_exact_object(value: object, fields: set[str], location: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{location} 必须是 object")
    assert isinstance(value, dict)
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        _fail(f"{location} 字段不匹配：缺少 {missing}，未知 {unknown}")
    return value


def _require_int(value: object, location: str) -> int:
    if type(value) is not int:
        _fail(f"{location} 必须是 integer，且不能是 boolean")
    assert isinstance(value, int)
    return value


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        _fail(f"{location} 必须是非空 string")
    assert isinstance(value, str)
    if "\x00" in value:
        _fail(f"{location} 不得包含 NUL")
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            _fail(f"JSON object 包含重复字段：{key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> NoReturn:
    _fail(f"JSON 不得包含非标准数值：{value}")


def _load_json(path: Path) -> object:
    try:
        raw = path.read_bytes()
    except OSError as error:
        _fail(f"无法读取布局文件 {path}：{error}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail(f"布局文件不是有效 UTF-8：{error}")
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        _fail(f"布局文件不是有效 JSON：{error}")


def _artifact_parts(value: str, location: str) -> tuple[str, ...]:
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute():
        _fail(f"{location} 必须是相对 BUILD_DIR 的路径")
    if "\\" in value:
        _fail(f"{location} 必须使用 POSIX 路径分隔符")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        _fail(f"{location} 含有空、当前目录或父目录段")
    return tuple(raw_parts)


def _read_artifact(
    build_dir: Path,
    relative_path: str,
    max_size: int,
    location: str,
) -> tuple[Path, bytes]:
    parts = _artifact_parts(relative_path, location)
    lexical_path = build_dir.joinpath(*parts)
    try:
        lexical_status = lexical_path.lstat()
    except OSError as error:
        _fail(f"{location} 不可访问：{error}")
    if stat.S_ISLNK(lexical_status.st_mode):
        _fail(f"{location} 不得是符号链接：{relative_path}")

    try:
        resolved_path = lexical_path.resolve(strict=True)
        resolved_path.relative_to(build_dir)
    except (OSError, ValueError) as error:
        _fail(f"{location} 解析后逃逸 BUILD_DIR 或不可访问：{error}")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved_path, flags)
    except OSError as error:
        _fail(f"{location} 无法安全打开：{error}")

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{location} 必须是普通文件")
        if before.st_nlink != 1:
            _fail(f"{location} 必须只有一个硬链接")
        if before.st_size <= 0:
            _fail(f"{location} 不能为空")
        if before.st_size > max_size:
            _fail(f"{location} 大小 {before.st_size} 超过上限 {max_size}")

        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            _raise_if_interrupted()
            chunk = os.read(descriptor, min(COPY_CHUNK_SIZE, remaining))
            if not chunk:
                _fail(f"{location} 在读取过程中被截断")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail(f"{location} 在读取过程中增长")
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_identity != after_identity:
            _fail(f"{location} 在读取过程中发生变化")
        return resolved_path, b"".join(chunks)
    finally:
        os.close(descriptor)


def _load_layout(layout_path: Path, build_dir_argument: Path) -> Layout:
    try:
        build_dir = build_dir_argument.resolve(strict=True)
    except OSError as error:
        _fail(f"BUILD_DIR 不可访问：{error}")
    if not build_dir.is_dir():
        _fail(f"BUILD_DIR 不是目录：{build_dir}")

    root = _require_exact_object(_load_json(layout_path), ROOT_FIELDS, "布局顶层")
    format_version = _require_int(root["format_version"], "format_version")
    if format_version != FORMAT_VERSION:
        _fail(f"不支持 format_version={format_version}")
    sector_size = _require_int(root["sector_size"], "sector_size")
    if sector_size != SECTOR_SIZE:
        _fail(f"不支持 sector_size={sector_size}，当前格式固定为 {SECTOR_SIZE}")
    image_size = _require_int(root["image_size_bytes"], "image_size_bytes")
    if image_size <= 0 or image_size % sector_size:
        _fail("image_size_bytes 必须为正数且是 sector_size 的整数倍")
    if image_size > MAX_IMAGE_SIZE_BYTES:
        _fail(f"image_size_bytes 超过安全上限 {MAX_IMAGE_SIZE_BYTES}")

    raw_components = root["components"]
    if type(raw_components) is not list or not raw_components:
        _fail("components 必须是非空 array")
    assert isinstance(raw_components, list)

    image_sectors = image_size // sector_size
    names: set[str] = set()
    regions: list[tuple[int, int, str]] = []
    pending: list[tuple[str, str, int, int]] = []
    for index, raw_component in enumerate(raw_components):
        location = f"components[{index}]"
        component = _require_exact_object(raw_component, COMPONENT_FIELDS, location)
        name = _require_nonempty_string(component["name"], f"{location}.name")
        if not name.strip():
            _fail(f"{location}.name 不得只包含空白")
        if name in names:
            _fail(f"组件名称重复：{name}")
        names.add(name)
        artifact = _require_nonempty_string(
            component["artifact"], f"{location}.artifact"
        )
        _artifact_parts(artifact, f"{location}.artifact")
        lba = _require_int(component["lba"], f"{location}.lba")
        max_sectors = _require_int(
            component["max_sectors"], f"{location}.max_sectors"
        )
        if lba < 0:
            _fail(f"{location}.lba 不得为负数")
        if max_sectors <= 0:
            _fail(f"{location}.max_sectors 必须为正数")
        end = lba + max_sectors
        if end > image_sectors:
            _fail(f"组件 {name} 的保留区域越过镜像边界")
        regions.append((lba, end, name))
        pending.append((name, artifact, lba, max_sectors))

    regions.sort()
    for previous, current in zip(regions, regions[1:]):
        if current[0] < previous[1]:
            _fail(f"组件保留区域重叠：{previous[2]} 与 {current[2]}")

    loaded: list[Component] = []
    for index, (name, artifact, lba, max_sectors) in enumerate(pending):
        path, payload = _read_artifact(
            build_dir,
            artifact,
            max_sectors * sector_size,
            f"components[{index}].artifact",
        )
        if name == "stage1" and len(payload) != sector_size:
            _fail(f"stage1 必须恰好为一个扇区（{sector_size} 字节）")
        loaded.append(Component(name, path, lba * sector_size, payload))
    return Layout(image_size, tuple(loaded))


def _status_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _write_all_at(descriptor: int, payload: bytes, offset: int) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(view):
        _raise_if_interrupted()
        try:
            count = os.pwrite(descriptor, view[written:], offset + written)
        except InterruptedError:
            continue
        if count <= 0:
            _fail("镜像组件写入没有取得进展")
        written += count


def _signal_numbers() -> tuple[int, ...]:
    names = ("SIGINT", "SIGTERM", "SIGHUP", "SIGXFSZ")
    return tuple(
        dict.fromkeys(
            int(getattr(signal, name)) for name in names if hasattr(signal, name)
        )
    )


def _interrupted(signum: int, _frame: object) -> None:
    # 处理器只记录状态，避免在异常展开的 finally 内再次抛出并跳过临时文件清理。
    global _INTERRUPTED_SIGNAL
    if _INTERRUPTED_SIGNAL is None:
        _INTERRUPTED_SIGNAL = signum


def _raise_if_interrupted() -> None:
    if _INTERRUPTED_SIGNAL is None:
        return
    try:
        name = signal.Signals(_INTERRUPTED_SIGNAL).name
    except ValueError:
        name = str(_INTERRUPTED_SIGNAL)
    _fail(f"收到信号 {name}，已取消镜像生成")


def _install_signal_handlers() -> dict[int, signal.Handlers]:
    global _INTERRUPTED_SIGNAL
    _INTERRUPTED_SIGNAL = None
    previous: dict[int, signal.Handlers] = {}
    for number in _signal_numbers():
        previous[number] = signal.getsignal(number)
        signal.signal(number, _interrupted)
    return previous


def _restore_signal_handlers(previous: dict[int, signal.Handlers]) -> None:
    for number, handler in previous.items():
        signal.signal(number, handler)


def _commit_without_interrupts(
    directory_descriptor: int,
    temporary_name: str,
    output_name: str,
) -> None:
    previous: dict[int, signal.Handlers] = {}
    for number in _signal_numbers():
        previous[number] = signal.getsignal(number)
        signal.signal(number, signal.SIG_IGN)
    try:
        os.replace(
            temporary_name,
            output_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    finally:
        _restore_signal_handlers(previous)


def _cleanup_temporary(
    directory_descriptor: int,
    temporary_descriptor: int | None,
    temporary_name: str | None,
) -> None:
    """清理阶段忽略第二个终止信号，确保 DrvFS 句柄先关闭再删除。"""

    previous: dict[int, signal.Handlers] = {}
    for number in _signal_numbers():
        previous[number] = signal.getsignal(number)
        signal.signal(number, signal.SIG_IGN)
    try:
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except OSError:
                pass
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
    finally:
        _restore_signal_handlers(previous)


def _generate(layout: Layout, output_argument: Path) -> None:
    if output_argument.name in {"", ".", ".."}:
        _fail("--output 必须指向文件名")
    output_parent_argument = output_argument.parent
    try:
        canonical_parent = output_parent_argument.resolve(strict=True)
    except OSError as error:
        _fail(f"输出目录不可访问：{error}")
    if not canonical_parent.is_dir():
        _fail(f"输出父路径不是目录：{output_parent_argument}")

    # 输出父目录不能通过符号链接重定向，目录 fd 用于约束临时文件和替换目标。
    lexical_parent = Path(os.path.abspath(output_parent_argument))
    if lexical_parent != canonical_parent:
        _fail("输出父目录不得包含符号链接或不规范路径段")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_descriptor = os.open(canonical_parent, directory_flags)
    except OSError as error:
        _fail(f"无法安全打开输出目录：{error}")

    output_name = output_argument.name
    temporary_name: str | None = None
    temporary_descriptor: int | None = None
    try:
        try:
            original_status = os.stat(
                output_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            original_status = None
        except OSError as error:
            _fail(f"无法检查输出目标：{error}")
        if original_status is not None and not stat.S_ISREG(original_status.st_mode):
            if stat.S_ISDIR(original_status.st_mode):
                _fail("输出目标不能是目录")
            _fail("已有输出目标必须是非符号链接的普通文件")

        output_path = canonical_parent / output_name
        for component in layout.components:
            if output_path == component.path:
                _fail("输出目标不得覆盖输入组件")
            if (
                original_status is not None
                and original_status.st_dev == component.path.stat().st_dev
                and original_status.st_ino == component.path.stat().st_ino
            ):
                _fail("输出目标不得与输入组件互为硬链接")

        for _attempt in range(128):
            candidate = f".{output_name}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_CLOEXEC", 0)
            try:
                temporary_descriptor = os.open(
                    candidate,
                    flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if temporary_descriptor is None or temporary_name is None:
            _fail("无法创建唯一的同目录临时文件")

        os.ftruncate(temporary_descriptor, layout.image_size_bytes)
        _raise_if_interrupted()
        for component in layout.components:
            _write_all_at(temporary_descriptor, component.payload, component.offset)
        _raise_if_interrupted()
        os.fchmod(temporary_descriptor, 0o644)
        os.fsync(temporary_descriptor)
        _raise_if_interrupted()
        os.close(temporary_descriptor)
        temporary_descriptor = None

        try:
            current_status = os.stat(
                output_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            current_status = None
        if (original_status is None) != (current_status is None):
            _fail("输出目标在生成过程中发生变化")
        if original_status is not None and current_status is not None:
            if _status_identity(original_status) != _status_identity(current_status):
                _fail("输出目标在生成过程中发生变化")

        _commit_without_interrupts(directory_descriptor, temporary_name, output_name)
        temporary_name = None
    finally:
        _cleanup_temporary(
            directory_descriptor,
            temporary_descriptor,
            temporary_name,
        )
        os.close(directory_descriptor)


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    previous_handlers = _install_signal_handlers()
    try:
        layout = _load_layout(options.layout, options.build_dir)
        _raise_if_interrupted()
        _generate(layout, options.output)
    except (ImageError, OSError) as error:
        print(f"make_image.py: error: {error}", file=sys.stderr)
        return 1
    finally:
        _restore_signal_handlers(previous_handlers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
