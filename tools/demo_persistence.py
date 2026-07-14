#!/usr/bin/env python3
"""运行产品双启动并展示 MiniFS 持久化闭环。"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


BOOT_MARKERS = (
    (
        "[KERN] minifs persistence created PASS",
        "[USER] command persistence created PASS",
    ),
    (
        "[KERN] minifs persistence verified and truncated PASS",
        "[USER] command persistence verified PASS",
    ),
)
COMMON_MARKERS = (
    "[S1] boot",
    "[S2] protected mode entered",
    "[KERN] minifs mounted blocks=16128 inodes=1024",
    "[USER] file commands PASS",
)


def run(command: list[str], repo: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def print_evidence(boot: int, output: str, expected: tuple[str, str]) -> None:
    print(f"boot={boot} evidence:")
    for marker in (*COMMON_MARKERS, *expected):
        print(f"  {marker}")


def run_demo(repo: Path, qemu: str) -> int:
    repo = repo.resolve(strict=True)
    if not (repo / "Makefile").is_file():
        print(f"demo: FAIL: 不是仓库根目录：{repo}", file=sys.stderr)
        return 1
    if not sys.platform.startswith("linux"):
        print("demo: FAIL: 持久化演示只允许在 Linux/WSL 中运行", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix=".minios-demo-", dir=repo) as temporary:
        build_dir = Path(temporary) / "build"
        build_relative = build_dir.relative_to(repo).as_posix()
        build = run(
            [
                "bash",
                "environment/with-env.sh",
                "make",
                f"BUILD_DIR={build_relative}",
                "KERNEL_TEST_MINIFS_WRITE=1",
                "-j4",
                "image",
            ],
            repo,
            120,
        )
        if build.returncode != 0:
            print("demo: FAIL: 演示镜像构建失败", file=sys.stderr)
            print(build.stdout + build.stderr, file=sys.stderr)
            return 1

        image = build_dir / "miniorangeos.img"
        for boot, expected in enumerate(BOOT_MARKERS, start=1):
            log = build_dir / f"test-logs/demo-persistence-{boot}.log"
            result = run(
                [
                    sys.executable,
                    "tools/qemu_test.py",
                    "--qemu",
                    qemu,
                    "--image",
                    str(image),
                    "--log",
                    str(log),
                    "--timeout",
                    "15",
                    "--max-log-bytes",
                    "262144",
                    "--repo",
                    str(repo),
                    "--build-dir",
                    build_relative,
                ],
                repo,
                35,
            )
            if result.returncode == 0 or "QEMU 超时" not in result.stderr:
                print(f"demo: FAIL: 第 {boot} 次启动未按产品超时协议结束", file=sys.stderr)
                print(result.stdout + result.stderr, file=sys.stderr)
                return 1
            output = log.read_text(encoding="utf-8", errors="replace")
            missing = [marker for marker in (*COMMON_MARKERS, *expected) if marker not in output]
            if missing or "[PANIC]" in output:
                print(f"demo: FAIL: 第 {boot} 次启动证据不完整：{missing}", file=sys.stderr)
                return 1

            checked = run(
                [
                    sys.executable,
                    "tools/fsck.py",
                    "--layout",
                    "config/image-layout.json",
                    "--image",
                    str(image),
                ],
                repo,
                20,
            )
            if checked.returncode != 0:
                print(f"demo: FAIL: 第 {boot} 次启动后 fsck 失败", file=sys.stderr)
                print(checked.stdout + checked.stderr, file=sys.stderr)
                return 1
            print_evidence(boot, output, expected)
            print(f"boot={boot} fsck=PASS")

        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        print(f"image_sha256={digest}")
        print("demo: PASS: 启动、用户文件命令与双启动持久化闭环完成")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 MiniOrangeOS 双启动持久化演示")
    parser.add_argument("--repo", type=Path, required=True, help="仓库根目录")
    parser.add_argument("--qemu", default="qemu-system-i386", help="QEMU 可执行文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run_demo(args.repo, args.qemu)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"demo: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
