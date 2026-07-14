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
import time
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows 只收集并跳过真实 WSL 测试
    resource = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[2]
IMAGE_NAME = "miniorangeos.img"
BUILD_MARKER = ".miniorangeos-build-root"
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
    "user/bin/init.elf",
    "user/bin/init.map",
    "user/bin/init.sym",
    "user/bin/echo.elf",
    "user/bin/echo.map",
    "user/bin/echo.sym",
    "user/bin/sh.elf",
    "user/bin/sh.map",
    "user/bin/sh.sym",
    "user/bin/ps.elf",
    "user/bin/ps.map",
    "user/bin/ps.sym",
    "user/bin/memtest.elf",
    "user/bin/memtest.map",
    "user/bin/memtest.sym",
    "user/bin/fault.elf",
    "user/bin/fault.map",
    "user/bin/fault.sym",
    "fs/minifs.img",
    IMAGE_NAME,
)
EXPECTED_DEPFILES = (
    "boot/stage2/entry.d",
    "kernel/arch/x86/entry.d",
    "kernel/core/kernel.d",
    "kernel/proc/elf.d",
    "kernel/proc/program_registry.d",
    "kernel/proc/embedded_programs.d",
    "kernel/drivers/ata.d",
    "kernel/block/block.d",
    "kernel/fs/minifs.d",
    "kernel/fs/vfs.d",
    "user/crt/start.d",
    "user/libc/syscall.d",
    "user/libc/string.d",
    "user/programs/init.d",
    "user/programs/echo.d",
    "user/programs/sh.d",
    "user/programs/ps.d",
    "user/programs/memtest.d",
    "user/programs/fault.d",
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
    def _workspace(self, *, name: str = "workspace") -> Iterator[Path]:
        test_root = ROOT / "build/test-workspaces"
        test_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="minios-t02-", dir=test_root
            ) as temporary_directory:
                workspace = Path(temporary_directory) / name
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
        address_space_limit: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["bash", "environment/with-env.sh", *arguments]

        def apply_resource_limits() -> None:
            assert resource is not None
            if file_size_limit is not None:
                resource.setrlimit(
                    resource.RLIMIT_FSIZE, (file_size_limit, file_size_limit)
                )
                signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
            if address_space_limit is not None:
                resource.setrlimit(
                    resource.RLIMIT_AS, (address_space_limit, address_space_limit)
                )

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
            preexec_fn=(
                apply_resource_limits
                if file_size_limit is not None or address_space_limit is not None
                else None
            ),
        )

    def _make(
        self,
        workspace: Path,
        *arguments: str,
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self._assert_makefile(workspace)
        return self._run(
            workspace,
            "make",
            *arguments,
            timeout=timeout,
            env=env,
        )

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
            for source_root in (
                workspace / "boot",
                workspace / "kernel",
                workspace / "user",
            )
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

    def _source_snapshot(self, workspace: Path) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for relative_root in ("boot", "kernel", "config", "tools"):
            root = workspace / relative_root
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    snapshot[path.relative_to(workspace).as_posix()] = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
        return snapshot

    def _lstat_snapshot(
        self, root: Path
    ) -> dict[str, tuple[str, int, int, int, str]]:
        snapshot: dict[str, tuple[str, int, int, int, str]] = {}

        def visit(directory: Path) -> None:
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    path = Path(entry.path)
                    status = entry.stat(follow_symlinks=False)
                    relative = path.relative_to(root).as_posix()
                    mode = stat.S_IMODE(status.st_mode)
                    if stat.S_ISLNK(status.st_mode):
                        snapshot[relative] = (
                            "symlink",
                            mode,
                            status.st_size,
                            status.st_mtime_ns,
                            os.readlink(path),
                        )
                    elif stat.S_ISREG(status.st_mode):
                        digest = hashlib.sha256()
                        with path.open("rb") as stream:
                            while chunk := stream.read(1024 * 1024):
                                digest.update(chunk)
                        snapshot[relative] = (
                            "file",
                            mode,
                            status.st_size,
                            status.st_mtime_ns,
                            digest.hexdigest(),
                        )
                    elif stat.S_ISDIR(status.st_mode):
                        snapshot[relative] = (
                            "directory",
                            mode,
                            status.st_size,
                            status.st_mtime_ns,
                            "",
                        )
                        visit(path)
                    else:
                        snapshot[relative] = (
                            "other",
                            mode,
                            status.st_size,
                            status.st_mtime_ns,
                            "",
                        )

        visit(root)
        return snapshot

    def _assert_clear_space_rejection(
        self,
        result: subprocess.CompletedProcess[str],
        snapshot_root: Path,
        before: dict[str, tuple[str, int, int, int, str]],
    ) -> None:
        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertRegex(
            output,
            r"(?is)(?:空格.*不支持|不支持.*空格|path.*space.*not supported|space.*path.*not supported)",
            "含空格路径失败时没有给出明确的 parse-time 拒绝信息",
        )
        self.assertLessEqual(
            len(output.encode("utf-8")),
            4096,
            "含空格路径拒绝产生了异常庞大的 Make 诊断",
        )
        self.assertEqual(
            before,
            self._lstat_snapshot(snapshot_root),
            "含空格路径拒绝前后工作区 lstat 快照发生变化",
        )

    def _assert_unsafe_make_value_rejection(
        self,
        workspace: Path,
        target: str,
        variable: str,
        value: str,
        marker: Path,
        make_prefix: tuple[str, ...] = (),
        gate_overrides: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        snapshot_root = workspace.parent
        before = self._lstat_snapshot(snapshot_root)
        result = self._make(
            workspace,
            *make_prefix,
            target,
            f"{variable}={value}",
            *gate_overrides,
            env=env,
        )
        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertRegex(
            output,
            r"(?is)(?:危险字符.*不支持|不支持.*危险字符|unsafe.*(?:make|shell).*(?:value|variable)|(?:make|shell).*(?:value|variable).*unsafe)",
            "危险 Make 变量没有在 parse-time 给出清晰拒绝信息",
        )
        self.assertLessEqual(
            len(output.encode("utf-8")),
            4096,
            "危险 Make 变量拒绝产生了异常庞大的诊断",
        )
        self.assertFalse(marker.exists(), "危险 Make 变量执行了注入 helper")
        self.assertEqual(
            before,
            self._lstat_snapshot(snapshot_root),
            "危险 Make 变量拒绝前后工作区 lstat 快照发生变化",
        )

    def _image_command(
        self, workspace: Path, build_dir: Path, output: Path, layout: Path | None = None
    ) -> list[str]:
        return [
            "bash",
            "environment/with-env.sh",
            "python3",
            "tools/make_image.py",
            "--layout",
            str(layout or workspace / "config/image-layout.json"),
            "--build-dir",
            str(build_dir),
            "--output",
            str(output),
        ]

    def _single_component_layout(
        self,
        workspace: Path,
        name: str,
        artifact: str,
        image_size: int = 2 * 1024 * 1024,
    ) -> Path:
        layout = {
            "format_version": 1,
            "sector_size": 512,
            "image_size_bytes": image_size,
            "components": [
                {
                    "name": name,
                    "artifact": artifact,
                    "lba": 0,
                    "max_sectors": image_size // 512,
                }
            ],
        }
        path = workspace / f"{name}-layout.json"
        path.write_text(json.dumps(layout), encoding="utf-8")
        return path

    def _run_hooked_process(
        self,
        workspace: Path,
        command: list[str],
        hook_variable: str,
        hook_name: str,
        mutate: Callable[[], None],
    ) -> subprocess.CompletedProcess[str]:
        control = Path(
            tempfile.mkdtemp(
                prefix=f"hook-{hook_variable.lower()}-{hook_name.replace(':', '-')}-",
                dir=workspace,
            )
        )
        ready = control / "ready"
        proceed = control / "continue"
        hook_log = control / "hook.log"
        env = os.environ.copy()
        env.update(
            {
                "MINIOS_TEST_MODE": "1",
                hook_variable: hook_name,
                "MINIOS_TEST_HOOK_READY": str(ready),
                "MINIOS_TEST_HOOK_CONTINUE": str(proceed),
                "MINIOS_TEST_HOOK_LOG": str(hook_log),
            }
        )
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + 10
        while not ready.is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready.is_file():
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(
                f"测试 hook 未到达：{hook_name}; rc={process.returncode}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            )
        try:
            mutate()
            proceed.write_text("continue\n", encoding="utf-8")
            stdout, stderr = process.communicate(timeout=30)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        self.assertTrue(hook_log.is_file(), f"测试 hook 没有记录阶段：{hook_name}")
        self.assertEqual(
            [hook_name],
            hook_log.read_text(encoding="utf-8").splitlines(),
            f"测试 hook 阶段或调用次数错误：{hook_name}",
        )
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

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

            for relative in (
                "boot/stage2.elf",
                "kernel/kernel.elf",
                "user/bin/init.elf",
            ):
                self._assert_elf32_i386(workspace, build_dir / relative)
            for relative in ("boot/stage2.bin", "kernel/kernel.bin"):
                self.assertGreater((build_dir / relative).stat().st_size, 0)
            for relative in (
                "boot/stage2.map",
                "kernel/kernel.map",
                "user/bin/init.map",
            ):
                self.assertGreater((build_dir / relative).stat().st_size, 0)
            for relative in (
                "boot/stage2.sym",
                "kernel/kernel.sym",
                "user/bin/init.sym",
            ):
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
            self.assertTrue(any(argument.endswith("user/linker.ld") for argument in ld_arguments))
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
            self.assertGreaterEqual(
                checked,
                2,
                "MiniFS 占满镜像尾部后仍应抽样 Stage 2 与 Kernel 预留区",
            )

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

    def test_clean_and_distclean_are_owned_idempotent_and_scoped(self) -> None:
        for target in ("clean", "distclean"):
            for relative_build_dir in ("build", "alternate-build"):
                with self.subTest(target=target, build_dir=relative_build_dir):
                    with self._workspace() as workspace:
                        source_before = self._source_snapshot(workspace)
                        build_dir = workspace / relative_build_dir
                        variables = (
                            ()
                            if relative_build_dir == "build"
                            else (f"BUILD_DIR={build_dir}",)
                        )
                        result = self._make(workspace, "-j4", "all", *variables)
                        self._assert_success(result)
                        marker = build_dir / BUILD_MARKER
                        self.assertTrue(
                            marker.is_file() and not marker.is_symlink(),
                            f"构建未创建可信归属标记：{marker}",
                        )
                        result = self._make(workspace, target, *variables)
                        self._assert_success(result)
                        self.assertFalse(build_dir.exists())
                        result = self._make(workspace, target, *variables)
                        self._assert_success(result)
                        self.assertFalse(build_dir.exists())
                        self.assertEqual(source_before, self._source_snapshot(workspace))

    def test_clean_and_distclean_reject_unowned_or_dangerous_paths(self) -> None:
        dangerous_names = (
            "boot",
            "kernel",
            "config",
            "tools",
            "unknown-existing",
            "symlink-to-source",
            "symlink-outside",
        )
        for target in ("clean", "distclean"):
            for name in dangerous_names:
                with self.subTest(target=target, name=name):
                    with self._workspace() as workspace:
                        source_before = self._source_snapshot(workspace)
                        external = workspace.parent / "foreign-clean-target"
                        external.mkdir()
                        external_sentinel = external / "sentinel.txt"
                        external_sentinel.write_text("foreign\n", encoding="utf-8")
                        build_dir = workspace / name
                        if name == "unknown-existing":
                            build_dir.mkdir()
                            (build_dir / "sentinel.txt").write_text(
                                "unknown\n", encoding="utf-8"
                            )
                        elif name == "symlink-to-source":
                            build_dir.symlink_to(workspace / "boot", target_is_directory=True)
                        elif name == "symlink-outside":
                            build_dir.symlink_to(external, target_is_directory=True)

                        result = self._make(
                            workspace, target, f"BUILD_DIR={build_dir}"
                        )

                        self.assertNotEqual(
                            0, result.returncode, f"{target} 接受危险路径：{name}"
                        )
                        self.assertEqual(source_before, self._source_snapshot(workspace))
                        self.assertEqual(
                            "foreign\n",
                            external_sentinel.read_text(encoding="utf-8"),
                        )
                        self.assertTrue(os.path.lexists(build_dir))

    def test_cleanup_marker_cannot_be_copied_to_claim_foreign_directory(self) -> None:
        with self._workspace() as workspace:
            owned = workspace / "owned-build"
            result = self._make(workspace, "all", f"BUILD_DIR={owned}")
            self._assert_success(result)
            marker = owned / BUILD_MARKER
            self.assertTrue(marker.is_file(), "构建根缺少归属标记")
            for target in ("clean", "distclean"):
                with self.subTest(target=target):
                    foreign = workspace / f"foreign-{target}"
                    foreign.mkdir()
                    shutil.copy2(marker, foreign / BUILD_MARKER)
                    sentinel = foreign / "sentinel.txt"
                    sentinel.write_text("foreign\n", encoding="utf-8")
                    result = self._make(
                        workspace, target, f"BUILD_DIR={foreign}"
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("foreign\n", sentinel.read_text(encoding="utf-8"))

    def test_cleanup_marker_accepts_only_synchronized_drvfs_device_rebase(self) -> None:
        with self._workspace() as workspace:
            build_dir = self._build_dir(workspace)
            marker = build_dir / BUILD_MARKER

            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            value = json.loads(marker.read_text(encoding="utf-8"))
            value["repo_dev"] += 1000
            value["build_dev"] += 1000
            marker.write_text(
                json.dumps(value, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            result = self._make(workspace, "clean")
            self._assert_success(result)
            self.assertFalse(build_dir.exists())

            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            sentinel = build_dir / "preserve-on-asymmetric-device"
            sentinel.write_text("preserve\n", encoding="utf-8")
            value = json.loads(marker.read_text(encoding="utf-8"))
            value["repo_dev"] += 1000
            marker.write_text(
                json.dumps(value, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            result = self._make(workspace, "clean")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("preserve\n", sentinel.read_text(encoding="utf-8"))

    def test_public_cleanup_targets_bind_validated_directory_identity(self) -> None:
        for target in ("clean", "distclean"):
            with self.subTest(target=target):
                with self._workspace() as workspace:
                    build_dir = workspace / "race-build"
                    variables = (f"BUILD_DIR={build_dir}",)
                    command = [
                        "bash",
                        "environment/with-env.sh",
                        "make",
                        target,
                        *variables,
                    ]
                    hook_name = f"cleanup-after-validation-before-remove:{target}"

                    result = self._make(workspace, "all", *variables)
                    self._assert_success(result)
                    self.assertTrue((build_dir / BUILD_MARKER).is_file())
                    disabled_control = workspace / f"cleanup-hook-disabled-{target}"
                    disabled_control.mkdir()
                    disabled_ready = disabled_control / "ready"
                    disabled_continue = disabled_control / "continue"
                    disabled_log = disabled_control / "hook.log"
                    disabled_continue.write_text("continue\n", encoding="utf-8")
                    disabled_env = os.environ.copy()
                    disabled_env.pop("MINIOS_TEST_MODE", None)
                    disabled_env.update(
                        {
                            "MINIOS_CLEAN_TEST_HOOK": hook_name,
                            "MINIOS_TEST_HOOK_READY": str(disabled_ready),
                            "MINIOS_TEST_HOOK_CONTINUE": str(disabled_continue),
                            "MINIOS_TEST_HOOK_LOG": str(disabled_log),
                        }
                    )
                    result = self._run(
                        workspace,
                        "make",
                        target,
                        *variables,
                        env=disabled_env,
                    )
                    self._assert_success(result)
                    self.assertFalse(build_dir.exists())
                    self.assertFalse(
                        disabled_ready.exists(),
                        "未启用测试模式时 cleanup hook 仍创建 ready",
                    )
                    self.assertFalse(
                        disabled_log.exists(),
                        "未启用测试模式时 cleanup hook 仍写入 log",
                    )

                    result = self._make(workspace, "all", *variables)
                    self._assert_success(result)
                    self.assertTrue((build_dir / BUILD_MARKER).is_file())
                    result = self._run_hooked_process(
                        workspace,
                        command,
                        "MINIOS_CLEAN_TEST_HOOK",
                        hook_name,
                        lambda: None,
                    )
                    self._assert_success(result)
                    self.assertFalse(build_dir.exists())

                    result = self._make(workspace, "all", *variables)
                    self._assert_success(result)
                    valid_probe = workspace / "race-build-valid-probe"
                    build_dir.rename(valid_probe)
                    result = self._make(workspace, "all", *variables)
                    self._assert_success(result)
                    probe_current = workspace / "race-build-probe-current"
                    build_dir.rename(probe_current)
                    valid_probe.rename(build_dir)
                    result = self._make(workspace, target, *variables)
                    self._assert_success(result)
                    self.assertFalse(build_dir.exists())
                    probe_current.rename(build_dir)

                    replacement = workspace / "race-build-replacement"
                    build_dir.rename(replacement)
                    replacement_before = self._lstat_snapshot(replacement)
                    result = self._make(workspace, "all", *variables)
                    self._assert_success(result)
                    original = workspace / "race-build-original"
                    source_before = self._source_snapshot(workspace)

                    def replace_with_valid_owned_directory() -> None:
                        build_dir.rename(original)
                        replacement.rename(build_dir)

                    result = self._run_hooked_process(
                        workspace,
                        command,
                        "MINIOS_CLEAN_TEST_HOOK",
                        hook_name,
                        replace_with_valid_owned_directory,
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(
                        replacement_before, self._lstat_snapshot(build_dir)
                    )
                    self.assertTrue((build_dir / BUILD_MARKER).is_file())
                    self.assertTrue((original / BUILD_MARKER).is_file())
                    self.assertEqual(source_before, self._source_snapshot(workspace))

    def test_repository_space_path_is_supported_or_cleanly_rejected(self) -> None:
        with self._workspace(name="workspace with space") as workspace:
            snapshot_root = workspace.parent
            before = self._lstat_snapshot(snapshot_root)
            result = self._make(workspace, "-j4", "image")
            if result.returncode == 0:
                self.assertTrue((workspace / "build" / IMAGE_NAME).is_file())
            else:
                self._assert_clear_space_rejection(
                    result,
                    snapshot_root,
                    before,
                )

    def test_build_dir_space_path_is_supported_or_cleanly_rejected(self) -> None:
        with self._workspace() as workspace:
            build_dir = workspace / "out tree"
            snapshot_root = workspace.parent
            before = self._lstat_snapshot(snapshot_root)
            result = self._make(
                workspace, "-j4", "image", f"BUILD_DIR={build_dir}"
            )
            if result.returncode == 0:
                self.assertTrue((build_dir / IMAGE_NAME).is_file())
            else:
                self._assert_clear_space_rejection(
                    result,
                    snapshot_root,
                    before,
                )

    def test_tool_space_paths_are_supported_or_cleanly_rejected(self) -> None:
        with self._workspace() as workspace:
            wrappers = workspace / "tool wrappers"
            logs = workspace / "tool wrapper logs"
            wrappers.mkdir()
            logs.mkdir()
            log_paths: list[Path] = []
            for name in ("gcc", "ld", "objcopy", "nm"):
                log = logs / f"{name}.log"
                log_paths.append(log)
                self._write_wrapper(
                    wrappers / f"i686-elf-{name}",
                    self._resolve_tool(workspace, f"i686-elf-{name}"),
                    log,
                )
            for executable, real_name in (
                ("nasm override", "nasm"),
                ("python override", "python3"),
            ):
                log = logs / f"{real_name}.log"
                log_paths.append(log)
                self._write_wrapper(
                    wrappers / executable,
                    self._resolve_tool(workspace, real_name),
                    log,
                )
            snapshot_root = workspace.parent
            before = self._lstat_snapshot(snapshot_root)
            result = self._make(
                workspace,
                "-j4",
                "image",
                f"CROSS_COMPILE={wrappers / 'i686-elf-'}",
                f"NASM={wrappers / 'nasm override'}",
                f"PYTHON={wrappers / 'python override'}",
            )
            if result.returncode == 0:
                self.assertTrue((workspace / "build" / IMAGE_NAME).is_file())
                for log in log_paths:
                    self.assertGreater(log.stat().st_size, 0)
            else:
                self._assert_clear_space_rejection(
                    result,
                    snapshot_root,
                    before,
                )

    def test_make_variables_reject_command_injection_before_side_effects(self) -> None:
        variables = (
            ("BUILD_DIR", "unsafe-build"),
            ("CROSS_COMPILE", "i686-elf-"),
            ("NASM", "nasm"),
            ("PYTHON", "python3"),
        )
        targets = ("all", "image", "clean", "distclean")
        gate_variables = (
            "unsafe_make_value",
            "make_dollar",
            "left_parenthesis",
            "right_parenthesis",
        )
        for variable_index, (variable, base) in enumerate(variables):
            for payload_index, payload_name in enumerate(
                ("backtick", "make-shell", "shell-dollar", "semicolon")
            ):
                target = targets[(variable_index + payload_index) % len(targets)]
                for bypass_mode in ("command-line", "environment-e"):
                    with self.subTest(
                        variable=variable,
                        payload=payload_name,
                        target=target,
                        bypass=bypass_mode,
                    ):
                        with self._workspace() as workspace:
                            marker = workspace / "make-variable-injection-ran"
                            helper = workspace / "make-variable-injection-helper"
                            helper.write_text(
                                "#!/usr/bin/env bash\n"
                                "set -eu\n"
                                f": > {shlex.quote(str(marker))}\n",
                                encoding="utf-8",
                            )
                            helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
                            if payload_name == "backtick":
                                value = f"{base}`{helper}`"
                            elif payload_name == "make-shell":
                                value = f"{base}$(shell {helper})"
                            elif payload_name == "shell-dollar":
                                value = f"{base}$$({helper})"
                            else:
                                value = f"{base};{helper}"

                            make_prefix: tuple[str, ...] = ()
                            gate_overrides: tuple[str, ...] = ()
                            env: dict[str, str] | None = None
                            if bypass_mode == "command-line":
                                gate_overrides = tuple(
                                    f"{name}=" for name in gate_variables
                                )
                            else:
                                make_prefix = ("-e",)
                                env = os.environ.copy()
                                env.update({name: "" for name in gate_variables})
                            self._assert_unsafe_make_value_rejection(
                                workspace,
                                target,
                                variable,
                                value,
                                marker,
                                make_prefix,
                                gate_overrides,
                                env,
                            )

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

    def test_image_tool_rejects_unsafe_artifact_and_directory_types(self) -> None:
        kinds = (
            "final-symlink",
            "hardlink",
            "fifo",
            "directory",
            "intermediate-symlink-inside",
            "intermediate-symlink-outside",
            "build-dir-intermediate-symlink",
            "output-parent-symlink",
        )
        for kind in kinds:
            with self.subTest(kind=kind):
                with self._workspace() as workspace:
                    result = self._make(workspace, "-j4", "all")
                    self._assert_success(result)
                    source_build = self._build_dir(workspace)
                    case_root = workspace / f"type-{kind}"
                    case_root.mkdir()
                    build_dir = case_root / "build"
                    shutil.copytree(source_build, build_dir)
                    external = workspace.parent / f"external-{kind}"
                    external.mkdir()
                    external_sentinel = external / "sentinel.txt"
                    external_sentinel.write_text("foreign\n", encoding="utf-8")
                    output_parent = case_root / "output"
                    output_parent.mkdir()
                    output = output_parent / IMAGE_NAME
                    marker = f"preserve-{kind}".encode()
                    output.write_bytes(marker)
                    fifo_descriptor: int | None = None

                    artifact = build_dir / "kernel/kernel.elf"
                    external_artifact = external / "kernel.elf"
                    shutil.copy2(artifact, external_artifact)
                    layout_artifact = "kernel/kernel.elf"
                    if kind == "final-symlink":
                        artifact.unlink()
                        artifact.symlink_to(external_artifact)
                    elif kind == "hardlink":
                        artifact.unlink()
                        os.link(external_artifact, artifact)
                    elif kind == "fifo":
                        artifact.unlink()
                        os.mkfifo(artifact)
                        fifo_descriptor = os.open(
                            artifact, os.O_RDWR | getattr(os, "O_NONBLOCK", 0)
                        )
                    elif kind == "directory":
                        artifact.unlink()
                        artifact.mkdir()
                    elif kind == "intermediate-symlink-inside":
                        layout_artifact = "boot/stage2.bin"
                        boot = build_dir / "boot"
                        boot.rename(build_dir / "boot-real")
                        boot.symlink_to("boot-real", target_is_directory=True)
                    elif kind == "intermediate-symlink-outside":
                        layout_artifact = "boot/stage2.bin"
                        external_boot = external / "boot"
                        shutil.copytree(build_dir / "boot", external_boot)
                        shutil.rmtree(build_dir / "boot")
                        (build_dir / "boot").symlink_to(
                            external_boot, target_is_directory=True
                        )
                    elif kind == "build-dir-intermediate-symlink":
                        actual_parent = case_root / "actual-parent"
                        actual_parent.mkdir()
                        build_dir.rename(actual_parent / "build")
                        alias = case_root / "build-parent-alias"
                        alias.symlink_to(actual_parent, target_is_directory=True)
                        build_dir = alias / "build"
                    elif kind == "output-parent-symlink":
                        real_output = case_root / "real-output"
                        output.unlink()
                        output_parent.rmdir()
                        real_output.mkdir()
                        output_parent.symlink_to(real_output, target_is_directory=True)
                        output = output_parent / IMAGE_NAME
                        output.write_bytes(marker)

                    external_before = {
                        path.relative_to(external).as_posix(): hashlib.sha256(
                            path.read_bytes()
                        ).hexdigest()
                        for path in external.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    }
                    layout_path = self._single_component_layout(
                        workspace,
                        f"type-{kind}",
                        layout_artifact,
                    )

                    try:
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
                    finally:
                        if fifo_descriptor is not None:
                            os.close(fifo_descriptor)

                    self.assertNotEqual(0, result.returncode, f"不安全路径被接受：{kind}")
                    self.assertEqual(marker, output.read_bytes())
                    self.assertEqual(
                        "foreign\n", external_sentinel.read_text(encoding="utf-8")
                    )
                    external_after = {
                        path.relative_to(external).as_posix(): hashlib.sha256(
                            path.read_bytes()
                        ).hexdigest()
                        for path in external.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    }
                    self.assertEqual(external_before, external_after)
                    self.assertEqual(
                        [],
                        [path for path in output.parent.iterdir() if ".tmp-" in path.name],
                    )

    def test_image_test_hooks_are_disabled_without_explicit_test_mode(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            output = workspace / "default-hook-disabled.img"
            layout_path = self._single_component_layout(
                workspace, "hook-disabled", "boot/stage1.bin"
            )
            ready = workspace / "unexpected-hook-ready"
            env = os.environ.copy()
            env.update(
                {
                    "MINIOS_IMAGE_TEST_HOOK": (
                        "artifact-after-validation-before-open:stage1"
                    ),
                    "MINIOS_TEST_HOOK_READY": str(ready),
                    "MINIOS_TEST_HOOK_CONTINUE": str(workspace / "never-created"),
                }
            )
            result = self._run(
                workspace,
                "python3",
                "tools/make_image.py",
                "--layout",
                str(layout_path),
                "--build-dir",
                str(self._build_dir(workspace)),
                "--output",
                str(output),
                env=env,
            )
            self._assert_success(result)
            self.assertFalse(ready.exists(), "未启用测试模式时仍执行了 hook")

    def test_image_artifact_replacement_race_is_rejected(self) -> None:
        with self._workspace() as workspace:
            result = self._make(workspace, "-j4", "all")
            self._assert_success(result)
            source_build = self._build_dir(workspace)
            build_dir = workspace / "artifact-race-build"
            shutil.copytree(source_build, build_dir)
            layout = json.loads(
                (workspace / "config/image-layout.json").read_text(encoding="utf-8")
            )
            layout["image_size_bytes"] = 1024 * 1024
            layout["components"] = [layout["components"][0]]
            layout_path = workspace / "artifact-race-layout.json"
            layout_path.write_text(json.dumps(layout), encoding="utf-8")
            hook_name = "artifact-after-validation-before-open:stage1"
            noop_output = workspace / "artifact-hook-noop.img"
            result = self._run_hooked_process(
                workspace,
                self._image_command(workspace, build_dir, noop_output, layout_path),
                "MINIOS_IMAGE_TEST_HOOK",
                hook_name,
                lambda: None,
            )
            self._assert_success(result)
            self.assertEqual(
                (build_dir / "boot/stage1.bin").read_bytes(),
                noop_output.read_bytes()[:512],
            )

            output = workspace / "artifact-race.img"
            marker = b"preserve-artifact-race"
            output.write_bytes(marker)
            replacement_boot = build_dir / "boot-replacement"
            shutil.copytree(build_dir / "boot", replacement_boot)
            replacement_stage1 = replacement_boot / "stage1.bin"
            replacement_stage1.write_bytes(b"E" * 512)
            replacement_hash = hashlib.sha256(
                replacement_stage1.read_bytes()
            ).hexdigest()
            original_boot = build_dir / "boot-owned"

            def replace_boot_directory() -> None:
                (build_dir / "boot").rename(original_boot)
                replacement_boot.rename(build_dir / "boot")

            result = self._run_hooked_process(
                workspace,
                self._image_command(workspace, build_dir, output, layout_path),
                "MINIOS_IMAGE_TEST_HOOK",
                hook_name,
                replace_boot_directory,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(marker, output.read_bytes())
            self.assertEqual(
                replacement_hash,
                hashlib.sha256(
                    (build_dir / "boot/stage1.bin").read_bytes()
                ).hexdigest(),
            )
            self.assertTrue((build_dir / "boot").is_dir())
            self.assertTrue(original_boot.is_dir())
            self.assertEqual([], [p for p in output.parent.iterdir() if ".tmp-" in p.name])

    def test_image_output_parent_replacement_races_are_rejected(self) -> None:
        for hook_name in (
            "output-parent-after-validation-before-open",
            "output-after-validation-before-commit",
        ):
            with self.subTest(hook=hook_name):
                with self._workspace() as workspace:
                    result = self._make(workspace, "-j4", "all")
                    self._assert_success(result)
                    output_parent = workspace / "race-output"
                    output_parent.mkdir()
                    output = output_parent / IMAGE_NAME
                    marker = f"preserve-{hook_name}".encode()
                    output.write_bytes(marker)
                    original_parent = workspace / "race-output-owned"
                    foreign_parent = workspace.parent / f"foreign-{hook_name}"
                    foreign_parent.mkdir()
                    foreign_output = foreign_parent / IMAGE_NAME
                    foreign_marker = f"foreign-{hook_name}".encode()
                    foreign_output.write_bytes(foreign_marker)
                    layout_path = self._single_component_layout(
                        workspace,
                        f"race-{hook_name}",
                        "boot/stage1.bin",
                    )
                    noop_parent = workspace / "noop-output"
                    noop_parent.mkdir()
                    noop_output = noop_parent / IMAGE_NAME
                    result = self._run_hooked_process(
                        workspace,
                        self._image_command(
                            workspace,
                            self._build_dir(workspace),
                            noop_output,
                            layout_path,
                        ),
                        "MINIOS_IMAGE_TEST_HOOK",
                        hook_name,
                        lambda: None,
                    )
                    self._assert_success(result)
                    self.assertEqual(2 * 1024 * 1024, noop_output.stat().st_size)

                    replacement_parent = workspace / "race-output-replacement"
                    replacement_parent.mkdir()
                    replacement_output = replacement_parent / IMAGE_NAME
                    replacement_output.write_bytes(foreign_marker)

                    def replace_output_parent() -> None:
                        output_parent.rename(original_parent)
                        replacement_parent.rename(output_parent)

                    result = self._run_hooked_process(
                        workspace,
                        self._image_command(
                            workspace,
                            self._build_dir(workspace),
                            output,
                            layout_path,
                        ),
                        "MINIOS_IMAGE_TEST_HOOK",
                        hook_name,
                        replace_output_parent,
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(
                        marker, (original_parent / IMAGE_NAME).read_bytes()
                    )
                    self.assertEqual(
                        foreign_marker, (output_parent / IMAGE_NAME).read_bytes()
                    )
                    self.assertEqual(foreign_marker, foreign_output.read_bytes())
                    original_temporary = [
                        path
                        for path in original_parent.iterdir()
                        if ".tmp-" in path.name
                    ]
                    expected_residue = (
                        1
                        if hook_name == "output-after-validation-before-commit"
                        else 0
                    )
                    self.assertEqual(expected_residue, len(original_temporary))
                    for path in original_temporary:
                        status = path.lstat()
                        self.assertTrue(stat.S_ISREG(status.st_mode))
                        self.assertEqual(1, status.st_nlink)
                        self.assertTrue(path.name.startswith(f".{IMAGE_NAME}.tmp-"))
                    self.assertEqual(
                        [],
                        [
                            path
                            for parent in (output_parent, foreign_parent)
                            for path in parent.iterdir()
                            if ".tmp-" in path.name
                        ],
                    )

    def test_image_generation_streams_large_sparse_artifact_under_memory_limit(self) -> None:
        with self._workspace() as workspace:
            build_dir = workspace / "stream-build"
            build_dir.mkdir()
            artifact = build_dir / "large.bin"
            artifact_size = 80 * 1024 * 1024
            image_size = 96 * 1024 * 1024
            with artifact.open("wb") as stream:
                stream.truncate(artifact_size)
                stream.seek(0)
                stream.write(b"STREAM-BEGIN")
                stream.seek(artifact_size - len(b"STREAM-END"))
                stream.write(b"STREAM-END")
            layout = {
                "format_version": 1,
                "sector_size": 512,
                "image_size_bytes": image_size,
                "components": [
                    {
                        "name": "large",
                        "artifact": "large.bin",
                        "lba": 1,
                        "max_sectors": artifact_size // 512,
                    }
                ],
            }
            layout_path = workspace / "stream-layout.json"
            layout_path.write_text(json.dumps(layout), encoding="utf-8")
            output = workspace / "stream.img"
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
                address_space_limit=48 * 1024 * 1024,
                timeout=120,
            )
            self._assert_success(result)
            self.assertEqual(image_size, output.stat().st_size)
            with output.open("rb") as stream:
                self.assertEqual(b"\0" * 512, stream.read(512))
                self.assertEqual(b"STREAM-BEGIN", stream.read(len(b"STREAM-BEGIN")))
                stream.seek(512 + artifact_size - len(b"STREAM-END"))
                self.assertEqual(b"STREAM-END", stream.read(len(b"STREAM-END")))
                self.assertEqual(b"\0" * 512, stream.read(512))

            expected = hashlib.sha256()
            expected.update(b"\0" * 512)
            with artifact.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    expected.update(chunk)
            remaining = image_size - 512 - artifact_size
            zero_chunk = b"\0" * (1024 * 1024)
            while remaining:
                count = min(remaining, len(zero_chunk))
                expected.update(zero_chunk[:count])
                remaining -= count
            actual = hashlib.sha256()
            with output.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    actual.update(chunk)
            self.assertEqual(expected.hexdigest(), actual.hexdigest())


if __name__ == "__main__":
    unittest.main()
