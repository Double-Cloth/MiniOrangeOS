"""使用临时目录定义 T01 Linux 环境脚本的运行时契约。"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class EnvironmentRuntimeTests(unittest.TestCase):
    def _run_bash(
        self,
        script: str,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", "-c", script],
            cwd=cwd or ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def _run_required(
        self,
        relative_path: str,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = ROOT / relative_path
        self.assertTrue(script.is_file(), f"缺少 T01 文件：{relative_path}")
        return subprocess.run(
            ["/bin/bash", str(script), *arguments],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def _base_env(self, environment_root: Path | str) -> dict[str, str]:
        env = os.environ.copy()
        env["MINIOS_ENV_ROOT"] = str(environment_root)
        return env

    def _path_without_container_engines(self, directory: Path) -> str:
        for command in (
            "basename",
            "cat",
            "cut",
            "date",
            "dirname",
            "grep",
            "id",
            "mkdir",
            "mktemp",
            "readlink",
            "realpath",
            "rm",
            "sed",
            "sha256sum",
            "tr",
            "uname",
        ):
            source = shutil.which(command)
            if source is not None:
                (directory / command).symlink_to(source)
        return str(directory)

    def _write_fake_container_backend(self, directory: Path, backend: str) -> Path:
        self.assertIn(backend, {"podman", "docker"})
        fake_backend = directory / backend
        fake_backend.write_text(
            """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_CONTAINER_LOG"
case " $* " in
  *" inspect "*)
    case "$*" in
      *Labels*|*labels*|*label*) printf '%s\\n' "$FAKE_CONTAINER_LABEL" ;;
      *RepoTags*|*repoTags*|*name*) printf '%s\\n' "$FAKE_CONTAINER_IMAGE_NAME" ;;
      *Id*|*ID*|*id*) printf '%s\\n' "$FAKE_CONTAINER_IMAGE_ID" ;;
      *)
        printf '[{"Id":"%s","RepoTags":["%s"],"Config":{"Labels":{"org.miniorangeos.project":"%s"}}}]\\n' \\
          "$FAKE_CONTAINER_IMAGE_ID" "$FAKE_CONTAINER_IMAGE_NAME" \\
          "$FAKE_CONTAINER_LABEL"
        ;;
    esac
    ;;
  *" images "*) printf '%s\\n' "$FAKE_CONTAINER_IMAGE_ID" ;;
  *" info "*) printf '%s\\n' true ;;
  *" version "*) printf '%s\\n' 'fake container backend 1.0' ;;
  *" rm "*|*" rmi "*) exit 75 ;;
  *) : ;;
esac
""",
            encoding="utf-8",
            newline="\n",
        )
        fake_backend.chmod(0o755)
        return fake_backend

    def _write_container_state(
        self,
        environment_root: Path,
        *,
        image_name: str = "miniorangeos-dev:ubuntu-24.04",
        label: str = "org.miniorangeos.project=MiniOrangeOS",
        image_id: str = "sha256:owned-image-id",
    ) -> None:
        state_directory = environment_root / "state"
        state_directory.mkdir(parents=True)
        (environment_root / "container-storage" / "graphroot").mkdir(parents=True)
        (environment_root / "container-storage" / "runroot").mkdir(parents=True)
        (state_directory / "container.env").write_text(
            f"MINIOS_CONTAINER_IMAGE={image_name}\n"
            f"MINIOS_CONTAINER_LABEL={label}\n"
            f"MINIOS_CONTAINER_IMAGE_ID={image_id}\n"
            "MINIOS_CONTAINER_IMAGE_DIGEST=sha256:owned-image-digest\n",
            encoding="utf-8",
            newline="\n",
        )

    def _write_toolchain_archive(
        self,
        archive: Path,
        source_directory_name: str,
        component: str,
    ) -> str:
        """创建只含 configure 的微型源码包，供构建状态机测试使用。"""
        staging_root = archive.parent / f"{component}-staging"
        source_directory = staging_root / source_directory_name
        source_directory.mkdir(parents=True)
        configure = source_directory / "configure"
        self._write_executable(
            configure,
            "#!/bin/sh\n"
            "set -eu\n"
            f"printf 'configure component={component} cwd=%s args=%s\\n' "
            '"$PWD" "$*" >> "$FAKE_TOOLCHAIN_LOG"\n'
            f"printf '%s\\n' '{component}' > .minios-component\n",
        )
        with tarfile.open(archive, "w:xz") as tar:
            tar.add(source_directory, arcname=source_directory_name)
        shutil.rmtree(staging_root)
        return hashlib.sha256(archive.read_bytes()).hexdigest()

    def _write_fake_make(self, command_directory: Path) -> None:
        self._write_executable(
            command_directory / "make",
            """#!/bin/sh
set -eu
printf 'make cwd=%s args=%s\n' "$PWD" "$*" >> "$FAKE_TOOLCHAIN_LOG"
component=$(cat .minios-component)
case " $* " in
  *" install "*)
    if [ "$component" = "binutils" ]; then
      mkdir -p "$FAKE_TOOLCHAIN_PREFIX/bin"
      cat > "$FAKE_TOOLCHAIN_PREFIX/bin/i686-elf-ld" <<'EOF'
#!/bin/sh
printf 'GNU ld (GNU Binutils) %s\n' "${FAKE_LD_VERSION:-1.0}"
EOF
      chmod +x "$FAKE_TOOLCHAIN_PREFIX/bin/i686-elf-ld"
    fi
    ;;
