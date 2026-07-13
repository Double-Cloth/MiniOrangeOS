"""使用临时目录定义 T01 Linux 环境脚本的运行时契约。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class EnvironmentRuntimeTests(unittest.TestCase):
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
