"""在专用 WSL 中验证 T02 构建、增量依赖和镜像行为。"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows 只收集并跳过真实 WSL 测试
    resource = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[2]
IMAGE_NAME = "miniorangeos.img"
EXPECTED_FINAL_ARTIFACTS = (
    "boot/stage1.bin",
    "boot/stage2.elf",
    "boot/stage2.bin",
    "boot/stage2.map",
    "boot/stage2.sym",
    "kernel/kernel.elf",
    "kernel/kernel.bin",
    "kernel/kernel.map",
    "kernel/kernel.sym",
    IMAGE_NAME,
)
EXPECTED_DEPFILES = (
    "boot/stage2/entry.d",
    "kernel/arch/x86/entry.d",
    "kernel/core/kernel.d",
)
KERNEL_C_FLAGS = {
    "-std=c11",
    "-ffreestanding",
    "-fno-builtin",
    "-fno-stack-protector",
    "-fno-pic",
    "-fno-pie",
    "-m32",
    "-mno-mmx",
    "-mno-sse",
    "-mno-sse2",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Wshadow",
    "-Wconversion",
    "-Wmissing-prototypes",
    "-Wstrict-prototypes",
}


def _is_wsl_linux() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return False
    return "microsoft" in release.casefold()


@unittest.skipUnless(_is_wsl_linux(), "真实构建契约只在专用 WSL Linux 中执行")
class BuildRuntimeTests(unittest.TestCase):
    @contextlib.contextmanager
    def _workspace(self) -> Iterator[Path]:
        test_root = ROOT / "build/test-workspaces"
        test_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="minios-t02-", dir=test_root
            ) as temporary_directory:
                workspace = Path(temporary_directory) / "workspace"
                shutil.copytree(
                    ROOT,
                    workspace,
                    ignore=shutil.ignore_patterns(
                        ".git",
                        ".superpowers",
                        "build",
                        "__pycache__",
                        ".pytest_cache",
                        ".cache",
                    ),
                )
                self.assertTrue(
                    workspace.is_relative_to(test_root),
                    f"测试工作副本逃逸权威工作树：{workspace}",
                )
                self.assertTrue(
                    workspace.as_posix().startswith("/mnt/"),
                    f"测试工作副本不在 Windows DrvFS 挂载：{workspace}",
                )
                yield workspace
        finally:
            for directory in (test_root, ROOT / "build"):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def _assert_makefile(self, workspace: Path) -> None:
        self.assertTrue((workspace / "Makefile").is_file(), "缺少顶层 Makefile")

    def _run(
        self,
        workspace: Path,
        *arguments: str,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        file_size_limit: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["bash", "environment/with-env.sh", *arguments]

        def limit_output_file_size() -> None:
            assert file_size_limit is not None
            assert resource is not None
            resource.setrlimit(
                resource.RLIMIT_FSIZE, (file_size_limit, file_size_limit)
            )
            signal.signal(signal.SIGXFSZ, signal.SIG_DFL)

        return subprocess.run(
            command,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            preexec_fn=limit_output_file_size if file_size_limit is not None else None,
        )

    def _make(
        self,
        workspace: Path,
        *arguments: str,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        self._assert_makefile(workspace)
        return self._run(workspace, "make", *arguments, timeout=timeout)

    def _assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(
            0,
            result.returncode,
            f"命令失败：stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def _build_dir(self, workspace: Path, relative: str = "build") -> Path:
        return workspace / relative

    def _snapshot(self, root: Path) -> dict[str, tuple[int, str]]:
        return {
            path.relative_to(root).as_posix(): (
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def _generated_in_source(self, workspace: Path) -> list[str]:
        suffixes = {".o", ".d", ".elf", ".bin", ".map", ".sym", ".img"}
        return [
            path.relative_to(workspace).as_posix()
            for source_root in (workspace / "boot", workspace / "kernel")
            for path in source_root.rglob("*")
            if path.is_file() and path.suffix in suffixes
        ]

    def _assert_elf32_i386(self, workspace: Path, path: Path) -> None:
        data = path.read_bytes()
        self.assertGreaterEqual(len(data), 52, f"ELF 过短：{path}")
        self.assertEqual(b"\x7fELF", data[:4])
        self.assertEqual(1, data[4], "ELF class 必须为 ELF32")
        self.assertEqual(1, data[5], "ELF data 必须为 little-endian")
        self.assertEqual(3, struct.unpack_from("<H", data, 18)[0], "ELF machine 必须为 i386")
        result = self._run(workspace, "i686-elf-readelf", "-h", str(path))
        self._assert_success(result)

    def _assert_sorted_symbols(self, path: Path) -> None:
        addresses: list[int] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([0-9a-fA-F]+)\s+", line)
            if match:
                addresses.append(int(match.group(1), 16))
        self.assertTrue(addresses, f"符号文件没有地址记录：{path}")
        self.assertEqual(sorted(addresses), addresses, f"符号未按地址排序：{path}")

    def _resolve_tool(self, workspace: Path, name: str) -> str:
        result = self._run(workspace, "sh", "-c", f"command -v -- {shlex.quote(name)}")
        self._assert_success(result)
        resolved = result.stdout.strip()
        self.assertTrue(resolved.startswith("/"), f"工具路径不是绝对路径：{name}={resolved!r}")
        return resolved

    def _write_wrapper(self, path: Path, target: str, log: Path) -> None:
        path.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf 'BEGIN\\n' >> {shlex.quote(str(log))}\n"
            f"printf '%s\\n' \"$@\" >> {shlex.quote(str(log))}\n"
            f"exec {shlex.quote(target)} \"$@\"\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_public_targets_build_expected_artifacts(self) -> None:
        with self._workspace() as workspace:
            clean = self._make(workspace, "clean")
            self._assert_success(clean)
            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            result = self._make(workspace, "image")
            self._assert_success(result)

            build_dir = self._build_dir(workspace)
            missing = [path for path in EXPECTED_FINAL_ARTIFACTS if not (build_dir / path).is_file()]
            self.assertEqual([], missing, f"缺少构建产物：{missing}")
            missing_depfiles = [path for path in EXPECTED_DEPFILES if not (build_dir / path).is_file()]
            self.assertEqual([], missing_depfiles, f"缺少依赖文件：{missing_depfiles}")
            self.assertEqual(512, (build_dir / "boot/stage1.bin").stat().st_size)

            for relative in ("boot/stage2.elf", "kernel/kernel.elf"):
                self._assert_elf32_i386(workspace, build_dir / relative)
            for relative in ("boot/stage2.bin", "kernel/kernel.bin"):
                self.assertGreater((build_dir / relative).stat().st_size, 0)
            for relative in ("boot/stage2.map", "kernel/kernel.map"):
                self.assertGreater((build_dir / relative).stat().st_size, 0)
            for relative in ("boot/stage2.sym", "kernel/kernel.sym"):
                self._assert_sorted_symbols(build_dir / relative)
            self.assertEqual([], self._generated_in_source(workspace))

    def test_tool_overrides_parallel_build_and_failure_status(self) -> None:
        with self._workspace() as workspace:
            wrappers = workspace / "wrapper_tools"
            logs = workspace / "wrapper_logs"
            wrappers.mkdir()
            logs.mkdir()
            for name in ("gcc", "ld", "objcopy", "nm"):
                self._write_wrapper(
                    wrappers / f"i686-elf-{name}",
                    self._resolve_tool(workspace, f"i686-elf-{name}"),
                    logs / f"{name}.log",
                )
            self._write_wrapper(
                wrappers / "nasm-override",
                self._resolve_tool(workspace, "nasm"),
                logs / "nasm.log",
            )
            self._write_wrapper(
                wrappers / "python-override",
                self._resolve_tool(workspace, "python3"),
                logs / "python.log",
            )

            build_dir = workspace / "out-tree"
            variables = (
                f"CROSS_COMPILE={wrappers / 'i686-elf-'}",
                f"NASM={wrappers / 'nasm-override'}",
                f"PYTHON={wrappers / 'python-override'}",
                f"BUILD_DIR={build_dir}",
            )
            result = self._make(workspace, "-j4", "image", *variables)
            self._assert_success(result)
            self.assertFalse((workspace / "build").exists(), "BUILD_DIR 覆盖后仍写入默认 build/")
            self.assertTrue((build_dir / IMAGE_NAME).is_file())

            gcc_arguments = (logs / "gcc.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(set(), KERNEL_C_FLAGS - set(gcc_arguments))
            nasm_arguments = (logs / "nasm.log").read_text(encoding="utf-8").splitlines()
            self.assertIn("bin", nasm_arguments)
            self.assertIn("elf32", nasm_arguments)
            ld_arguments = (logs / "ld.log").read_text(encoding="utf-8").splitlines()
            self.assertTrue(any(argument.endswith("boot/stage2/linker.ld") for argument in ld_arguments))
            self.assertTrue(any(argument.endswith("kernel/linker.ld") for argument in ld_arguments))
            self.assertTrue(any(argument == "-Map" or argument.startswith("-Map=") for argument in ld_arguments))
            self.assertIn("tools/make_image.py", (logs / "python.log").read_text(encoding="utf-8"))

        with self._workspace() as workspace:
            wrappers = workspace / "failing-tools"
            wrappers.mkdir()
            failing_gcc = wrappers / "i686-elf-gcc"
            failing_gcc.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
            failing_gcc.chmod(failing_gcc.stat().st_mode | stat.S_IXUSR)
            for name in ("ld", "objcopy", "nm"):
                path = wrappers / f"i686-elf-{name}"
                path.symlink_to(self._resolve_tool(workspace, f"i686-elf-{name}"))
            result = self._make(
                workspace,
                "-j4",
                "all",
                f"CROSS_COMPILE={wrappers / 'i686-elf-'}",
            )
            self.assertNotEqual(0, result.returncode, "编译器失败被构建系统吞掉")

    def test_incremental_build_is_exact_and_kernel_dependency_is_selective(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "image")
            self._assert_success(result)
            build_dir = self._build_dir(workspace)
            before = self._snapshot(build_dir)

            result = self._make(workspace, "image")
            self._assert_success(result)
            self.assertNotRegex(
                result.stdout,
                r"(?i)(?:i686-elf-|nasm|make_image\.py|\.(?:asm|c|ld|o|elf|bin|img)\b)",
                "无变更构建仍输出编译、链接或镜像命令",
            )
            self.assertEqual(before, self._snapshot(build_dir), "无变更构建修改了产物")

            source = workspace / "kernel/core/kernel.c"
            old_stat = source.stat()
            related_artifacts = (
                "kernel/core/kernel.o",
                "kernel/core/kernel.d",
                "kernel/kernel.elf",
                "kernel/kernel.bin",
                "kernel/kernel.map",
                "kernel/kernel.sym",
                IMAGE_NAME,
            )
            newest_artifact = max(before[path][0] for path in related_artifacts)
            future = max(old_stat.st_mtime_ns, newest_artifact) + 2_000_000_000
            os.utime(source, ns=(old_stat.st_atime_ns, future))
            touched_mtime = source.stat().st_mtime_ns
            self.assertGreater(
                touched_mtime,
                newest_artifact,
                "DrvFS 触碰后的内核源码没有严格晚于依赖产物",
            )
            result = self._make(workspace, "image")
            self._assert_success(result)
            after = self._snapshot(build_dir)

            protected = [
                path
                for path in before
                if path == "boot/stage1.bin" or path.startswith("boot/stage2")
            ]
            self.assertTrue(protected)
            for path in protected:
                self.assertEqual(before[path], after[path], f"内核变更误重建了 {path}")
            for path in related_artifacts:
                self.assertIn(path, before)
                self.assertIn(path, after)
                self.assertGreater(after[path][0], before[path][0], f"内核链未重建：{path}")

    def test_image_matches_layout_and_unoccupied_samples_are_zero(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "image")
            self._assert_success(result)
            build_dir = self._build_dir(workspace)
            layout = json.loads((workspace / "config/image-layout.json").read_text(encoding="utf-8"))
            image = (build_dir / IMAGE_NAME).read_bytes()
            sector_size = layout["sector_size"]
            self.assertEqual(layout["image_size_bytes"], len(image))

            occupied: list[tuple[int, int]] = []
            candidates = {len(image) - sector_size}
            for component in layout["components"]:
                payload = (build_dir / component["artifact"]).read_bytes()
                offset = component["lba"] * sector_size
                self.assertEqual(payload, image[offset : offset + len(payload)])
                occupied.append((offset, offset + len(payload)))
                padded_end = ((offset + len(payload) + sector_size - 1) // sector_size) * sector_size
                self.assertEqual(
                    b"\0" * (padded_end - offset - len(payload)),
                    image[offset + len(payload) : padded_end],
                    f"组件尾部填充不是零：{component['name']}",
                )
                candidates.add(padded_end)
                candidates.add((component["lba"] + component["max_sectors"]) * sector_size)

            checked = 0
            for offset in sorted(candidates):
                if offset < 0 or offset + sector_size > len(image):
                    continue
                if any(start < offset + sector_size and offset < end for start, end in occupied):
                    continue
                self.assertEqual(b"\0" * sector_size, image[offset : offset + sector_size])
                checked += 1
            self.assertGreaterEqual(checked, 3, "镜像未占用区域抽样不足")

            independent_outputs = (
                workspace / "independent-one.img",
                workspace / "independent-two.img",
            )
            for output in independent_outputs:
                result = self._run(
                    workspace,
                    "python3",
                    "tools/make_image.py",
                    "--layout",
                    str(workspace / "config/image-layout.json"),
                    "--build-dir",
                    str(build_dir),
                    "--output",
                    str(output),
                )
                self._assert_success(result)
            hashes = {
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (*independent_outputs, build_dir / IMAGE_NAME)
            }
            self.assertEqual(1, len(hashes), "相同输入没有生成确定的完整镜像")

    def test_clean_is_scoped_and_alternate_build_dir_works(self) -> None:
        with self._workspace() as workspace:
            marker = workspace / "boot/keep-source.txt"
            marker.write_text("keep\n", encoding="utf-8")
            build_dir = workspace / "alternate-build"
            result = self._make(workspace, "-j4", "image", f"BUILD_DIR={build_dir}")
            self._assert_success(result)
            self.assertTrue((build_dir / IMAGE_NAME).is_file())
            result = self._make(workspace, "clean", f"BUILD_DIR={build_dir}")
            self._assert_success(result)
            self.assertFalse(build_dir.exists(), "clean 未删除所选 BUILD_DIR")
            self.assertEqual("keep\n", marker.read_text(encoding="utf-8"))
            self.assertTrue((workspace / "config/image-layout.json").is_file())

    def test_image_tool_rejects_invalid_inputs_without_clobbering_output(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            source_build = self._build_dir(workspace)
            layout = json.loads((workspace / "config/image-layout.json").read_text(encoding="utf-8"))

            invalid_layouts: list[tuple[str, object]] = []

            def changed(name: str) -> dict[str, object]:
                value = copy.deepcopy(layout)
                invalid_layouts.append((name, value))
                return value

            invalid_layouts.append(("root-array", []))
            value = changed("unknown-root-field")
            value["unknown"] = 1
            for field in ("format_version", "sector_size", "image_size_bytes", "components"):
                value = changed(f"missing-root-{field}")
                del value[field]
            for name, field, replacement in (
                ("bool-format", "format_version", True),
                ("unsupported-format", "format_version", 2),
                ("bool-sector", "sector_size", True),
                ("string-sector", "sector_size", "512"),
                ("zero-sector", "sector_size", 0),
                ("negative-sector", "sector_size", -512),
                ("unsupported-sector", "sector_size", 1024),
                ("non-divisor-sector", "sector_size", 513),
                ("bool-image-size", "image_size_bytes", True),
                ("string-image-size", "image_size_bytes", "67108864"),
                ("zero-image-size", "image_size_bytes", 0),
                ("negative-image-size", "image_size_bytes", -512),
                ("non-sector-multiple-image", "image_size_bytes", 64 * 1024 * 1024 + 1),
                ("components-object", "components", {}),
                ("components-empty", "components", []),
            ):
                value = changed(name)
                value[field] = replacement

            for field in ("name", "artifact", "lba", "max_sectors"):
                value = changed(f"missing-component-{field}")
                del value["components"][0][field]
            value = changed("unknown-component-field")
            value["components"][0]["unknown"] = 1
            for name, field, replacement in (
                ("bool-name", "name", True),
                ("empty-name", "name", ""),
                ("bool-artifact", "artifact", True),
                ("empty-artifact", "artifact", ""),
                ("absolute-artifact", "artifact", "/tmp/foreign.bin"),
                ("parent-artifact", "artifact", "../foreign.bin"),
                ("nested-parent-artifact", "artifact", "boot/../foreign.bin"),
                ("bool-lba", "lba", True),
                ("string-lba", "lba", "0"),
                ("negative-lba", "lba", -1),
                ("bool-max-sectors", "max_sectors", True),
                ("string-max-sectors", "max_sectors", "1"),
                ("zero-max-sectors", "max_sectors", 0),
                ("negative-max-sectors", "max_sectors", -1),
            ):
                value = changed(name)
                value["components"][0][field] = replacement
            value = changed("duplicate-name")
            value["components"][1]["name"] = value["components"][0]["name"]
            value = changed("overlapping-components")
            value["components"][1]["lba"] = value["components"][0]["lba"]
            value = changed("component-out-of-image")
            value["components"][2]["lba"] = (
                value["image_size_bytes"] // value["sector_size"]
            )

            cases: list[tuple[str, Path, Path]] = []
            layout_dir = workspace / "invalid-layouts"
            layout_dir.mkdir()
            for name, invalid_layout in invalid_layouts:
                layout_path = layout_dir / f"{name}.json"
                layout_path.write_text(json.dumps(invalid_layout), encoding="utf-8")
                cases.append((name, layout_path, source_build))

            missing_build = workspace / "missing-component"
            shutil.copytree(source_build, missing_build)
            (missing_build / "kernel/kernel.elf").unlink()
            cases.append(("missing-component", workspace / "config/image-layout.json", missing_build))

            oversized_build = workspace / "oversized-component"
            shutil.copytree(source_build, oversized_build)
            (oversized_build / "boot/stage1.bin").write_bytes(b"X" * 513)
            cases.append(("oversized-component", workspace / "config/image-layout.json", oversized_build))

            for name, layout_path, build_dir in cases:
                with self.subTest(name=name):
                    output = workspace / f"{name}.img"
                    marker = f"preserve-{name}".encode()
                    output.write_bytes(marker)
                    result = self._run(
                        workspace,
                        "python3",
                        "tools/make_image.py",
                        "--layout",
                        str(layout_path),
                        "--build-dir",
                        str(build_dir),
                        "--output",
                        str(output),
                    )
                    self.assertNotEqual(0, result.returncode, f"{name} 被错误接受")
                    self.assertEqual(marker, output.read_bytes(), f"{name} 失败覆盖了既有目标")

    def test_image_tool_write_failure_is_atomic(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            output_dir = workspace / "atomic-output"
            output_dir.mkdir()
            output = output_dir / IMAGE_NAME
            marker = b"preserve-image-before-write-failure"
            output.write_bytes(marker)
            before = output.stat()

            result = self._run(
                workspace,
                "python3",
                "tools/make_image.py",
                "--layout",
                str(workspace / "config/image-layout.json"),
                "--build-dir",
                str(self._build_dir(workspace)),
                "--output",
                str(output),
                file_size_limit=1024 * 1024,
            )

            self.assertNotEqual(0, result.returncode, "写入阶段文件大小限制未使镜像生成失败")
            self.assertEqual(marker, output.read_bytes(), "写入中途失败覆盖了既有镜像")
            after = output.stat()
            self.assertEqual(
                (before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns),
                (after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns),
                "写入中途失败改变了既有镜像 metadata",
            )
            self.assertEqual([output], list(output_dir.iterdir()), "写入失败残留临时文件")


if __name__ == "__main__":
    unittest.main()
