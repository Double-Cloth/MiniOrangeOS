"""使用临时目录定义 T01 Linux 环境脚本的运行时契约。"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
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

    def test_verify_rejects_missing_or_empty_freestanding_object(self) -> None:
        for object_mode in ("missing", "empty"):
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
            environment_root = Path(temporary_directory)
            result = self._run_required(
                "tools/build_toolchain.sh",
                "--print-plan",
                env=self._base_env(environment_root),
            )
            self.assertEqual([], list(environment_root.iterdir()), "--print-plan 不得写入环境根")

        self.assertEqual(0, result.returncode, result.stderr)
        output = result.stdout.lower()
        self.assertIn("target=i686-elf", output)
        self.assertIn("binutils_version=2.42", output)
        self.assertIn("gcc_version=13.2.0", output)
        self.assertIn(f"prefix={environment_root}/toolchain".lower(), output)

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