esac
case " $* " in
  *" install-gcc "*)
    mkdir -p "$FAKE_TOOLCHAIN_PREFIX/bin"
    cat > "$FAKE_TOOLCHAIN_PREFIX/bin/i686-elf-gcc" <<'EOF'
#!/bin/sh
case "${1:-}" in
  -dumpmachine) printf 'i686-elf\n' ;;
  --version) printf 'i686-elf-gcc (GCC) %s\n' "${FAKE_GCC_VERSION:-1.0}" ;;
  -print-libgcc-file-name)
    printf '%s\n' "${FAKE_LIBGCC_PATH:-__MINIOS_LIBGCC__}"
    ;;
  *)
    output=
    previous=
    for argument in "$@"; do
      if [ "$previous" = "-o" ]; then output="$argument"; fi
      previous="$argument"
    done
    case "${FAKE_GCC_COMPILE_MODE:-valid}" in
      valid) printf 'fake-object\n' > "$output" ;;
      empty) : > "$output" ;;
      symlink) ln -s /dev/null "$output" ;;
      missing) : ;;
      *) exit 65 ;;
    esac
    ;;
esac
EOF
    sed -i "s|__MINIOS_LIBGCC__|$FAKE_TOOLCHAIN_PREFIX/lib/gcc/i686-elf/1.0/libgcc.a|" \
      "$FAKE_TOOLCHAIN_PREFIX/bin/i686-elf-gcc"
    chmod +x "$FAKE_TOOLCHAIN_PREFIX/bin/i686-elf-gcc"
    ;;
  *) : ;;
esac
case " $* " in
  *" install-target-libgcc "*)
    mkdir -p "$FAKE_TOOLCHAIN_PREFIX/lib/gcc/i686-elf/1.0"
    printf 'fake-libgcc\n' > \
      "$FAKE_TOOLCHAIN_PREFIX/lib/gcc/i686-elf/1.0/libgcc.a"
    ;;
  *) : ;;
