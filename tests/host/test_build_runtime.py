"""在专用 WSL 中验证 T02 构建、增量依赖和镜像行为。"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path


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
        with tempfile.TemporaryDirectory(prefix="minios-t02-") as temporary_directory:
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
            yield workspace

    def _assert_makefile(self, workspace: Path) -> None:
        self.assertTrue((workspace / "Makefile").is_file(), "缺少顶层 Makefile")

    def _run(
        self,
        workspace: Path,
        *arguments: str,
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["bash", "environment/with-env.sh", *arguments]
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
            future = max(old_stat.st_mtime_ns + 2_000_000_000, os.stat(build_dir).st_mtime_ns + 1)
            os.utime(source, ns=(old_stat.st_atime_ns, future))
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
            for path in (
                "kernel/core/kernel.o",
                "kernel/core/kernel.d",
                "kernel/kernel.elf",
                "kernel/kernel.bin",
                "kernel/kernel.map",
                "kernel/kernel.sym",
                IMAGE_NAME,
            ):
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

            cases: list[tuple[str, Path, Path]] = []
            bad_layout = workspace / "bad-layout.json"
            overlapping = json.loads(json.dumps(layout))
            overlapping["components"][1]["lba"] = overlapping["components"][0]["lba"]
            bad_layout.write_text(json.dumps(overlapping), encoding="utf-8")
            cases.append(("bad-layout", bad_layout, source_build))

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


if __name__ == "__main__":
    unittest.main()
