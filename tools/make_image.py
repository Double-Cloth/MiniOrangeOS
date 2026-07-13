#!/usr/bin/env python3
"""按受控布局原子生成确定性的 MiniOrangeOS 原始磁盘镜像。"""

from __future__ import annotations

import argparse
import errno
import json
import os
import secrets
import signal
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn


ROOT_FIELDS = {"format_version", "sector_size", "image_size_bytes", "components"}
COMPONENT_FIELDS = {"name", "artifact", "lba", "max_sectors"}
FORMAT_VERSION = 1
SECTOR_SIZE = 512
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024 * 1024
MAX_LAYOUT_SIZE_BYTES = 4 * 1024 * 1024
COPY_CHUNK_SIZE = 256 * 1024
DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_INTERRUPTED_SIGNAL: int | None = None


class ImageError(Exception):
    """表示可安全报告且不会覆盖目标镜像的失败。"""


@dataclass(frozen=True)
class DirectoryIdentity:
    device: int
    inode: int
    mode: int

    @classmethod
    def from_status(cls, value: os.stat_result) -> "DirectoryIdentity":
        if not stat.S_ISDIR(value.st_mode):
            _fail("路径组件不是目录")
        return cls(value.st_dev, value.st_ino, value.st_mode)


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_status(cls, value: os.stat_result) -> "FileIdentity":
        return cls(
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )


@dataclass
class DirectoryBinding:
    path: Path
    descriptor: int
    identities: tuple[DirectoryIdentity, ...]

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass
class Component:
    name: str
    descriptor: int
    identity: FileIdentity
    offset: int

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass
class Layout:
    image_size_bytes: int
    components: tuple[Component, ...]

    def close(self) -> None:
        for component in self.components:
            component.close()


def _fail(message: str) -> NoReturn:
    raise ImageError(message)


def _require_exact_object(value: object, fields: set[str], location: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{location} 必须是 object")
    assert isinstance(value, dict)
    actual = set(value)
    if actual != fields:
        _fail(
            f"{location} 字段不匹配：缺少 {sorted(fields - actual)}，"
            f"未知 {sorted(actual - fields)}"
        )
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


def _signal_numbers() -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            int(getattr(signal, name))
            for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGXFSZ")
            if hasattr(signal, name)
        )
    )


def _interrupted(signum: int, _frame: object) -> None:
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


def _path_parts(path: Path, location: str) -> tuple[bool, tuple[str, ...]]:
    raw = os.fspath(path)
    if "\x00" in raw or "\\" in raw:
        _fail(f"{location} 含有不安全路径字符")
    pure = PurePosixPath(raw)
    if PureWindowsPath(raw).is_absolute() and not pure.is_absolute():
        _fail(f"{location} 不得使用 Windows 绝对路径")
    parts = list(pure.parts)
    absolute = pure.is_absolute()
    if absolute and parts and parts[0] in {"/", "//"}:
        parts.pop(0)
    if any(part in {"", ".", ".."} for part in parts):
        _fail(f"{location} 含有空、当前目录或父目录段")
    return absolute, tuple(parts)


def _open_directory_path(path: Path, location: str) -> DirectoryBinding:
    absolute, parts = _path_parts(path, location)
    descriptor = os.open("/" if absolute else ".", DIRECTORY_FLAGS)
    identities: list[DirectoryIdentity] = []
    try:
        identities.append(DirectoryIdentity.from_status(os.fstat(descriptor)))
        for part in parts:
            next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            identities.append(DirectoryIdentity.from_status(os.fstat(descriptor)))
        return DirectoryBinding(path, descriptor, tuple(identities))
    except BaseException:
        os.close(descriptor)
        raise


def _open_relative_directories(
    base_descriptor: int,
    parts: tuple[str, ...],
    location: str,
) -> DirectoryBinding:
    descriptor = os.dup(base_descriptor)
    os.set_inheritable(descriptor, False)
    identities: list[DirectoryIdentity] = []
    try:
        identities.append(DirectoryIdentity.from_status(os.fstat(descriptor)))
        for part in parts:
            next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            identities.append(DirectoryIdentity.from_status(os.fstat(descriptor)))
        return DirectoryBinding(Path("."), descriptor, tuple(identities))
    except BaseException as error:
        os.close(descriptor)
        if isinstance(error, ImageError):
            raise
        _fail(f"{location} 无法安全打开：{error}")


