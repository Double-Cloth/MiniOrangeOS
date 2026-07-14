#!/usr/bin/env python3
"""从统一镜像布局生成内核 MiniFS 卷位置常量。"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path


sys.dont_write_bytecode = True

import minifs


def _render(layout: minifs.VolumeLayout) -> bytes:
    return (
        "#ifndef MINIOS_GENERATED_MINIFS_LAYOUT_H\n"
        "#define MINIOS_GENERATED_MINIFS_LAYOUT_H\n\n"
        f"#define MINIFS_VOLUME_START_BLOCK {layout.lba // minifs.SECTORS_PER_BLOCK}U\n"
        f"#define MINIFS_VOLUME_BLOCK_COUNT {layout.block_count}U\n\n"
        "#endif\n"
    ).encode("ascii")


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=False, exist_ok=True)
    temporary = path.parent / (
        f".{path.name}.{os.getpid()}.{secrets.token_hex(12)}.tmp"
    )
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                minifs.fail("布局头写入没有取得进展")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
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
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_arguments(arguments)
    try:
        layout = minifs.load_volume_layout(options.layout)
        _write_atomic(options.output, _render(layout))
    except (minifs.MiniFsError, OSError) as error:
        print(f"generate_minifs_layout.py: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