esac
""",
        )

    def _write_toolchain_fixture(
        self, temporary_root: Path
    ) -> tuple[Path, Path, dict[str, str]]:
        """复制最小脚本布局并把固定来源替换为本地可校验源码包。"""
        fixture_root = temporary_root / "repo"
        (fixture_root / "tools").mkdir(parents=True)
        (fixture_root / "environment" / "lib").mkdir(parents=True)
        builder_source = ROOT / "tools" / "build_toolchain.sh"
        self.assertTrue(builder_source.is_file(), "缺少 T01 工具链构建器")
        shutil.copy2(
            builder_source,
            fixture_root / "tools" / "build_toolchain.sh",
        )
        shutil.copy2(
            ROOT / "environment" / "lib" / "common.sh",
            fixture_root / "environment" / "lib" / "common.sh",
        )

        fixture_sources = temporary_root / "fixture-sources"
        fixture_sources.mkdir()
        binutils_archive = fixture_sources / "binutils-1.0.tar.xz"
        gcc_archive = fixture_sources / "gcc-1.0.tar.xz"
        binutils_sha256 = self._write_toolchain_archive(
            binutils_archive, "binutils-1.0", "binutils"
        )
        gcc_sha256 = self._write_toolchain_archive(
            gcc_archive, "gcc-1.0", "gcc"
        )
        (fixture_root / "environment" / "versions.env").write_text(
            "MINIOS_TARGET=i686-elf\n"
            "MINIOS_WSL_DISTRO=MiniOrangeOS-Dev\n"
            "MINIOS_WSL_IMAGE_VERSION=24.04.4\n"
            "MINIOS_WSL_IMAGE_URL=https://example.invalid/rootfs\n"
            f"MINIOS_WSL_IMAGE_SHA256={'1' * 64}\n"
            "MINIOS_CONTAINER_IMAGE=miniorangeos-dev:ubuntu-24.04\n"
            "MINIOS_CONTAINER_LABEL=org.miniorangeos.project=MiniOrangeOS\n"
            "MINIOS_CONTAINER_BASE_IMAGE=ubuntu:noble-test\n"
            f"MINIOS_CONTAINER_BASE_DIGEST=sha256:{'2' * 64}\n"
            "MINIOS_BINUTILS_VERSION=1.0\n"
            f"MINIOS_BINUTILS_URL={binutils_archive.as_uri()}\n"
            f"MINIOS_BINUTILS_SHA256={binutils_sha256}\n"
            "MINIOS_GCC_VERSION=1.0\n"
            f"MINIOS_GCC_URL={gcc_archive.as_uri()}\n"
            f"MINIOS_GCC_SHA256={gcc_sha256}\n",
            encoding="utf-8",
            newline="\n",
        )

        environment_root = temporary_root / "environment root"
        command_directory = temporary_root / "commands"
        command_directory.mkdir()
        self._write_fake_make(command_directory)
        log = temporary_root / "toolchain.log"
        env = self._base_env(environment_root)
        env.update(
            {
                "FAKE_TOOLCHAIN_LOG": str(log),
                "FAKE_TOOLCHAIN_PREFIX": str(environment_root / "toolchain"),
                "MINIOS_BUILD_JOBS": "2",
                "PATH": str(command_directory) + os.pathsep + env["PATH"],
            }
        )
        return fixture_root, log, env

    def _run_fixture_toolchain(
        self,
        fixture_root: Path,
        *arguments: str,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                str(fixture_root / "tools" / "build_toolchain.sh"),
                *arguments,
            ],
            cwd=fixture_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def _replace_fixture_archive(
        self,
        fixture_root: Path,
        component: str,
        archive: Path,
    ) -> None:
        versions_file = fixture_root / "environment" / "versions.env"
        content = versions_file.read_text(encoding="utf-8")
        prefix = f"MINIOS_{component.upper()}"
        lines = []
        for line in content.splitlines():
            if line.startswith(f"{prefix}_URL="):
                line = f"{prefix}_URL={archive.as_uri()}"
            elif line.startswith(f"{prefix}_SHA256="):
                line = f"{prefix}_SHA256={hashlib.sha256(archive.read_bytes()).hexdigest()}"
            lines.append(line)
        versions_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_malicious_toolchain_archive(
        self, archive: Path, member_kind: str
    ) -> None:
        configure_data = b"#!/bin/sh\nexit 0\n"
        configure = tarfile.TarInfo("binutils-1.0/configure")
        configure.mode = 0o755
        configure.size = len(configure_data)
        with tarfile.open(archive, "w:xz") as tar:
            tar.addfile(configure, io.BytesIO(configure_data))
            if member_kind in {"absolute", "dotdot"}:
                name = "/absolute-escape" if member_kind == "absolute" else "../escape"
                payload = b"escape\n"
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                tar.addfile(member, io.BytesIO(payload))
            else:
                member = tarfile.TarInfo("binutils-1.0/unsafe-link")
                member.type = (
                    tarfile.SYMTYPE if member_kind == "symlink" else tarfile.LNKTYPE
                )
                member.linkname = "../../escape"
                tar.addfile(member)

    def test_with_env_rejects_missing_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = self._run_required(
                "environment/with-env.sh",
                env=self._base_env(temporary_directory),
            )
        self.assertNotEqual(0, result.returncode)
        self.assertRegex(
            (result.stdout + result.stderr).lower(),
            r"(?:command|usage|命令|用法)",
        )

    def test_with_env_exposes_fake_tool_only_to_child_process(self) -> None:
        original_path = os.environ.get("PATH", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment_root = Path(temporary_directory)
            tool_directory = environment_root / "toolchain" / "bin"
            tool_directory.mkdir(parents=True)
            fake_tool = tool_directory / "minios-t01-contract-tool"
            fake_tool.write_text(
                "#!/bin/sh\nprintf 'path=%s\\n' \"$PATH\"\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_tool.chmod(0o755)

            result = self._run_required(
                "environment/with-env.sh",
                fake_tool.name,
                env=self._base_env(environment_root),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            child_path = result.stdout.removeprefix("path=").strip()
            self.assertEqual(str(tool_directory), child_path.split(os.pathsep)[0])
            self.assertEqual(
                str(fake_tool), shutil.which(fake_tool.name, path=child_path)
            )

        self.assertEqual(original_path, os.environ.get("PATH", ""))
        self.assertIsNone(shutil.which(fake_tool.name, path=original_path))

    def test_with_env_rejects_dangerous_environment_roots(self) -> None:
        for dangerous_root in ("/", "/usr/local", str(ROOT)):
            with self.subTest(environment_root=dangerous_root):
                result = self._run_required(
                    "environment/with-env.sh",
                    "true",
                    env=self._base_env(dangerous_root),
                )
                self.assertNotEqual(0, result.returncode)
                self.assertRegex(
                    (result.stdout + result.stderr).lower(),
                    r"(?:environment root|env root|环境根|拒绝|unsafe)",
                )

    def test_common_download_rejects_boundary_in_errexit_suppressed_contexts(
        self,
    ) -> None:
        contexts = {
            "or-list": (
                'status=0\nminios_download_verified "$SOURCE_URL" '
                '"$SOURCE_SHA256" "$OUTSIDE_DESTINATION" || status=$?\n'
                'test "$status" -ne 0\n'
            ),
            "if-condition": (
                'status=0\nif minios_download_verified "$SOURCE_URL" '
                '"$SOURCE_SHA256" "$OUTSIDE_DESTINATION"; then\n'
                '    status=0\nelse\n    status=$?\nfi\n'
                'test "$status" -ne 0\n'
            ),
            "negated-condition": (
                'failed=0\nif ! minios_download_verified "$SOURCE_URL" '
                '"$SOURCE_SHA256" "$OUTSIDE_DESTINATION"; then\n'
                '    failed=1\nfi\ntest "$failed" -eq 1\n'
            ),
        }
        for context, invocation in contexts.items():
            with (
                self.subTest(context=context),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                environment_root = temporary_root / "environment"
                source = temporary_root / "source"
                source.write_bytes(b"boundary-fixture\n")
                outside_destination = temporary_root / "outside" / "archive"
                env = self._base_env(environment_root)
                env.update(
                    {
                        "COMMON_SH": str(ROOT / "environment/lib/common.sh"),
                        "OUTSIDE_DESTINATION": str(outside_destination),
                        "SOURCE_SHA256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "SOURCE_URL": source.as_uri(),
                    }
                )
                result = self._run_bash(
                    'set -u\nsource "$COMMON_SH"\n' + invocation,
                    env=env,
                    cwd=temporary_root,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertFalse(outside_destination.exists())
                self.assertFalse(Path(f"{outside_destination}.partial").exists())
                self.assertFalse(
                    (temporary_root / ".partial").exists(),
                    "失败的路径赋值不得退化为当前目录 .partial",
                )

    def test_common_download_propagates_hash_and_command_failures(self) -> None:
        cases = ("existing-hash", "download-hash", "path-assignment", "mv")
        for case in cases:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                environment_root = temporary_root / "environment"
                destination = environment_root / "downloads" / "archive"
                source = temporary_root / "source"
                source.write_bytes(b"verified-source\n")
                source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
                env = self._base_env(environment_root)
                env.update(
                    {
                        "COMMON_SH": str(ROOT / "environment/lib/common.sh"),
                        "DESTINATION": str(destination),
                        "SOURCE_SHA256": source_sha256,
                        "SOURCE_URL": source.as_uri(),
                    }
                )

                setup = ""
                expected_sha256 = source_sha256
                expected_status = "1"
                if case == "existing-hash":
                    destination.parent.mkdir(parents=True)
                    destination.write_bytes(b"corrupt-existing\n")
                elif case == "download-hash":
                    expected_sha256 = "0" * 64
                elif case == "path-assignment":
                    setup = (
                        "minios_assert_path_within_environment_root() { return 72; }\n"
                    )
                    expected_status = "72"
                elif case == "mv":
                    setup = "mv() { return 74; }\n"
                    expected_status = "74"
                env["EXPECTED_SHA256"] = expected_sha256
                env["EXPECTED_STATUS"] = expected_status

                result = self._run_bash(
                    'set -u\nsource "$COMMON_SH"\n'
                    + setup
                    + 'status=0\nminios_download_verified "$SOURCE_URL" '
                    '"$EXPECTED_SHA256" "$DESTINATION" || status=$?\n'
                    'test "$status" -eq "$EXPECTED_STATUS"\n',
                    env=env,
                    cwd=temporary_root,
                )

                diagnostic = result.stdout + result.stderr
                self.assertEqual(0, result.returncode, diagnostic)
                self.assertNotIn("复用已校验下载", diagnostic)
                self.assertNotIn("下载校验完成", diagnostic)
                self.assertFalse(Path(f"{destination}.partial").exists())
                if case != "existing-hash":
                    self.assertFalse(destination.exists())

    def test_common_helpers_propagate_canonicalize_and_hash_calculation_failures(
        self,
    ) -> None:
        overrides = {
            "canonicalize": (
                "71",
                "realpath() { return 71; }\n"
                'status=0\nminios_canonicalize_path "$SAFE_PATH" || status=$?\n'
            ),
            "sha256": (
                "73",
                "minios_sha256() { return 73; }\n"
                'status=0\nminios_verify_sha256 "$SOURCE_PATH" '
                '"$SOURCE_SHA256" || status=$?\n'
            ),
        }
        for helper, (expected_status, invocation) in overrides.items():
            with (
                self.subTest(helper=helper),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                environment_root = temporary_root / "environment"
                source = temporary_root / "source"
                source.write_bytes(b"helper-fixture\n")
                env = self._base_env(environment_root)
                env.update(
                    {
                        "COMMON_SH": str(ROOT / "environment/lib/common.sh"),
                        "SAFE_PATH": str(environment_root / "safe"),
                        "EXPECTED_STATUS": expected_status,
                        "SOURCE_PATH": str(source),
                        "SOURCE_SHA256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                )
                result = self._run_bash(
                    'set -u\nsource "$COMMON_SH"\n'
                    + invocation
                    + 'test "$status" -eq "$EXPECTED_STATUS"\n',
                    env=env,
                    cwd=temporary_root,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_with_env_never_falls_back_to_global_cross_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            environment_root = temporary_root / "environment"
            (environment_root / "toolchain" / "bin").mkdir(parents=True)
            global_bin = temporary_root / "global-bin"
            global_bin.mkdir()
            marker = temporary_root / "global-tool-ran"
            self._write_executable(
                global_bin / "i686-elf-gcc",
                "#!/bin/sh\nprintf 'executed\\n' > \"$FAKE_GLOBAL_MARKER\"\n",
            )
            env = self._base_env(environment_root)
            env.update(
                {
                    "FAKE_GLOBAL_MARKER": str(marker),
                    "PATH": str(global_bin) + os.pathsep + env["PATH"],
                }
            )

            cross_result = self._run_required(
                "environment/with-env.sh",
                "i686-elf-gcc",
                env=env,
            )
            generic_result = self._run_required(
                "environment/with-env.sh",
                "sh",
                "-c",
                "printf generic-command-ok",
                env=env,
            )

            self.assertNotEqual(0, cross_result.returncode)
            self.assertFalse(marker.exists(), "不得执行 PATH 中的全局交叉工具")
            self.assertEqual(0, generic_result.returncode, generic_result.stderr)
            self.assertEqual("generic-command-ok", generic_result.stdout)

    def test_verify_rejects_missing_empty_or_symlink_freestanding_object(self) -> None:
        for object_mode in ("missing", "empty", "symlink"):
            with (
                self.subTest(object_mode=object_mode),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                environment_root = Path(temporary_directory) / "environment"
                toolchain_bin = environment_root / "toolchain" / "bin"
                toolchain_bin.mkdir(parents=True)
                self._write_executable(
                    toolchain_bin / "i686-elf-gcc",
                    """#!/bin/sh
