#!/usr/bin/env python3
"""为 QEMU 工具提供受 T02 build marker 约束的文件描述符路径。"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import Callable

import build_dir_guard as guard


DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
DIRECTORY_FLAGS |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
FILE_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
FILE_FLAGS |= getattr(os, "O_NOFOLLOW", 0)
FILE_FLAGS |= getattr(os, "O_NONBLOCK", 0)


class PathBoundaryError(Exception):
    """表示路径不能证明位于可信构建目录内。"""


@dataclass
class BoundFile:
    """保持已验证普通文件身份直至子进程继承。"""

    descriptor: int
    size: int

    @property
    def proc_path(self) -> str:
        return f"/proc/self/fd/{self.descriptor}"

    @property
    def owner_path(self) -> str:
        """允许测试 wrapper 的后代在持有者存活期间打开同一已验证文件。"""

        return f"/proc/{os.getpid()}/fd/{self.descriptor}"

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1

    def __enter__(self) -> BoundFile:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


@dataclass
class BoundLog:
    """将日志原子提交到已锚定的构建子目录。"""

    directory_descriptor: int
    name: str
    validate_directory: Callable[[], None]
    original_target: tuple[int, int, int, int] | None

    def _target_identity(self) -> tuple[int, int, int, int] | None:
        try:
            status = os.stat(
                self.name,
                dir_fd=self.directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise PathBoundaryError("已有日志目标必须是单链接普通文件")
        return status.st_dev, status.st_ino, status.st_mode, status.st_nlink

    def _validate_target(self) -> None:
        if self._target_identity() != self.original_target:
            raise PathBoundaryError("日志目标在生成过程中发生变化")

    def write_atomic(self, content: bytes, temporary_name: str) -> None:
        descriptor = -1
        try:
            self.validate_directory()
            self._validate_target()
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self.directory_descriptor,
            )
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise PathBoundaryError("日志写入没有取得进展")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            self.validate_directory()
            self._validate_target()
            os.replace(
                temporary_name,
                self.name,
                src_dir_fd=self.directory_descriptor,
                dst_dir_fd=self.directory_descriptor,
            )
            os.fsync(self.directory_descriptor)
            self.validate_directory()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=self.directory_descriptor)
            except FileNotFoundError:
                pass

    def close(self) -> None:
        if self.directory_descriptor >= 0:
            os.close(self.directory_descriptor)
            self.directory_descriptor = -1

    def __enter__(self) -> BoundLog:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


class BoundBuild:
    """持有经 build marker 验证的仓库和 BUILD_DIR。"""

    def __init__(
        self,
        repo_descriptor: int,
        build_descriptor: int,
        location: guard.Location,
    ) -> None:
        self.repo_descriptor = repo_descriptor
        self.build_descriptor = build_descriptor
        self.location = location
        self.build_path = location.build_path
        self.repo_identity = guard._identity(os.fstat(repo_descriptor))
        self.build_identity = guard._identity(os.fstat(build_descriptor))

    @classmethod
    def open(cls, repo_argument: str, build_argument: str) -> BoundBuild:
        try:
            location = guard._validate_arguments(repo_argument, build_argument)
            repo_descriptor = guard._open_repo(location)
            parent_descriptor: int | None = None
            build_descriptor = -1
            try:
                parent_descriptor, name = guard._open_parent(repo_descriptor, location)
                if parent_descriptor is None:
                    raise PathBoundaryError("BUILD_DIR 不存在")
                build_descriptor = guard._open_named_directory(parent_descriptor, name)
                guard._validate_marker(
                    build_descriptor,
                    location,
                    os.fstat(repo_descriptor),
                    os.fstat(build_descriptor),
                )
                return cls(repo_descriptor, build_descriptor, location)
            except BaseException:
                if build_descriptor >= 0:
                    os.close(build_descriptor)
                os.close(repo_descriptor)
                raise
            finally:
                if parent_descriptor is not None:
                    os.close(parent_descriptor)
        except (guard.GuardError, PathBoundaryError, OSError) as error:
            raise PathBoundaryError(f"无法绑定可信 BUILD_DIR：{error}") from error

    def _parts(self, argument: str, label: str) -> tuple[str, ...]:
        if not argument or "\x00" in argument or "\\" in argument:
            raise PathBoundaryError(f"{label} 路径为空或含非法字符")
        raw = argument.split("/")
        if any(part in {".", ".."} for part in raw):
            raise PathBoundaryError(f"{label} 路径不得包含当前目录或父目录段")
        absolute = os.path.abspath(argument)
        try:
            common = os.path.commonpath((self.build_path, absolute))
        except ValueError as error:
            raise PathBoundaryError(f"无法比较 {label} 与 BUILD_DIR：{error}") from error
        if common != self.build_path or absolute == self.build_path:
            raise PathBoundaryError(f"{label} 必须位于 BUILD_DIR 内")
        relative = os.path.relpath(absolute, self.build_path)
        parts = tuple(relative.split(os.sep))
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise PathBoundaryError(f"{label} 相对路径无效")
        return parts

    def _fresh_build(self) -> int:
        parent_descriptor: int | None = None
        descriptor = -1
        try:
            parent_descriptor, name = guard._open_parent(
                self.repo_descriptor, self.location
            )
            if parent_descriptor is None:
                raise PathBoundaryError("BUILD_DIR 在运行过程中消失")
            descriptor = guard._open_named_directory(parent_descriptor, name)
            status = os.fstat(descriptor)
            if guard._identity(status) != self.build_identity:
                raise PathBoundaryError("BUILD_DIR 在运行过程中被替换")
            guard._validate_marker(
                descriptor,
                self.location,
                os.fstat(self.repo_descriptor),
                status,
            )
            return descriptor
        except (guard.GuardError, PathBoundaryError, OSError) as error:
            if descriptor >= 0:
                os.close(descriptor)
            if isinstance(error, PathBoundaryError):
                raise
            raise PathBoundaryError(f"无法复核 BUILD_DIR：{error}") from error
        finally:
            if parent_descriptor is not None:
                os.close(parent_descriptor)

    def open_file(self, argument: str, label: str) -> BoundFile:
        parts = self._parts(argument, label)
        descriptor = os.dup(self.build_descriptor)
        try:
            for part in parts[:-1]:
                next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            file_descriptor = os.open(parts[-1], FILE_FLAGS, dir_fd=descriptor)
            try:
                status = os.fstat(file_descriptor)
                if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                    raise PathBoundaryError(f"{label} 必须是单链接普通文件")
                if status.st_size <= 0:
                    raise PathBoundaryError(f"{label} 不得为空")
                fresh = self._fresh_build()
                os.close(fresh)
                return BoundFile(file_descriptor, status.st_size)
            except BaseException:
                os.close(file_descriptor)
                raise
        except OSError as error:
            raise PathBoundaryError(f"无法安全打开 {label}：{error}") from error
        finally:
            os.close(descriptor)

    def bind_log(self, argument: str) -> BoundLog:
        parts = self._parts(argument, "日志")
        descriptor = os.dup(self.build_descriptor)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            expected_directory = guard._identity(os.fstat(descriptor))

            def validate_directory() -> None:
                fresh = self._fresh_build()
                try:
                    for part in parts[:-1]:
                        next_descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=fresh)
                        os.close(fresh)
                        fresh = next_descriptor
                    if guard._identity(os.fstat(fresh)) != expected_directory:
                        raise PathBoundaryError("日志父目录在运行过程中被替换")
                except OSError as error:
                    raise PathBoundaryError(f"无法复核日志父目录：{error}") from error
                finally:
                    os.close(fresh)

            try:
                status = os.stat(
                    parts[-1], dir_fd=descriptor, follow_symlinks=False
                )
            except FileNotFoundError:
                original_target = None
            else:
                if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                    raise PathBoundaryError("已有日志目标必须是单链接普通文件")
                original_target = (
                    status.st_dev,
                    status.st_ino,
                    status.st_mode,
                    status.st_nlink,
                )
            validate_directory()
            return BoundLog(
                descriptor,
                parts[-1],
                validate_directory,
                original_target,
            )
        except (PathBoundaryError, OSError) as error:
            os.close(descriptor)
            if isinstance(error, PathBoundaryError):
                raise
            raise PathBoundaryError(f"无法安全绑定日志：{error}") from error

    def close(self) -> None:
        if self.build_descriptor >= 0:
            os.close(self.build_descriptor)
            self.build_descriptor = -1
        if self.repo_descriptor >= 0:
            os.close(self.repo_descriptor)
            self.repo_descriptor = -1

    def __enter__(self) -> BoundBuild:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()