def _reopen_directory(binding: DirectoryBinding, location: str) -> DirectoryBinding:
    try:
        current = _open_directory_path(binding.path, location)
    except OSError as error:
        _fail(f"{location} 当前路径无法安全重开：{error}")
    if current.identities != binding.identities:
        current.close()
        _fail(f"{location} 在验证后被替换")
    return current


def _parent_path_and_name(path: Path, location: str) -> tuple[Path, str]:
    absolute, parts = _path_parts(path, location)
    if not parts:
        _fail(f"{location} 必须指向文件")
    name = parts[-1]
    parent_parts = parts[:-1]
    if absolute:
        parent = Path("/").joinpath(*parent_parts)
    else:
        parent = Path(".").joinpath(*parent_parts)
    return parent, name


def _stat_regular(
    parent_descriptor: int,
    name: str,
    location: str,
    *,
    single_link: bool,
) -> FileIdentity:
    try:
        status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        _fail(f"{location} 不可访问：{error}")
    if not stat.S_ISREG(status.st_mode):
        _fail(f"{location} 必须是非符号链接的普通文件")
    if single_link and status.st_nlink != 1:
        _fail(f"{location} 必须只有一个硬链接")
    return FileIdentity.from_status(status)


def _open_checked_file(
    parent_descriptor: int,
    name: str,
    expected: FileIdentity,
    location: str,
) -> int:
    try:
        descriptor = os.open(name, FILE_FLAGS, dir_fd=parent_descriptor)
    except OSError as error:
        _fail(f"{location} 无法安全打开：{error}")
    if FileIdentity.from_status(os.fstat(descriptor)) != expected:
        os.close(descriptor)
        _fail(f"{location} 在验证后被替换")
    return descriptor


def _read_layout_json(path: Path) -> object:
    parent_path, name = _parent_path_and_name(path, "--layout")
    parent = _open_directory_path(parent_path, "布局父目录")
    descriptor = -1
    try:
        expected = _stat_regular(parent.descriptor, name, "布局文件", single_link=True)
        if expected.size <= 0 or expected.size > MAX_LAYOUT_SIZE_BYTES:
            _fail("布局文件大小不合理")
        descriptor = _open_checked_file(parent.descriptor, name, expected, "布局文件")
        chunks: list[bytes] = []
        offset = 0
        while offset < expected.size:
            chunk = os.pread(descriptor, min(COPY_CHUNK_SIZE, expected.size - offset), offset)
            if not chunk:
                _fail("布局文件在读取过程中被截断")
            chunks.append(chunk)
            offset += len(chunk)
        if FileIdentity.from_status(os.fstat(descriptor)) != expected:
            _fail("布局文件在读取过程中发生变化")
        current_parent = _reopen_directory(parent, "布局父目录")
        try:
            if _stat_regular(current_parent.descriptor, name, "布局文件", single_link=True) != expected:
                _fail("布局文件路径在读取过程中被替换")
        finally:
            current_parent.close()
        raw = b"".join(chunks)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        parent.close()
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
    if posix_path.is_absolute() or PureWindowsPath(value).is_absolute():
        _fail(f"{location} 必须是相对 BUILD_DIR 的路径")
    if "\\" in value:
        _fail(f"{location} 必须使用 POSIX 路径分隔符")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail(f"{location} 含有空、当前目录或父目录段")
    return tuple(parts)


