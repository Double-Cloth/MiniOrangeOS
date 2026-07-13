#!/usr/bin/env python3
"""以逐级 openat 边界安全地更新 apt package lock。"""

from __future__ import annotations

import argparse
import fcntl
import os
import secrets
import signal
import stat
import sys
from dataclasses import dataclass


LOCK_NAME = "apt-packages.lock"
PARTIAL_PREFIX = f"{LOCK_NAME}.partial."
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
HANDLED_SIGNALS = frozenset((signal.SIGINT, signal.SIGTERM, signal.SIGHUP))


class WriterError(RuntimeError):
    """表示边界校验或原子写入失败。"""


@dataclass(frozen=True)
class Arguments:
    environment_root: str
    target_uid: int
    target_gid: int
    test_root: str | None
    race_phase: str | None
    race_state: str | None
    race_original: str | None
    race_outside: str | None


def parse_arguments() -> Arguments:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-root", required=True)
    parser.add_argument("--target-uid", required=True, type=int)
    parser.add_argument("--target-gid", required=True, type=int)
    parser.add_argument("--test-root")
    parser.add_argument(
        "--race-phase",
        choices=(
            "before-open",
            "after-open",
            "after-partial",
            "signal-after-create",
            "replace-partial",
        ),
    )
    parser.add_argument("--race-state")
    parser.add_argument("--race-original")
    parser.add_argument("--race-outside")
    namespace = parser.parse_args()
    if namespace.target_uid <= 0 or namespace.target_gid <= 0:
        parser.error("target uid/gid 必须是非零整数")
    race_values = (
        namespace.race_phase,
        namespace.race_state,
        namespace.race_original,
        namespace.race_outside,
    )
    if any(race_values) and (not namespace.test_root or not all(race_values)):
        parser.error("race 参数只能在 test root 下完整提供")
    return Arguments(
        environment_root=namespace.environment_root,
        target_uid=namespace.target_uid,
        target_gid=namespace.target_gid,
        test_root=namespace.test_root,
        race_phase=namespace.race_phase,
        race_state=namespace.race_state,
        race_original=namespace.race_original,
        race_outside=namespace.race_outside,
    )


def canonical_absolute(path: str, label: str) -> str:
    if not path.startswith("/") or os.path.normpath(path) != path:
        raise WriterError(f"{label} 必须是规范绝对路径：{path}")
    return path


def identity(item: os.stat_result) -> tuple[int, int]:
    return item.st_dev, item.st_ino


def validate_directory(
    item: os.stat_result,
    label: str,
    target_uid: int,
    *,
    require_target: bool,
) -> None:
    if not stat.S_ISDIR(item.st_mode):
        raise WriterError(f"路径组件不是目录：{label}")
    if require_target:
        if item.st_uid != target_uid:
            raise WriterError(f"最终目录不是 target-owned：{label}")
    elif item.st_uid not in (0, target_uid):
        raise WriterError(f"路径组件 owner 不可信：{label} uid={item.st_uid}")
    writable = stat.S_IMODE(item.st_mode) & 0o022
    root_sticky_ancestor = (
        item.st_uid == 0
        and bool(item.st_mode & stat.S_ISVTX)
        and bool(stat.S_IMODE(item.st_mode) & 0o002)
    )
    if writable and not root_sticky_ancestor:
        raise WriterError(
            f"路径组件可由组/其他用户写：{label} mode={stat.S_IMODE(item.st_mode):04o}"
        )


def path_components(environment_root: str) -> list[str]:
    root = canonical_absolute(environment_root, "environment root")
    if root == "/":
        raise WriterError("environment root 不能是 /")
    return [part for part in root.split("/") if part] + ["state"]


