#!/usr/bin/env python3
"""按自主实现边界统计仓库文本文件的物理行数。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CATEGORY_LABELS = {
    "boot_loader_asm": "Boot/Loader 汇编",
    "kernel_c": "内核 C 与头文件",
    "kernel_asm": "内核汇编",
    "shared_abi": "共享 ABI 头文件",
    "user_programs": "用户程序",
    "user_libc": "用户 libc/crt",
    "tools": "工具与环境脚本",
    "tests": "测试",
    "docs": "文档",
    "build_config": "构建与配置",
    "generated": "自动生成文件",
    "third_party": "第三方文件",
}


@dataclass
class Metrics:
    files: int = 0
    total_lines: int = 0
    nonblank_lines: int = 0

    def add(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.files += 1
        self.total_lines += len(lines)
        self.nonblank_lines += sum(1 for line in lines if line.strip())

    def as_dict(self) -> dict[str, int]:
        return {
            "files": self.files,
            "total_lines": self.total_lines,
            "nonblank_lines": self.nonblank_lines,
        }


def iter_tree(root: Path, suffixes: set[str]) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return (
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in suffixes
        and "__pycache__" not in path.parts
    )


def add_paths(
    report: dict[str, Metrics],
    category: str,
    paths: Iterable[Path],
    claimed: set[Path],
) -> None:
    for path in paths:
        resolved = path.resolve(strict=True)
        if resolved in claimed:
            raise ValueError(f"文件被重复分类：{path}")
        claimed.add(resolved)
        report[category].add(path)


def build_report(repo: Path) -> dict[str, object]:
    repo = repo.resolve(strict=True)
    if not (repo / "Makefile").is_file() or not (repo / "PROJECT_PLAN.md").is_file():
        raise ValueError(f"不是 MiniOrangeOS 仓库根目录：{repo}")

    report = {name: Metrics() for name in CATEGORY_LABELS}
    claimed: set[Path] = set()

    add_paths(report, "boot_loader_asm", iter_tree(repo / "boot", {".asm", ".inc"}), claimed)
    add_paths(report, "kernel_c", iter_tree(repo / "kernel", {".c", ".h"}), claimed)
    add_paths(report, "kernel_asm", iter_tree(repo / "kernel", {".asm"}), claimed)
    add_paths(report, "shared_abi", iter_tree(repo / "include", {".h"}), claimed)
    add_paths(report, "user_programs", iter_tree(repo / "user/programs", {".c"}), claimed)
    add_paths(
        report,
        "user_libc",
        (
            *iter_tree(repo / "user/libc", {".c", ".h"}),
            *iter_tree(repo / "user/crt", {".asm"}),
            *iter_tree(repo / "user/include", {".h"}),
        ),
        claimed,
    )
    add_paths(report, "tools", iter_tree(repo / "tools", {".py", ".sh", ".ps1"}), claimed)
    add_paths(
        report,
        "tools",
        iter_tree(repo / "environment", {".py", ".sh", ".ps1"}),
        claimed,
    )
    containerfile = repo / "environment/Containerfile"
    if containerfile.is_file():
        add_paths(report, "tools", (containerfile,), claimed)
    add_paths(report, "tests", iter_tree(repo / "tests", {".py", ".ps1", ".asm"}), claimed)
    add_paths(report, "docs", iter_tree(repo / "docs", {".md"}), claimed)
    root_documents = tuple(
        path
        for path in (
            repo / "README.md",
            repo / "PROJECT_PLAN.md",
            repo / "CONTRIBUTING.md",
            repo / "LICENSE",
        )
        if path.is_file()
    )
    add_paths(report, "docs", root_documents, claimed)

    build_files = [repo / "Makefile", repo / "user/linker.ld", repo / "kernel/linker.ld", repo / "boot/stage2/linker.ld"]
    build_files.extend(iter_tree(repo / "config", {".json"}))
    versions = repo / "environment/versions.env"
    if versions.is_file():
        build_files.append(versions)
    add_paths(report, "build_config", (path for path in build_files if path.is_file()), claimed)

    categories = {name: metrics.as_dict() for name, metrics in report.items()}
    totals = Metrics(
        files=sum(item.files for item in report.values()),
        total_lines=sum(item.total_lines for item in report.values()),
        nonblank_lines=sum(item.nonblank_lines for item in report.values()),
    )
    return {
        "metric": "UTF-8 文本物理行；nonblank_lines 排除空白行",
        "categories": categories,
        "total": totals.as_dict(),
    }


def format_text(report: dict[str, object]) -> str:
    categories = report["categories"]
    assert isinstance(categories, dict)
    lines = ["MiniOrangeOS 代码量统计（物理行）", "", "类别                         文件     总行     非空行"]
    for name, label in CATEGORY_LABELS.items():
        item = categories[name]
        assert isinstance(item, dict)
        lines.append(
            f"{label:<28} {item['files']:>6} {item['total_lines']:>8} {item['nonblank_lines']:>10}"
        )
    total = report["total"]
    assert isinstance(total, dict)
    lines.extend(
        (
            "-" * 58,
            f"{'合计':<28} {total['files']:>6} {total['total_lines']:>8} {total['nonblank_lines']:>10}",
            "",
            "自动生成与第三方文件只列边界，不计入自主核心代码。",
        )
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计 MiniOrangeOS 自主实现代码量")
    parser.add_argument("--repo", type=Path, required=True, help="仓库根目录")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args.repo)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"loc: FAIL: {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