set -eu
if [ "${1:-}" = "-dumpmachine" ]; then
    printf 'i686-elf\\n'
    exit 0
fi
output=
previous=
for argument in "$@"; do
    if [ "$previous" = "-o" ]; then
        output="$argument"
    fi
    previous="$argument"
done
if [ "${FAKE_GCC_OBJECT_MODE:-missing}" = "empty" ] && [ -n "$output" ]; then
    : > "$output"
fi
if [ "${FAKE_GCC_OBJECT_MODE:-missing}" = "symlink" ] && [ -n "$output" ]; then
    ln -s /dev/null "$output"
fi
exit 0
""",
                )
                self._write_executable(
                    toolchain_bin / "i686-elf-ld",
                    "#!/bin/sh\nprintf 'fake ld 1.0\\n'\n",
                )
                env = self._base_env(environment_root)
                env["FAKE_GCC_OBJECT_MODE"] = object_mode

                result = self._run_required(
                    "environment/verify.sh",
                    env=env,
                )

                diagnostic = result.stdout + result.stderr
                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "check=freestanding-compile status=FAIL", diagnostic
                )
                self.assertNotIn(
                    "check=freestanding-compile status=PASS", diagnostic
                )

    def test_toolchain_print_plan_is_pinned_and_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            environment_root = temporary_root / "environment"
            command_directory = temporary_root / "commands"
            command_directory.mkdir()
            network_marker = temporary_root / "network-used"
            self._write_executable(
                command_directory / "curl",
                "#!/bin/sh\nprintf used > \"$NETWORK_MARKER\"\nexit 99\n",
            )
            env = self._base_env(environment_root)
            env.update(
                {
                    "NETWORK_MARKER": str(network_marker),
                    "PATH": str(command_directory) + os.pathsep + env["PATH"],
                }
            )
            result = self._run_required(
                "tools/build_toolchain.sh",
                "--print-plan",
                env=env,
            )
            self.assertFalse(environment_root.exists(), "--print-plan 不得创建环境根")
            self.assertFalse(network_marker.exists(), "--print-plan 不得访问网络")

        self.assertEqual(0, result.returncode, result.stderr)
        output = result.stdout.lower()
        self.assertIn("target=i686-elf", output)
        self.assertIn("binutils_version=2.42", output)
        self.assertIn("gcc_version=13.2.0", output)
        self.assertIn(f"prefix={environment_root}/toolchain".lower(), output)
        self.assertIn("binutils_configure=--target=i686-elf", output)
        self.assertIn("--with-sysroot", output)
        self.assertIn("gcc_configure=--target=i686-elf", output)
        self.assertIn("--enable-languages=c", output)
        self.assertIn("gcc_build_targets=all-gcc all-target-libgcc", output)
        self.assertIn("gcc_install_targets=install-gcc install-target-libgcc", output)

    def test_toolchain_rejects_dangerous_roots_and_invalid_arguments(self) -> None:
        for dangerous_root in ("", ".", "/", "/usr", "/usr/local", str(ROOT)):
            with self.subTest(environment_root=dangerous_root):
                result = self._run_required(
                    "tools/build_toolchain.sh",
                    "--print-plan",
                    env=self._base_env(dangerous_root),
                )
                self.assertNotEqual(0, result.returncode)

        argument_cases = (
            ("--unknown",),
            ("--print-plan", "--download-only"),
            ("--print-plan", "--force"),
            ("--download-only", "--force"),
            ("--force", "--force"),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            for arguments in argument_cases:
                with self.subTest(arguments=arguments):
                    result = self._run_required(
                        "tools/build_toolchain.sh",
                        *arguments,
                        env=self._base_env(temporary_directory),
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertRegex(
                        (result.stdout + result.stderr).lower(),
                        r"(?:usage|参数|冲突|未知|重复)",
                    )

    def test_toolchain_download_only_verifies_archives_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, _, env = self._write_toolchain_fixture(temporary_root)
            result = self._run_fixture_toolchain(
                fixture_root, "--download-only", env=env
            )

            environment_root = Path(env["MINIOS_ENV_ROOT"])
            downloads = environment_root / "downloads"
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                {"binutils-1.0.tar.xz", "gcc-1.0.tar.xz"},
                {path.name for path in downloads.iterdir()},
            )
            self.assertFalse(any(downloads.glob("*.partial")))
            self.assertFalse((environment_root / "sources").exists())
            self.assertFalse((environment_root / "build").exists())
            self.assertFalse((environment_root / "toolchain").exists())
            self.assertIn("download_status=complete", result.stdout)

    def test_toolchain_build_is_pinned_truthful_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, log, env = self._write_toolchain_fixture(temporary_root)
            first = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)

            environment_root = Path(env["MINIOS_ENV_ROOT"])
            marker = environment_root / "state" / "toolchain.env"
            self.assertTrue(marker.is_file())
            marker_text = marker.read_text(encoding="utf-8")
            self.assertRegex(marker_text, r"(?m)^lock_fingerprint=[0-9a-f]{64}$")
            self.assertIn("target=i686-elf", marker_text)
            self.assertIn(f"prefix={environment_root}/toolchain", marker_text)
            self.assertIn("binutils_configure=--target=i686-elf", marker_text)
            self.assertIn("gcc_configure=--target=i686-elf", marker_text)
            self.assertIn("gcc_build_targets=all-gcc all-target-libgcc", marker_text)
            self.assertIn(
                "gcc_install_targets=install-gcc install-target-libgcc",
                marker_text,
            )
            log_before = log.read_text(encoding="utf-8")
            self.assertIn(
                "configure component=binutils", log_before
            )
            self.assertIn("--target=i686-elf", log_before)
            self.assertIn("--with-sysroot", log_before)
            self.assertIn("--enable-languages=c", log_before)
            self.assertIn("--without-headers", log_before)
            self.assertIn("make cwd=", log_before)
            self.assertIn("all-gcc", log_before)
            self.assertIn("all-target-libgcc", log_before)
            self.assertIn("install-gcc", log_before)
            self.assertIn("install-target-libgcc", log_before)

            interrupted_selfcheck = (
                environment_root / ".toolchain-selfcheck.interrupted"
            )
            interrupted_selfcheck.mkdir()
            (interrupted_selfcheck / "stale.o").write_bytes(b"stale\n")
            second = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertIn("toolchain_status=up-to-date", second.stdout)
            self.assertEqual(log_before, log.read_text(encoding="utf-8"))
            self.assertFalse(interrupted_selfcheck.exists())

            (environment_root / "toolchain" / "bin" / "i686-elf-ld").unlink()
            third = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, third.returncode, third.stderr)
            self.assertNotIn("toolchain_status=up-to-date", third.stdout)
            self.assertGreater(len(log.read_text(encoding="utf-8")), len(log_before))

    def test_toolchain_source_cache_requires_exact_atomic_stamps(self) -> None:
        expected = {
            "binutils": (
                "1.0",
                "binutils-1.0",
            ),
            "gcc": (
                "1.0",
                "gcc-1.0",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, _, env = self._write_toolchain_fixture(temporary_root)
            result = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, result.returncode, result.stderr)
            environment_root = Path(env["MINIOS_ENV_ROOT"])
            version_values = dict(
                line.split("=", 1)
                for line in (
                    fixture_root / "environment" / "versions.env"
                ).read_text(encoding="utf-8").splitlines()
            )
            for component, (version, top_level) in expected.items():
                stamp = (
                    environment_root
                    / "sources"
                    / top_level
                    / ".minios-source.env"
                )
                self.assertTrue(stamp.is_file() and not stamp.is_symlink())
                text = stamp.read_text(encoding="utf-8")
                self.assertIn(f"component={component}\n", text)
                self.assertIn(f"version={version}\n", text)
                self.assertIn(f"expected_top_level={top_level}\n", text)
                self.assertIn(
                    "archive_sha256="
                    f"{version_values[f'MINIOS_{component.upper()}_SHA256']}\n",
                    text,
                )

                stale_partial = (
                    environment_root / "sources" / f".extract-{top_level}.partial"
                )
                stale_partial.mkdir()
                (stale_partial / "stale").write_text("stale\n", encoding="utf-8")
            second = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertFalse(any((environment_root / "sources").glob(".extract-*.partial")))

    def test_toolchain_rejects_missing_or_mismatched_source_stamp(self) -> None:
        for component, top_level in (
            ("binutils", "binutils-1.0"),
            ("gcc", "gcc-1.0"),
        ):
            for stamp_mode in ("missing", "wrong-hash"):
                with (
                    self.subTest(component=component, stamp_mode=stamp_mode),
                    tempfile.TemporaryDirectory() as temporary_directory,
                ):
                    temporary_root = Path(temporary_directory)
                    fixture_root, log, env = self._write_toolchain_fixture(temporary_root)
                    first = self._run_fixture_toolchain(fixture_root, env=env)
                    self.assertEqual(0, first.returncode, first.stderr)
                    stamp = (
                        Path(env["MINIOS_ENV_ROOT"])
                        / "sources"
                        / top_level
                        / ".minios-source.env"
                    )
                    if stamp_mode == "wrong-hash":
                        stamp.write_text(
                            f"component={component}\nversion=1.0\n"
                            f"archive_sha256={'0' * 64}\n"
                            f"expected_top_level={top_level}\n",
                            encoding="utf-8",
                        )
                    elif stamp.exists():
                        stamp.unlink()
                    log_before = log.read_text(encoding="utf-8")
                    marker = (
                        Path(env["MINIOS_ENV_ROOT"]) / "state/toolchain.env"
                    )
                    marker_before = marker.read_bytes()
                    second = self._run_fixture_toolchain(fixture_root, env=env)
                    self.assertNotEqual(0, second.returncode)
                    self.assertNotIn("toolchain_status=up-to-date", second.stdout)
                    self.assertEqual(log_before, log.read_text(encoding="utf-8"))
                    self.assertEqual(marker_before, marker.read_bytes())

    def test_toolchain_selfcheck_rejects_untruthful_artifacts(self) -> None:
        cases = (
            ("wrong-gcc-version", {"FAKE_GCC_VERSION": "11.0"}, True),
            ("wrong-ld-version", {"FAKE_LD_VERSION": "11.0"}, True),
            ("compile-missing", {"FAKE_GCC_COMPILE_MODE": "missing"}, True),
            ("compile-empty", {"FAKE_GCC_COMPILE_MODE": "empty"}, True),
            ("compile-symlink", {"FAKE_GCC_COMPILE_MODE": "symlink"}, True),
            ("missing-libgcc", {}, False),
            ("empty-libgcc", {}, False),
            ("external-libgcc", {}, True),
            ("symlink-libgcc", {}, True),
            ("symlink-libgcc-parent", {}, True),
        )
        for case, overrides, expect_failure in cases:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                fixture_root, log, env = self._write_toolchain_fixture(temporary_root)
                first = self._run_fixture_toolchain(fixture_root, env=env)
                self.assertEqual(0, first.returncode, first.stderr)
                environment_root = Path(env["MINIOS_ENV_ROOT"])
                libgcc = (
                    environment_root
                    / "toolchain/lib/gcc/i686-elf/1.0/libgcc.a"
                )
                outside = temporary_root / "outside-libgcc.a"
                outside.write_bytes(b"outside\n")
                if case == "missing-libgcc":
                    libgcc.unlink()
                elif case == "empty-libgcc":
                    libgcc.write_bytes(b"")
                elif case == "external-libgcc":
                    overrides = {"FAKE_LIBGCC_PATH": str(outside)}
                elif case == "symlink-libgcc":
                    libgcc.unlink()
                    libgcc.symlink_to(outside)
                elif case == "symlink-libgcc-parent":
                    gcc_parent = environment_root / "toolchain/lib/gcc"
                    outside_parent = temporary_root / "outside-gcc-parent"
                    gcc_parent.rename(outside_parent)
                    gcc_parent.symlink_to(outside_parent, target_is_directory=True)
                env.update(overrides)
                log_before = log.read_text(encoding="utf-8")
                result = self._run_fixture_toolchain(fixture_root, env=env)
                self.assertNotIn("toolchain_status=up-to-date", result.stdout)
                if expect_failure:
                    self.assertNotEqual(0, result.returncode)
                else:
                    self.assertEqual(0, result.returncode, result.stderr)
                self.assertGreater(len(log.read_text(encoding="utf-8")), len(log_before))
                self.assertFalse(any(environment_root.glob(".toolchain-selfcheck.*")))

    def test_toolchain_rejects_symlinked_state_parent_before_marker_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, log, env = self._write_toolchain_fixture(temporary_root)
            first = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)
            environment_root = Path(env["MINIOS_ENV_ROOT"])
            state = environment_root / "state"
            outside_state = temporary_root / "outside-state"
            state.rename(outside_state)
            state.symlink_to(outside_state, target_is_directory=True)
            log_before = log.read_text(encoding="utf-8")

            result = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("toolchain_status=up-to-date", result.stdout)
            self.assertEqual(log_before, log.read_text(encoding="utf-8"))

    def test_toolchain_rejects_unsafe_tar_members_before_extraction(self) -> None:
        for member_kind in ("absolute", "dotdot", "symlink", "hardlink"):
            with (
                self.subTest(member_kind=member_kind),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                fixture_root, _, env = self._write_toolchain_fixture(temporary_root)
                archive = temporary_root / f"malicious-{member_kind}.tar.xz"
                self._write_malicious_toolchain_archive(archive, member_kind)
                self._replace_fixture_archive(
                    fixture_root, "binutils", archive
                )
                result = self._run_fixture_toolchain(fixture_root, env=env)
                self.assertNotEqual(0, result.returncode)
                self.assertRegex(
                    (result.stdout + result.stderr).lower(),
                    r"(?:unsafe archive member|archive member|归档成员|不安全成员)",
                )
                self.assertFalse((temporary_root / "escape").exists())
                self.assertFalse(
                    any(
                        (Path(env["MINIOS_ENV_ROOT"]) / "sources").glob(
                            ".extract-*.partial"
                        )
                    )
                )

    def test_toolchain_force_preserves_downloads_sources_and_unknown_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, _, env = self._write_toolchain_fixture(temporary_root)
            first = self._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)
            environment_root = Path(env["MINIOS_ENV_ROOT"])
            download_sentinel = environment_root / "downloads" / "keep.txt"
            source_sentinel = environment_root / "sources" / "keep.txt"
            unknown_sentinel = environment_root / "unknown" / "keep.txt"
            unrelated_build = environment_root / "build" / "unrelated" / "keep.txt"
            for sentinel in (
                download_sentinel,
                source_sentinel,
                unknown_sentinel,
                unrelated_build,
            ):
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text("keep\n", encoding="utf-8")

            forced = self._run_fixture_toolchain(fixture_root, "--force", env=env)
            self.assertEqual(0, forced.returncode, forced.stderr)
            for sentinel in (
                download_sentinel,
                source_sentinel,
                unknown_sentinel,
                unrelated_build,
            ):
                self.assertTrue(sentinel.is_file(), f"--force 误删：{sentinel}")

    def test_toolchain_force_rejects_symlinked_owned_path_before_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, _, env = self._write_toolchain_fixture(temporary_root)
            environment_root = Path(env["MINIOS_ENV_ROOT"])
            build_directory = environment_root / "build" / "binutils-1.0"
            build_directory.mkdir(parents=True)
            build_sentinel = build_directory / "keep.txt"
            build_sentinel.write_text("keep\n", encoding="utf-8")
            outside = temporary_root / "outside"
            outside.mkdir()
            outside_sentinel = outside / "keep.txt"
            outside_sentinel.write_text("keep\n", encoding="utf-8")
            environment_root.mkdir(exist_ok=True)
            (environment_root / "toolchain").symlink_to(
                outside, target_is_directory=True
            )

            result = self._run_fixture_toolchain(
                fixture_root, "--force", env=env
            )
            self.assertNotEqual(0, result.returncode)
            self.assertTrue(outside_sentinel.is_file())
            self.assertTrue(build_sentinel.is_file(), "安全预检失败前不得部分删除")

    def test_ubuntu_create_reports_when_no_backend_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            command_directory = temporary_root / "commands"
            command_directory.mkdir()
            env = self._base_env(temporary_root / "environment")
            env["PATH"] = self._path_without_container_engines(command_directory)
            env.pop("MINIOS_CONTAINER_BACKEND", None)

            result = self._run_required(
                "environment/ubuntu/create.sh",
                env=env,
            )

        diagnostic = (result.stdout + result.stderr).lower()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("podman", diagnostic)
        self.assertIn("docker", diagnostic)
        self.assertRegex(
            diagnostic,
            r"(?:backend|runtime|not found|unavailable|后端|不可用|未找到|未安装)",
        )

    def test_ubuntu_destroy_rejects_unowned_image_without_removal(self) -> None:
        cases = (
            {
                "description": "state 镜像名不匹配",
                "state_image_name": "foreign-project:latest",
                "inspected_label": "MiniOrangeOS",
                "inspected_image_id": "sha256:owned-image-id",
            },
            {
                "description": "项目标签不匹配",
                "state_image_name": "miniorangeos-dev:ubuntu-24.04",
                "inspected_label": "OtherProject",
                "inspected_image_id": "sha256:owned-image-id",
            },
            {
                "description": "镜像 ID 不匹配",
                "state_image_name": "miniorangeos-dev:ubuntu-24.04",
                "inspected_label": "MiniOrangeOS",
                "inspected_image_id": "sha256:foreign-image-id",
            },
        )
        for backend in ("podman", "docker"):
            for case in cases:
                with (
                    self.subTest(backend=backend, case=case["description"]),
                    tempfile.TemporaryDirectory() as temporary_directory,
                ):
                    temporary_root = Path(temporary_directory)
                    environment_root = temporary_root / "environment"
                    command_directory = temporary_root / "commands"
                    runtime_directory = temporary_root / "runtime"
                    command_directory.mkdir()
                    runtime_directory.mkdir()
                    self._write_fake_container_backend(command_directory, backend)
                    self._write_container_state(
                        environment_root,
                        image_name=case["state_image_name"],
                    )
                    fake_log = temporary_root / f"{backend}.log"

                    env = self._base_env(environment_root)
                    env.update(
                        {
                            "FAKE_CONTAINER_IMAGE_ID": case["inspected_image_id"],
                            "FAKE_CONTAINER_IMAGE_NAME": (
                                "miniorangeos-dev:ubuntu-24.04"
                            ),
                            # fake inspect 把该值作为项目 label 的 value。
                            "FAKE_CONTAINER_LABEL": case["inspected_label"],
                            "FAKE_CONTAINER_LOG": str(fake_log),
                            "MINIOS_CONTAINER_BACKEND": backend,
                            "PATH": (
                                str(command_directory)
                                + os.pathsep
                                + env["PATH"]
                            ),
                            "XDG_RUNTIME_DIR": str(runtime_directory),
                        }
                    )

                    result = self._run_required(
                        "environment/ubuntu/destroy.sh",
                        "--all",
                        env=env,
                    )

                    self.assertNotEqual(
                        0, result.returncode, str(case["description"])
                    )
                    self.assertTrue(
                        fake_log.is_file(),
                        f"destroy --all 必须调用 fake {backend} 检查 ownership",
                    )
                    commands = fake_log.read_text(encoding="utf-8").splitlines()
                    self.assertTrue(
                        any("inspect" in command.split() for command in commands),
                        f"负面测试必须到达 fake {backend} ownership inspect",
                    )
                    removal_tokens = {"rm", "rmi"}
                    self.assertFalse(
                        any(
                            removal_tokens.intersection(command.split())
                            for command in commands
                        ),
                        f"ownership 不匹配时不得调用 {backend} rm/rmi：{commands}",
                    )

    def test_ubuntu_destroy_reaches_owned_image_probe_for_both_backends(self) -> None:
        for backend in ("podman", "docker"):
            with (
                self.subTest(backend=backend),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                environment_root = temporary_root / "environment"
                command_directory = temporary_root / "commands"
                runtime_directory = temporary_root / "runtime"
                command_directory.mkdir()
                runtime_directory.mkdir()
                self._write_fake_container_backend(command_directory, backend)
                self._write_container_state(environment_root)
                fake_log = temporary_root / f"{backend}.log"
                env = self._base_env(environment_root)
                env.update(
                    {
                        "FAKE_CONTAINER_IMAGE_ID": "sha256:owned-image-id",
                        "FAKE_CONTAINER_IMAGE_NAME": (
                            "miniorangeos-dev:ubuntu-24.04"
                        ),
                        "FAKE_CONTAINER_LABEL": "MiniOrangeOS",
                        "FAKE_CONTAINER_LOG": str(fake_log),
                        "MINIOS_CONTAINER_BACKEND": backend,
                        "PATH": str(command_directory) + os.pathsep + env["PATH"],
                        "XDG_RUNTIME_DIR": str(runtime_directory),
                    }
                )

                self._run_required(
                    "environment/ubuntu/destroy.sh",
                    "--all",
                    env=env,
                )

                self.assertTrue(
                    fake_log.is_file(),
                    f"正常 state 必须调用 fake {backend} ownership probe",
                )
                commands = fake_log.read_text(encoding="utf-8").splitlines()
                self.assertTrue(
                    any("inspect" in command.split() for command in commands),
                    f"正常 state 必须到达 fake {backend} inspect",
                )


if __name__ == "__main__":
    unittest.main()