def _test_hook(stage: str) -> None:
    if os.environ.get("MINIOS_TEST_MODE") != "1":
        return
    if os.environ.get("MINIOS_IMAGE_TEST_HOOK") != stage:
        return
    ready = Path(os.environ["MINIOS_TEST_HOOK_READY"])
    proceed = Path(os.environ["MINIOS_TEST_HOOK_CONTINUE"])
    log = Path(os.environ["MINIOS_TEST_HOOK_LOG"])
    with log.open("a", encoding="utf-8") as stream:
        stream.write(stage + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    ready.write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not proceed.is_file():
        _raise_if_interrupted()
        if time.monotonic() >= deadline:
            _fail(f"测试 hook 等待超时：{stage}")
        time.sleep(0.01)


def _cleanup_test_hook(stage: str, temporary_name: str) -> None:
    if os.environ.get("MINIOS_TEST_MODE") != "1":
        return
    if os.environ.get("MINIOS_IMAGE_CLEANUP_TEST_HOOK") != stage:
        return
    ready = Path(os.environ["MINIOS_IMAGE_CLEANUP_TEST_HOOK_READY"])
    proceed = Path(os.environ["MINIOS_IMAGE_CLEANUP_TEST_HOOK_CONTINUE"])
    log = Path(os.environ["MINIOS_IMAGE_CLEANUP_TEST_HOOK_LOG"])
    name_file = Path(os.environ["MINIOS_IMAGE_CLEANUP_TEST_TEMP_NAME_FILE"])
    with log.open("a", encoding="utf-8") as stream:
        stream.write(stage + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    name_file.write_text(temporary_name + "\n", encoding="utf-8")
    ready.write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not proceed.is_file():
        _raise_if_interrupted()
        if time.monotonic() >= deadline:
            _fail(f"测试 hook 等待超时：{stage}")
        time.sleep(0.01)


def _open_artifact(
    build: DirectoryBinding,
    name: str,
    artifact: str,
    max_size: int,
    offset: int,
    index: int,
) -> Component:
    parts = _artifact_parts(artifact, f"components[{index}].artifact")
    parent_parts, final_name = parts[:-1], parts[-1]
    initial_parent = _open_relative_directories(
        build.descriptor, parent_parts, f"组件 {name} 父目录"
    )
    current_build: DirectoryBinding | None = None
    current_parent: DirectoryBinding | None = None
    descriptor = -1
    try:
        expected = _stat_regular(
            initial_parent.descriptor,
            final_name,
            f"组件 {name}",
            single_link=True,
        )
        if expected.size <= 0 or expected.size > max_size:
            _fail(f"组件 {name} 大小 {expected.size} 不在 1..{max_size} 范围")
        if name == "stage1" and expected.size != SECTOR_SIZE:
            _fail(f"stage1 必须恰好为一个扇区（{SECTOR_SIZE} 字节）")

        _test_hook(f"artifact-after-validation-before-open:{name}")
        current_build = _reopen_directory(build, "BUILD_DIR")
        current_parent = _open_relative_directories(
            current_build.descriptor, parent_parts, f"组件 {name} 当前父目录"
        )
        if current_parent.identities != initial_parent.identities:
            _fail(f"组件 {name} 的父目录在验证后被替换")
        current = _stat_regular(
            current_parent.descriptor,
            final_name,
            f"组件 {name}",
            single_link=True,
        )
        if current != expected:
            _fail(f"组件 {name} 在验证后被替换")
        descriptor = _open_checked_file(
            current_parent.descriptor, final_name, expected, f"组件 {name}"
        )
        return Component(name, descriptor, expected, offset)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        if current_parent is not None:
            current_parent.close()
        if current_build is not None:
            current_build.close()
        initial_parent.close()


def _load_layout(layout_path: Path, build_path: Path) -> Layout:
    root = _require_exact_object(_read_layout_json(layout_path), ROOT_FIELDS, "布局顶层")
    version = _require_int(root["format_version"], "format_version")
    if version != FORMAT_VERSION:
        _fail(f"不支持 format_version={version}")
    sector_size = _require_int(root["sector_size"], "sector_size")
    if sector_size != SECTOR_SIZE:
        _fail(f"不支持 sector_size={sector_size}，当前格式固定为 {SECTOR_SIZE}")
    image_size = _require_int(root["image_size_bytes"], "image_size_bytes")
    if image_size <= 0 or image_size % sector_size:
        _fail("image_size_bytes 必须为正数且是 sector_size 的整数倍")
    if image_size > MAX_IMAGE_SIZE_BYTES:
        _fail(f"image_size_bytes 超过安全上限 {MAX_IMAGE_SIZE_BYTES}")
    values = root["components"]
    if type(values) is not list or not values:
        _fail("components 必须是非空 array")
    assert isinstance(values, list)

    names: set[str] = set()
    regions: list[tuple[int, int, str]] = []
    pending: list[tuple[str, str, int, int, int]] = []
    image_sectors = image_size // sector_size
    for index, raw in enumerate(values):
        location = f"components[{index}]"
        value = _require_exact_object(raw, COMPONENT_FIELDS, location)
        name = _require_nonempty_string(value["name"], f"{location}.name")
        if not name.strip() or name in names:
            _fail(f"组件名称为空或重复：{name!r}")
        names.add(name)
        artifact = _require_nonempty_string(value["artifact"], f"{location}.artifact")
        _artifact_parts(artifact, f"{location}.artifact")
        lba = _require_int(value["lba"], f"{location}.lba")
        max_sectors = _require_int(value["max_sectors"], f"{location}.max_sectors")
        if lba < 0 or max_sectors <= 0:
            _fail(f"{location} 的 lba/max_sectors 边界无效")
        end = lba + max_sectors
        if end > image_sectors:
            _fail(f"组件 {name} 的保留区域越过镜像边界")
        regions.append((lba, end, name))
        pending.append((name, artifact, lba * sector_size, max_sectors * sector_size, index))
    regions.sort()
    for previous, current in zip(regions, regions[1:]):
        if current[0] < previous[1]:
            _fail(f"组件保留区域重叠：{previous[2]} 与 {current[2]}")

    try:
        build = _open_directory_path(build_path, "BUILD_DIR")
    except OSError as error:
        _fail(f"BUILD_DIR 无法安全打开：{error}")
    components: list[Component] = []
    try:
        for name, artifact, offset, max_size, index in pending:
            components.append(
                _open_artifact(build, name, artifact, max_size, offset, index)
            )
        return Layout(image_size, tuple(components))
    except BaseException:
        for component in components:
            component.close()
        raise
    finally:
        build.close()


def _write_all_at(descriptor: int, payload: bytes, offset: int) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(view):
        _raise_if_interrupted()
        count = os.pwrite(descriptor, view[written:], offset + written)
        if count <= 0:
            _fail("镜像组件写入没有取得进展")
        written += count


def _copy_range(source: int, target: int, source_start: int, source_end: int, target_start: int) -> None:
    position = source_start
    while position < source_end:
        _raise_if_interrupted()
        chunk = os.pread(source, min(COPY_CHUNK_SIZE, source_end - position), position)
        if not chunk:
            _fail("组件在复制过程中被截断")
        _write_all_at(target, chunk, target_start + position)
        position += len(chunk)


def _copy_component(component: Component, target: int) -> None:
    if FileIdentity.from_status(os.fstat(component.descriptor)) != component.identity:
        _fail(f"组件 {component.name} 在复制前发生变化")
    size = component.identity.size
    seek_data = getattr(os, "SEEK_DATA", None)
    seek_hole = getattr(os, "SEEK_HOLE", None)
    sparse_supported = seek_data is not None and seek_hole is not None
    position = 0
    if sparse_supported:
        while position < size:
            try:
                data_start = os.lseek(component.descriptor, position, seek_data)
            except OSError as error:
                if error.errno == errno.ENXIO:
                    break
                if error.errno in {errno.EINVAL, errno.ENOTSUP, errno.ENOSYS}:
                    sparse_supported = False
                    break
                raise
            try:
                data_end = min(os.lseek(component.descriptor, data_start, seek_hole), size)
            except OSError as error:
                if error.errno in {errno.EINVAL, errno.ENOTSUP, errno.ENOSYS}:
                    sparse_supported = False
                    break
                raise
            _copy_range(
                component.descriptor,
                target,
                data_start,
                data_end,
                component.offset,
            )
            position = data_end
    if not sparse_supported:
        _copy_range(component.descriptor, target, 0, size, component.offset)
    if FileIdentity.from_status(os.fstat(component.descriptor)) != component.identity:
        _fail(f"组件 {component.name} 在复制过程中发生变化")


def _output_status(parent_descriptor: int, name: str) -> FileIdentity | None:
    try:
        status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(status.st_mode):
        if stat.S_ISDIR(status.st_mode):
            _fail("输出目标不能是目录")
        _fail("已有输出目标必须是非符号链接的普通文件")
    return FileIdentity.from_status(status)


def _unlink_from_bound_parent(parent: DirectoryBinding, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent.descriptor)
        return
    except FileNotFoundError:
        pass
    except OSError:
        pass
    _cleanup_test_hook("cleanup-after-bound-unlink-failed-before-return", name)
    # DrvFS 会把 rename 后的目录 fd 重新解释为同名 replacement。任何重定位后删除
    # 都可能作用于外来目录，因此只保留随机临时文件并失败关闭。
    return


def _cleanup_temporary(
    parent: DirectoryBinding,
    descriptor: int | None,
    name: str | None,
) -> None:
    previous: dict[int, signal.Handlers] = {}
    for number in _signal_numbers():
        previous[number] = signal.getsignal(number)
        signal.signal(number, signal.SIG_IGN)
    try:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if name is not None:
            _unlink_from_bound_parent(parent, name)
    finally:
        _restore_signal_handlers(previous)


def _commit(parent: int, temporary: str, output: str) -> None:
    previous: dict[int, signal.Handlers] = {}
    for number in _signal_numbers():
        previous[number] = signal.getsignal(number)
        signal.signal(number, signal.SIG_IGN)
    try:
        os.replace(temporary, output, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        _restore_signal_handlers(previous)


def _generate(layout: Layout, output_path: Path) -> None:
    parent_path, output_name = _parent_path_and_name(output_path, "--output")
    try:
        parent = _open_directory_path(parent_path, "输出父目录")
    except OSError as error:
        _fail(f"输出父目录无法安全打开：{error}")
    temporary_name: str | None = None
    temporary_descriptor: int | None = None
    try:
        original = _output_status(parent.descriptor, output_name)
        for component in layout.components:
            if original is not None and (
                original.device == component.identity.device
                and original.inode == component.identity.inode
            ):
                _fail("输出目标不得与输入组件互为硬链接")

        _test_hook("output-parent-after-validation-before-open")
        current_parent = _reopen_directory(parent, "输出父目录")
        current_parent.close()

        for _attempt in range(128):
            candidate = f".{output_name}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            try:
                temporary_descriptor = os.open(
                    candidate, flags, 0o600, dir_fd=parent.descriptor
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
            _copy_component(component, temporary_descriptor)
        os.fchmod(temporary_descriptor, 0o644)
        os.fsync(temporary_descriptor)
        _raise_if_interrupted()
        os.close(temporary_descriptor)
        temporary_descriptor = None

        if _output_status(parent.descriptor, output_name) != original:
            _fail("输出目标在生成过程中发生变化")
        _test_hook("output-after-validation-before-commit")
        if _output_status(parent.descriptor, output_name) != original:
            _fail("输出目标在提交前发生变化")
        current_parent = _reopen_directory(parent, "输出父目录")
        current_parent.close()
        _commit(parent.descriptor, temporary_name, output_name)
        temporary_name = None
    finally:
        _cleanup_temporary(parent, temporary_descriptor, temporary_name)
        parent.close()


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    previous_handlers = _install_signal_handlers()
    layout: Layout | None = None
    try:
        layout = _load_layout(options.layout, options.build_dir)
        _raise_if_interrupted()
        _generate(layout, options.output)
    except (ImageError, OSError, MemoryError) as error:
        print(f"make_image.py: error: {error}", file=sys.stderr)
        return 1
    finally:
        if layout is not None:
            layout.close()
        _restore_signal_handlers(previous_handlers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
