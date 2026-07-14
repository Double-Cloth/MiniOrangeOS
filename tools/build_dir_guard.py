#!/usr/bin/env python3
"""安全创建并清理 MiniOrangeOS 专属构建目录。"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn


MARKER = ".miniorangeos-build-root"
MARKER_SCHEMA = 1
BUILD_IDENTITY_STABILIZE_SECONDS = 1.0
MARKER_FIELDS = {
    "schema",
    "repo_path",
    "repo_dev",
    "repo_ino",
    "build_path",
    "build_dev",
    "build_ino",
}
RESERVED_TOP_LEVEL = {
    ".cache",
    ".git",
    ".superpowers",
    "boot",
    "ci",
    "config",
    "docs",
    "environment",
    "include",
    "kernel",
    "lib",
    "scripts",
    "tests",
    "tools",
    "user",
}
BUILD_SUBDIRECTORIES = (
    ("boot",),
    ("boot", "stage2"),
    ("kernel",),
    ("kernel", "arch"),
    ("kernel", "arch", "x86"),
    ("kernel", "block"),
    ("kernel", "core"),
    ("kernel", "drivers"),
    ("kernel", "mm"),
    ("kernel", "proc"),
    ("user",),
    ("user", "bin"),
    ("user", "crt"),
    ("user", "libc"),
    ("user", "programs"),
)
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
DIRECTORY_FLAGS |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
FILE_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
FILE_FLAGS |= getattr(os, "O_NOFOLLOW", 0)


class GuardError(Exception):
    """表示必须保持失败关闭的构建目录边界错误。"""


@dataclass(frozen=True)
class Location:
    repo_path: str
    build_path: str
    relative_parts: tuple[str, ...]


def _fail(message: str) -> NoReturn:
    raise GuardError(message)


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _stable_created_status(
    parent_descriptor: int, name: str
) -> tuple[int, os.stat_result]:
    """等待 DrvFS 为新目录发布稳定且非零的文件身份。"""

    deadline = time.monotonic() + BUILD_IDENTITY_STABILIZE_SECONDS
    previous: tuple[int, int] | None = None
    while True:
        probe = _open_named_directory(parent_descriptor, name)
        status = os.fstat(probe)
        identity = _identity(status)
        if status.st_ino != 0 and identity == previous:
            return probe, status
        os.close(probe)
        previous = identity if status.st_ino != 0 else None
        if time.monotonic() >= deadline:
            _fail("DrvFS 未及时发布稳定的 BUILD_DIR inode")
        time.sleep(0.01)


def _fd_path(descriptor: int) -> str:
    try:
        value = os.readlink(f"/proc/self/fd/{descriptor}")
    except OSError as error:
        _fail(f"无法核对目录文件描述符：{error}")
    suffix = " (deleted)"
    if value.endswith(suffix):
        value = value[: -len(suffix)]
    return os.path.normpath(value)


def _open_absolute_directory(path: str) -> int:
    if not os.path.isabs(path):
        _fail(f"目录必须是绝对路径：{path}")
    descriptor = os.open("/", DIRECTORY_FLAGS)
    try:
        for part in Path(path).parts[1:]:
            next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if _fd_path(descriptor) != path:
            _fail(f"目录包含符号链接或发生替换：{path}")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_arguments(repo_argument: str, build_argument: str) -> Location:
    if not repo_argument or not build_argument:
        _fail("repo 和 BUILD_DIR 均不得为空")
    if any(character.isspace() for character in repo_argument + build_argument):
        _fail("含空格路径不支持")
    if "\x00" in repo_argument or "\x00" in build_argument:
        _fail("路径不得包含 NUL")
    if "\\" in build_argument:
        _fail("BUILD_DIR 必须使用 POSIX 路径分隔符")
    raw_segments = build_argument.split("/")
    if any(segment in {".", ".."} for segment in raw_segments):
        _fail("BUILD_DIR 不得包含当前目录或父目录段")

    repo_path = os.path.abspath(repo_argument)
    if repo_path != repo_argument or os.path.normpath(repo_argument) != repo_argument:
        _fail("repo 必须是规范绝对路径")
    if os.path.isabs(build_argument):
        build_path = os.path.normpath(build_argument)
    else:
        build_path = os.path.normpath(os.path.join(repo_path, build_argument))
    try:
        common = os.path.commonpath((repo_path, build_path))
    except ValueError as error:
        _fail(f"无法比较 repo 与 BUILD_DIR：{error}")
    if common != repo_path or build_path == repo_path:
        _fail("BUILD_DIR 必须是仓库内部的非根目录")

    relative = os.path.relpath(build_path, repo_path)
    parts = tuple(relative.split(os.sep))
    if not parts or parts[0] in RESERVED_TOP_LEVEL:
        _fail(f"BUILD_DIR 使用了源码保留目录：{parts[0] if parts else relative}")
    return Location(repo_path, build_path, parts)


def _open_repo(location: Location) -> int:
    descriptor = _open_absolute_directory(location.repo_path)
    status = os.fstat(descriptor)
    if not stat.S_ISDIR(status.st_mode):
        os.close(descriptor)
        _fail("repo 不是目录")
    return descriptor


def _open_parent(repo_descriptor: int, location: Location) -> tuple[int | None, str]:
    descriptor = os.dup(repo_descriptor)
    try:
        for part in location.relative_parts[:-1]:
            try:
                next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                os.close(descriptor)
                return None, location.relative_parts[-1]
            os.close(descriptor)
            descriptor = next_descriptor
        expected = os.path.dirname(location.build_path)
        if _fd_path(descriptor) != expected:
            _fail("BUILD_DIR 的中间目录包含符号链接或发生替换")
        return descriptor, location.relative_parts[-1]
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _marker_value(
    location: Location, repo_status: os.stat_result, build_status: os.stat_result
) -> dict[str, int | str]:
    return {
        "schema": MARKER_SCHEMA,
        "repo_path": location.repo_path,
        "repo_dev": repo_status.st_dev,
        "repo_ino": repo_status.st_ino,
        "build_path": location.build_path,
        "build_dev": build_status.st_dev,
        "build_ino": build_status.st_ino,
    }


def _write_marker(
    build_descriptor: int,
    location: Location,
    repo_status: os.stat_result,
    build_status: os.stat_result,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(MARKER, flags, 0o600, dir_fd=build_descriptor)
    try:
        os.fchmod(descriptor, 0o600)
        payload = (
            json.dumps(
                _marker_value(location, repo_status, build_status),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("构建目录归属标记写入没有取得进展")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_marker(build_descriptor: int) -> dict[str, object]:
    try:
        descriptor = os.open(MARKER, FILE_FLAGS, dir_fd=build_descriptor)
    except FileNotFoundError:
        _fail("已有 BUILD_DIR 缺少可信归属标记")
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            _fail("BUILD_DIR 归属标记必须是单链接普通文件")
        if stat.S_IMODE(status.st_mode) != 0o600 or status.st_size > 4096:
            _fail("BUILD_DIR 归属标记权限或大小无效")
        chunks: list[bytes] = []
        remaining = status.st_size
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                _fail("BUILD_DIR 归属标记读取不完整")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail("BUILD_DIR 归属标记在读取过程中增长")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"BUILD_DIR 归属标记无效：{error}")
    if type(value) is not dict or set(value) != MARKER_FIELDS:
        _fail("BUILD_DIR 归属标记 schema 无效")
    assert isinstance(value, dict)
    return value


def _validate_marker(
    build_descriptor: int,
    location: Location,
    repo_status: os.stat_result,
    build_status: os.stat_result,
) -> None:
    actual = _read_marker(build_descriptor)
    expected = _marker_value(location, repo_status, build_status)
    if actual == expected:
        return

    # DrvFS 的 st_dev 会在 WSL 重新挂载后变化，但同一 Windows 文件的 st_ino
    # 和规范路径保持稳定。只允许 repo/build 两个设备号同步重基；任何路径、
    # inode、schema 或单边设备号变化仍视为外来替换。
    stable_fields = MARKER_FIELDS - {"repo_dev", "build_dev"}
    stable_identity = all(actual[field] == expected[field] for field in stable_fields)
    previous_devices_match = (
        type(actual["repo_dev"]) is int
        and type(actual["build_dev"]) is int
        and actual["repo_dev"] == actual["build_dev"]
    )
    current_devices_match = expected["repo_dev"] == expected["build_dev"]
    if stable_identity and previous_devices_match and current_devices_match:
        return
    _fail("BUILD_DIR 归属标记与仓库或目录身份不匹配")


def _open_named_directory(parent_descriptor: int, name: str) -> int:
    try:
        return os.open(name, DIRECTORY_FLAGS, dir_fd=parent_descriptor)
    except OSError as error:
        _fail(f"BUILD_DIR 必须是无符号链接的目录：{error}")


def _ensure_subdirectory(parent_descriptor: int, name: str) -> int:
    try:
        os.mkdir(name, 0o755, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    return _open_named_directory(parent_descriptor, name)


def _prepare(location: Location) -> None:
    repo_descriptor = _open_repo(location)
    parent_descriptor: int | None = None
    build_descriptor: int | None = None
    created = False
    try:
        repo_status = os.fstat(repo_descriptor)
        parent_descriptor, name = _open_parent(repo_descriptor, location)
        if parent_descriptor is None:
            _fail("BUILD_DIR 的父目录不存在；拒绝隐式创建未知父目录")
        try:
            build_descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        except FileNotFoundError:
            try:
                os.mkdir(name, 0o755, dir_fd=parent_descriptor)
            except FileExistsError:
                _fail("BUILD_DIR 在创建过程中被其他路径替换")
            created = True
            build_descriptor = _open_named_directory(parent_descriptor, name)

        if _fd_path(build_descriptor) != location.build_path:
            _fail("BUILD_DIR 包含符号链接或发生替换")
        if created:
            # DrvFS 可能在创建句柄关闭前始终报告 inode=0；先释放该句柄，
            # 再以父目录 dirfd 重新绑定名称并要求两次稳定的非零身份。
            os.close(build_descriptor)
            build_descriptor = None
            build_descriptor, build_status = _stable_created_status(
                parent_descriptor, name
            )
            if _fd_path(build_descriptor) != location.build_path:
                _fail("新建 BUILD_DIR 在身份稳定时发生替换")
        else:
            build_status = os.fstat(build_descriptor)
        if created:
            _write_marker(build_descriptor, location, repo_status, build_status)
            named_descriptor = _open_named_directory(parent_descriptor, name)
            try:
                named_status = os.fstat(named_descriptor)
                if _identity(named_status) != _identity(build_status):
                    _fail("BUILD_DIR 在写入归属标记时被替换")
                _validate_marker(
                    named_descriptor, location, repo_status, named_status
                )
            finally:
                os.close(named_descriptor)
        else:
            _validate_marker(build_descriptor, location, repo_status, build_status)

        descriptors: dict[tuple[str, ...], int] = {(): os.dup(build_descriptor)}
        try:
            for parts in BUILD_SUBDIRECTORIES:
                parent = descriptors[parts[:-1]]
                descriptors[parts] = _ensure_subdirectory(parent, parts[-1])
        finally:
            for descriptor in descriptors.values():
                os.close(descriptor)
    finally:
        if build_descriptor is not None:
            os.close(build_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        os.close(repo_descriptor)


def _test_hook(stage: str) -> None:
    if os.environ.get("MINIOS_TEST_MODE") != "1":
        return
    if os.environ.get("MINIOS_CLEAN_TEST_HOOK") != stage:
        return
    names = (
        "MINIOS_TEST_HOOK_READY",
        "MINIOS_TEST_HOOK_CONTINUE",
        "MINIOS_TEST_HOOK_LOG",
    )
    values = {name: os.environ.get(name, "") for name in names}
    if any(not value or not os.path.isabs(value) for value in values.values()):
        _fail("cleanup 测试 hook 控制路径必须是绝对路径")
    ready = Path(values["MINIOS_TEST_HOOK_READY"])
    proceed = Path(values["MINIOS_TEST_HOOK_CONTINUE"])
    log = Path(values["MINIOS_TEST_HOOK_LOG"])
    if len({ready, proceed, log}) != 3:
        _fail("cleanup 测试 hook 控制路径必须互不相同")
    log.write_text(stage + "\n", encoding="utf-8")
    ready.write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not proceed.is_file():
        if time.monotonic() >= deadline:
            _fail("cleanup 测试 hook 等待 continue 超时")
        time.sleep(0.01)


def _same_named_identity(
    parent_descriptor: int, name: str, expected: tuple[int, int]
) -> bool:
    # DrvFS 的 rename 已成功返回后，新名称可能短暂尚不可见；只等待名称出现，
    # 一旦观察到不同身份就立即失败，不能把真正的 replacement 当成延迟。
    deadline = time.monotonic() + 1
    while True:
        try:
            status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
            continue
        return stat.S_ISDIR(status.st_mode) and _identity(status) == expected


def _refresh_parent(
    location: Location, expected_identity: tuple[int, int]
) -> tuple[int, str]:
    """重新打开父目录，绕过 DrvFS rename 后的旧目录句柄名称缓存。"""

    repo_descriptor = _open_repo(location)
    try:
        parent_descriptor, name = _open_parent(repo_descriptor, location)
        if parent_descriptor is None:
            _fail("BUILD_DIR 父目录在操作过程中消失")
        if _identity(os.fstat(parent_descriptor)) != expected_identity:
            os.close(parent_descriptor)
            _fail("BUILD_DIR 父目录在操作过程中被替换")
        return parent_descriptor, name
    finally:
        os.close(repo_descriptor)


def _replacement_after_rename(
    parent_descriptor: int, name: str, moved_identity: tuple[int, int]
) -> bool:
    """等待 DrvFS 旧名称消失；不同 inode 表示真实 replacement。"""

    deadline = time.monotonic() + 1
    while True:
        try:
            status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if _identity(status) != moved_identity:
            return True
        if time.monotonic() >= deadline:
            return True
        time.sleep(0.01)


def _remove_tree(directory_descriptor: int) -> None:
    for name in os.listdir(directory_descriptor):
        before = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if stat.S_ISDIR(before.st_mode):
            child = os.open(name, DIRECTORY_FLAGS, dir_fd=directory_descriptor)
            try:
                if _identity(os.fstat(child)) != _identity(before):
                    _fail(f"清理时目录身份发生变化：{name}")
                _remove_tree(child)
            finally:
                os.close(child)
            current = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or _identity(current) != _identity(before):
                _fail(f"清理时目录被替换：{name}")
            os.rmdir(name, dir_fd=directory_descriptor)
        else:
            current = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if _identity(current) != _identity(before) or current.st_mode != before.st_mode:
                _fail(f"清理时文件被替换：{name}")
            os.unlink(name, dir_fd=directory_descriptor)


def _clean(location: Location, target: str) -> None:
    repo_descriptor = _open_repo(location)
    parent_descriptor: int | None = None
    build_descriptor: int | None = None
    try:
        repo_status = os.fstat(repo_descriptor)
        parent_descriptor, name = _open_parent(repo_descriptor, location)
        if parent_descriptor is None:
            return
        parent_identity = _identity(os.fstat(parent_descriptor))
        try:
            status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(status.st_mode):
            _fail("BUILD_DIR 已存在但不是普通目录")
        build_descriptor = _open_named_directory(parent_descriptor, name)
        build_status = os.fstat(build_descriptor)
        if _identity(build_status) != _identity(status):
            _fail("BUILD_DIR 在打开过程中发生替换")
        if _fd_path(build_descriptor) != location.build_path:
            _fail("BUILD_DIR 包含符号链接或发生替换")
        _validate_marker(build_descriptor, location, repo_status, build_status)

        stage = f"cleanup-after-validation-before-remove:{target}"
        _test_hook(stage)
        expected_identity = _identity(build_status)
        os.close(parent_descriptor)
        parent_descriptor, name = _refresh_parent(location, parent_identity)
        if not _same_named_identity(parent_descriptor, name, expected_identity):
            _fail("BUILD_DIR 在校验后被替换；拒绝清理")

        # DrvFS 对“普通目录重命名为点目录”的名称缓存并非同步可见；使用同级
        # 非隐藏随机名称，仍由已打开 parent dirfd 完整约束。
        quarantine = f"{name}.minios-clean-{os.getpid()}-{secrets.token_hex(12)}"
        try:
            os.stat(quarantine, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _fail("清理隔离目录名称发生冲突")
        os.rename(
            name,
            quarantine,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        # DrvFS 在被重命名目录仍有旧名称 fd 打开时，不会向同一进程发布新名称。
        # 原子 rename 已完成且身份已记录，此处关闭后立即从 fresh parent 重新绑定。
        os.close(build_descriptor)
        build_descriptor = None
        os.close(parent_descriptor)
        parent_descriptor, name = _refresh_parent(location, parent_identity)
        if not _same_named_identity(parent_descriptor, quarantine, expected_identity):
            try:
                observed = os.stat(
                    quarantine,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                detail = f"observed={_identity(observed)} expected={expected_identity}"
            except OSError as error:
                detail = f"observed=unavailable({error}) expected={expected_identity}"
            try:
                os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(
                    quarantine,
                    name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
            _fail(f"BUILD_DIR 在隔离时被替换；拒绝递归清理；{detail}")
        quarantined_descriptor = _open_named_directory(
            parent_descriptor, quarantine
        )
        if _identity(os.fstat(quarantined_descriptor)) != expected_identity:
            os.close(quarantined_descriptor)
            _fail("隔离后的 BUILD_DIR 文件描述符身份不匹配")
        build_descriptor = quarantined_descriptor
        replacement_exists = _replacement_after_rename(
            parent_descriptor, name, expected_identity
        )

        _remove_tree(build_descriptor)
        os.close(build_descriptor)
        build_descriptor = None
        if not _same_named_identity(parent_descriptor, quarantine, expected_identity):
            _fail("隔离后的 BUILD_DIR 在删除前被替换")
        os.rmdir(quarantine, dir_fd=parent_descriptor)
        if replacement_exists:
            _fail("清理期间检测到 BUILD_DIR replacement；外来目录已保留")
    finally:
        if build_descriptor is not None:
            os.close(build_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        os.close(repo_descriptor)


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", allow_abbrev=False)
    prepare.add_argument("--repo", required=True)
    prepare.add_argument("--build", required=True)
    clean = subparsers.add_parser("clean", allow_abbrev=False)
    clean.add_argument("--repo", required=True)
    clean.add_argument("--build", required=True)
    clean.add_argument("--target", choices=("clean", "distclean"), required=True)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    try:
        location = _validate_arguments(options.repo, options.build)
        if options.command == "prepare":
            _prepare(location)
        else:
            _clean(location, options.target)
    except (GuardError, OSError) as error:
        print(f"build_dir_guard.py: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