def open_validated_chain(
    args: Arguments, *, state_restricted: bool = False
) -> tuple[list[int], list[tuple[int, int]]]:
    components = path_components(args.environment_root)
    descriptors: list[int] = []
    identities: list[tuple[int, int]] = []
    try:
        root_fd = os.open("/", DIRECTORY_FLAGS)
        descriptors.append(root_fd)
        root_stat = os.fstat(root_fd)
        validate_directory(root_stat, "/", args.target_uid, require_target=False)
        identities.append(identity(root_stat))
        current = ""
        for index, component in enumerate(components):
            current = f"{current}/{component}"
            opened = os.open(component, DIRECTORY_FLAGS, dir_fd=descriptors[-1])
            descriptors.append(opened)
            item = os.fstat(opened)
            is_state = index == len(components) - 1
            require_target = index == len(components) - 2 or (
                is_state and not state_restricted
            )
            validate_directory(
                item, current, args.target_uid, require_target=require_target
            )
            if is_state and state_restricted and (
                item.st_uid != 0 or stat.S_IMODE(item.st_mode) != 0o700
            ):
                raise WriterError("当前 package-state 路径不是锚定的 root-only 目录")
            identities.append(identity(item))
        return descriptors, identities
    except BaseException:
        close_descriptors(descriptors)
        raise


def assert_chain_unchanged(
    args: Arguments,
    expected_identities: list[tuple[int, int]],
    *,
    state_restricted: bool = False,
) -> None:
    current_fds, current_identities = open_validated_chain(
        args, state_restricted=state_restricted
    )
    try:
        if current_identities != expected_identities:
            raise WriterError("package-state 当前路径与锚定目录链 inode 不一致")
    finally:
        close_descriptors(current_fds)


