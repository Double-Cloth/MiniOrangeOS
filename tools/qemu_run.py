#!/usr/bin/env python3
"""启动 MiniOrangeOS 的交互式 QEMU 或本地回环 GDB 会话。"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

from qemu_paths import BoundBuild, PathBoundaryError


ENDPOINT_PATTERN = re.compile(r"tcp:127\.0\.0\.1:([1-9][0-9]{0,4})\Z")
QEMU_SHUTDOWN_VALUE = 0x2A
QEMU_SHUTDOWN_STATUS = (QEMU_SHUTDOWN_VALUE << 1) | 1


class RunError(Exception):
    """表示可直接报告给调用者的启动参数错误。"""


def _endpoint(value: str) -> tuple[str, int]:
    match = ENDPOINT_PATTERN.fullmatch(value)
    if match is None:
        raise RunError("GDB endpoint 必须是 tcp:127.0.0.1:<1-65535>")
    port = int(match.group(1))
    if port > 65535:
        raise RunError("GDB endpoint 端口必须位于 1-65535")
    return value, port


def _required(value: str | None, option: str) -> str:
    if value is None:
        raise RunError(f"{option} 是当前模式的必需参数")
    return value


def _qemu_command(options: argparse.Namespace, endpoint: str, image: str) -> list[str]:
    command = [
        options.qemu,
        "-drive",
        f"file={image},format=raw,if=ide,index=0,media=disk",
        "-no-reboot",
        "-no-shutdown",
        "-device",
        "isa-debug-exit,iobase=0xf4,iosize=0x04",
    ]
    if options.mode == "serial":
        command.extend(("-display", "none", "-monitor", "none", "-serial", "stdio"))
    elif options.mode == "curses":
        command.extend(("-display", "curses", "-serial", "none"))
    elif options.mode == "debug":
        command.extend(
            ("-display", "none", "-monitor", "none", "-serial", "stdio", "-S", "-gdb", endpoint)
        )
    else:  # pragma: no cover - argparse 已限制 mode
        raise RunError(f"未知 QEMU 模式：{options.mode}")
    return command


def _gdb_command(options: argparse.Namespace, port: int, kernel: str) -> list[str]:
    return [
        options.gdb,
        str(kernel),
        "-ex",
        f"target remote 127.0.0.1:{port}",
    ]


def _qemu_result(returncode: int) -> int:
    if returncode == QEMU_SHUTDOWN_STATUS:
        return 0
    return returncode


def _arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("serial", "curses", "debug", "gdb"))
    parser.add_argument("--qemu", default="qemu-system-i386")
    parser.add_argument("--gdb", default="gdb")
    parser.add_argument("--image")
    parser.add_argument("--kernel")
    parser.add_argument("--gdb-endpoint", default="tcp:127.0.0.1:1234")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--build-dir", default="build")
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _arguments(arguments)
    try:
        endpoint, port = _endpoint(options.gdb_endpoint)
        repo = os.path.abspath(options.repo)
        with BoundBuild.open(repo, options.build_dir) as build:
            if options.mode == "gdb":
                with build.open_file(_required(options.kernel, "--kernel"), "Kernel") as kernel:
                    command = _gdb_command(options, port, kernel.owner_path)
                    return subprocess.run(
                        command, check=False, pass_fds=(kernel.descriptor,)
                    ).returncode
            with build.open_file(_required(options.image, "--image"), "镜像") as image:
                command = _qemu_command(options, endpoint, image.owner_path)
                return _qemu_result(
                    subprocess.run(
                        command, check=False, pass_fds=(image.descriptor,)
                    ).returncode
                )
    except (RunError, PathBoundaryError, OSError) as error:
        print(f"qemu_run.py: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