def close_descriptors(descriptors: list[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def validate_existing_entries(state_fd: int, target_uid: int) -> None:
    names = os.listdir(state_fd)
    partials = [name for name in names if name.startswith(PARTIAL_PREFIX)]
    if partials:
        raise WriterError(f"拒绝预存 package lock partial：{partials[0]}")
    try:
        item = os.stat(LOCK_NAME, dir_fd=state_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (
        not stat.S_ISREG(item.st_mode)
        or item.st_uid != target_uid
        or stat.S_IMODE(item.st_mode) != 0o644
    ):
        raise WriterError("已有 package lock owner/type/mode 不可信")


def validate_test_race_paths(args: Arguments) -> None:
    if args.race_phase is None:
        return
    assert args.test_root is not None
    assert args.race_state is not None
    assert args.race_original is not None
    assert args.race_outside is not None
    test_root = canonical_absolute(args.test_root, "test root")
    paths = (args.race_state, args.race_original, args.race_outside)
    for path in paths:
        canonical_absolute(path, "race path")
        if os.path.commonpath((test_root, path)) != test_root:
            raise WriterError(f"race path 越过 test root：{path}")
    if args.race_state != f"{args.environment_root}/state":
        raise WriterError("race state 不是当前 package-state 路径")


def run_test_race(args: Arguments, phase: str) -> None:
    if args.race_phase != phase:
        return
    validate_test_race_paths(args)
    assert args.race_state is not None
    assert args.race_original is not None
    assert args.race_outside is not None
    os.rename(args.race_state, args.race_original)
    os.symlink(args.race_outside, args.race_state)


def create_partial(state_fd: int) -> tuple[int, str]:
    for _ in range(128):
        name = f"{PARTIAL_PREFIX}{os.getpid()}.{secrets.token_hex(8)}"
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
                dir_fd=state_fd,
            )
            return descriptor, name
        except FileExistsError:
            continue
    raise WriterError("无法创建唯一 package lock partial")


def write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise WriterError("package lock partial 写入不完整")
        view = view[written:]


def validate_written_file(descriptor: int, target_uid: int, expected_size: int) -> None:
    item = os.fstat(descriptor)
    if (
        not stat.S_ISREG(item.st_mode)
        or item.st_uid != target_uid
        or stat.S_IMODE(item.st_mode) != 0o644
        or item.st_size != expected_size
    ):
        raise WriterError("package lock partial 写入后元数据不可信")


def replace_partial_for_test(
    args: Arguments, state_fd: int, partial_name: str, size: int
) -> None:
    if args.race_phase != "replace-partial":
        return
    os.unlink(partial_name, dir_fd=state_fd)
    replacement = os.open(
        partial_name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        0o600,
        dir_fd=state_fd,
    )
    try:
        write_all(replacement, b"X" * size)
        os.fchmod(replacement, 0o644)
        os.fchown(replacement, args.target_uid, args.target_gid)
        os.fsync(replacement)
    finally:
        os.close(replacement)


def install_signal_handlers() -> None:
    def interrupted(signum: int, _frame: object) -> None:
        raise WriterError(f"收到信号 {signum}，中止 package lock 写入")

    for signum in HANDLED_SIGNALS:
        signal.signal(signum, interrupted)


def write_package_lock(args: Arguments, content: bytes) -> None:
    if not content or not content.endswith(b"\n") or b"\0" in content:
        raise WriterError("package lock 输入必须是非空、换行结尾且不含 NUL 的内容")
    validate_test_race_paths(args)
    run_test_race(args, "before-open")
    descriptors, identities = open_validated_chain(args)
    state_fd = descriptors[-1]
    original_state = os.fstat(state_fd)
    original_state_mode = stat.S_IMODE(original_state.st_mode)
    state_restricted = False
    partial_fd: int | None = None
    partial_name: str | None = None
    try:
        fcntl.flock(state_fd, fcntl.LOCK_EX)
        state_restricted = True
        os.fchown(state_fd, 0, 0)
        os.fchmod(state_fd, 0o700)
        restricted = os.fstat(state_fd)
        if restricted.st_uid != 0 or stat.S_IMODE(restricted.st_mode) != 0o700:
            raise WriterError("无法把锚定 package-state 临时收紧为 root-only")
        validate_existing_entries(state_fd, args.target_uid)
        run_test_race(args, "after-open")
        assert_chain_unchanged(args, identities, state_restricted=True)
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        try:
            partial_fd, partial_name = create_partial(state_fd)
            if args.race_phase == "signal-after-create":
                os.kill(os.getpid(), signal.SIGTERM)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        write_all(partial_fd, content)
        os.fchmod(partial_fd, 0o644)
        os.fchown(partial_fd, args.target_uid, args.target_gid)
        os.fsync(partial_fd)
        validate_written_file(partial_fd, args.target_uid, len(content))
        run_test_race(args, "after-partial")
        assert_chain_unchanged(args, identities, state_restricted=True)
        expected_partial_identity = identity(os.fstat(partial_fd))
        replace_partial_for_test(args, state_fd, partial_name, len(content))
        named_partial = os.stat(
            partial_name, dir_fd=state_fd, follow_symlinks=False
        )
        if identity(named_partial) != expected_partial_identity:
            raise WriterError("package lock partial 名称已被替换")
        os.replace(
            partial_name,
            LOCK_NAME,
            src_dir_fd=state_fd,
            dst_dir_fd=state_fd,
        )
        partial_name = None
        os.fsync(state_fd)
        final = os.stat(LOCK_NAME, dir_fd=state_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(final.st_mode)
            or identity(final) != expected_partial_identity
            or final.st_uid != args.target_uid
            or stat.S_IMODE(final.st_mode) != 0o644
            or final.st_size != len(content)
        ):
            raise WriterError("原子替换后的 package lock 元数据不可信")
        assert_chain_unchanged(args, identities, state_restricted=True)
    finally:
        try:
            if partial_fd is not None:
                try:
                    os.close(partial_fd)
                except OSError:
                    pass
            if partial_name is not None:
                try:
                    os.unlink(partial_name, dir_fd=state_fd)
                    os.fsync(state_fd)
                except FileNotFoundError:
                    pass
        finally:
            restore_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
            try:
                if state_restricted:
                    os.fchmod(state_fd, original_state_mode)
                    os.fchown(
                        state_fd, original_state.st_uid, original_state.st_gid
                    )
                    os.fsync(state_fd)
            finally:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
                finally:
                    close_descriptors(descriptors)


def main() -> int:
    try:
        args = parse_arguments()
        install_signal_handlers()
        write_package_lock(args, sys.stdin.buffer.read())
    except (WriterError, OSError) as error:
        print(f"FAIL package-state writer: {error}", file=sys.stderr)
        return 1
    print("package_lock_status=complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
