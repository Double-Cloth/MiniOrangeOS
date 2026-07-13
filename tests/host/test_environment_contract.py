"""定义 T01 隔离环境生命周期的静态契约。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PUBLIC_T01_FILES = (
    "environment/wsl/create.ps1",
    "environment/wsl/enter.ps1",
    "environment/wsl/backup.ps1",
    "environment/wsl/destroy.ps1",
    "environment/Containerfile",
    "environment/ubuntu/create.sh",
    "environment/ubuntu/run.sh",
    "environment/ubuntu/destroy.sh",
    "environment/bootstrap-inside.sh",
    "environment/with-env.sh",
    "environment/verify.sh",
    "tools/build_toolchain.sh",
)

SHELL_SCRIPTS = (
    "environment/bootstrap-inside.sh",
    "environment/with-env.sh",
    "environment/verify.sh",
    "environment/ubuntu/create.sh",
    "environment/ubuntu/run.sh",
    "environment/ubuntu/destroy.sh",
    "tools/build_toolchain.sh",
)

WSL_SCRIPTS = (
    "environment/wsl/create.ps1",
    "environment/wsl/enter.ps1",
    "environment/wsl/backup.ps1",
    "environment/wsl/destroy.ps1",
)

WSL_STORAGE_SCRIPTS = (
    "environment/wsl/create.ps1",
    "environment/wsl/backup.ps1",
    "environment/wsl/destroy.ps1",
)


class EnvironmentContractTests(unittest.TestCase):
    def _read_required(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"缺少 T01 文件：{relative_path}")
        return path.read_text(encoding="utf-8")

    def _parse_versions(self) -> dict[str, str]:
        content = self._read_required("environment/versions.env")
        values: dict[str, str] = {}
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertRegex(
                line,
                r"^[A-Z][A-Z0-9_]*=[^\s]+$",
                f"versions.env 第 {line_number} 行不是纯 KEY=VALUE：{raw_line!r}",
            )
            key, value = line.split("=", 1)
            self.assertNotIn(key, values, f"versions.env 重复键：{key}")
            values[key] = value
        return values

    def test_public_t01_files_exist(self) -> None:
        missing = [path for path in PUBLIC_T01_FILES if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"缺少 T01 生命周期文件：{missing}")

    def test_versions_lock_pins_all_external_sources(self) -> None:
        values = self._parse_versions()
        self.assertEqual("i686-elf", values.get("MINIOS_TARGET"))
        self.assertEqual("MiniOrangeOS-Dev", values.get("MINIOS_WSL_DISTRO"))
        self.assertEqual(
            "miniorangeos-dev:ubuntu-24.04", values.get("MINIOS_CONTAINER_IMAGE")
        )
        self.assertEqual(
            "org.miniorangeos.project=MiniOrangeOS",
            values.get("MINIOS_CONTAINER_LABEL"),
        )

        pinned_values = set(values.values())
        expected_values = {
            "24.04.4",
            "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-wsl-amd64.wsl",
            "9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5",
            "ubuntu:noble-20260509.1",
            "sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54",
            "2.42",
            "https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz",
            "f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800",
            "13.2.0",
            "https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz",
            "e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da",
        }
        self.assertEqual(set(), expected_values - pinned_values)

        source_hashes = {
            value
            for value in pinned_values
            if re.fullmatch(r"[0-9a-f]{64}", value)
        }
        self.assertTrue(
            {
                "9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5",
                "f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800",
                "e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da",
            }.issubset(source_hashes),
            "WSL、Binutils 和 GCC 必须使用 64 位小写 SHA-256",
        )

    def test_shell_scripts_use_strict_mode(self) -> None:
        for relative_path in SHELL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertRegex(content, r"(?m)^set -euo pipefail\s*$")

    def test_shell_scripts_avoid_global_or_unbounded_mutation(self) -> None:
        root_delete = re.compile(
            r"(?m)\brm\s+(?:-[^\s]+\s+)*(?:--\s+)?/[ \t]*(?:$|[;&|])"
        )
        global_write = re.compile(
            r"(?im)\b(?:install|cp|mv|mkdir|ln|touch|tee|sed\s+-i)\b"
            r"[^\n]*(?:/usr/local|\.bashrc|\.profile|/etc/environment)"
        )
        for relative_path in SHELL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertNotIn("system prune", content.lower())
                self.assertIsNone(root_delete.search(content), "禁止递归删除根目录")
                self.assertIsNone(
                    global_write.search(content),
                    "禁止写入 /usr/local 或 Shell 启动文件",
                )

    def test_wsl_scripts_restrict_names_and_authorized_root(self) -> None:
        for relative_path in WSL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertIn("MiniOrangeOS-Dev", content)
                self.assertIn("MiniOrangeOS-Dev-Test-", content)
                self.assertIn(r"D:\ApplicationData\MiniOrangeOS", content)
                self.assertIn("GetFullPath", content)
                self.assertNotRegex(content, r"(?i)wsl(?:\.exe)?\s+--shutdown")

    def test_wsl_storage_actions_validate_registry_basepath_and_reparse_points(
        self,
    ) -> None:
        for relative_path in WSL_STORAGE_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertRegex(
                    content,
                    r"(?i)(?:HKCU:|HKEY_CURRENT_USER)"
                    r"[^\r\n]*Software\\Microsoft\\Windows\\CurrentVersion\\Lxss",
                )
                self.assertIn("BasePath", content)
                self.assertIn("GetFullPath", content)
                self.assertIn("ReparsePoint", content)
                self.assertIn("rootfs", content)
                self.assertIn("drills", content)

    def test_wsl_destroy_requires_apply_and_exact_confirmation(self) -> None:
        content = self._read_required("environment/wsl/destroy.ps1")
        self.assertRegex(content, r"(?i)\[switch\]\s*\$Apply")
        self.assertRegex(content, r"(?i)\$ConfirmName")
        self.assertRegex(content, r"(?i)(?:-ne|-ceq|::Equals\()")
        self.assertIn("--unregister", content)
        self.assertRegex(content, r"(?i)(?:preview|预览)")
        self.assertNotRegex(content, r"(?i)wsl(?:\.exe)?\s+--shutdown")

    def test_containerfile_pins_ubuntu_digest_and_project_labels(self) -> None:
        content = self._read_required("environment/Containerfile")
        self.assertIn(
            "FROM ubuntu:noble-20260509.1@sha256:"
            "786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54",
            content,
        )
        self.assertIn("org.miniorangeos.project=MiniOrangeOS", content)
        self.assertIn("org.miniorangeos.task=T01", content)

    def test_ubuntu_destroy_has_four_independent_boundaries(self) -> None:
        content = self._read_required("environment/ubuntu/destroy.sh").lower()
        self.assertIn("miniorangeos-dev:ubuntu-24.04", content)
        self.assertIn("org.miniorangeos.project=MiniOrangeOS".lower(), content)
        self.assertIn("container.env", content)
        self.assertRegex(content, r"image[_ -]?id")
        self.assertIn("container-storage", content)
        self.assertIn("graphroot", content)
        self.assertIn("runroot", content)
        self.assertIn("buildx", content)
        self.assertIn("miniorangeos-dev-builder", content)
        self.assertIn("--all", content)
        self.assertNotIn("system prune", content)

    def test_container_create_and_destroy_share_storage_and_builder_boundaries(
        self,
    ) -> None:
        for relative_path in (
            "environment/ubuntu/create.sh",
            "environment/ubuntu/destroy.sh",
        ):
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path).lower()
                self.assertIn("container-storage", content)
                self.assertIn("miniorangeos-dev-builder", content)

    def test_environment_documentation_lists_public_interfaces(self) -> None:
        content = self._read_required("docs/environment.md")
        for relative_path in PUBLIC_T01_FILES:
            with self.subTest(path=relative_path):
                self.assertIn(relative_path, content)
        self.assertIn("environment/ubuntu/destroy.sh --all", content)

    def test_docs_record_wsl_only_rootless_podman_evidence_boundary(self) -> None:
        docs = "\n".join(
            (
                self._read_required("docs/environment.md"),
                self._read_required("docs/testing.md"),
            )
        )
        self.assertIn("MiniOrangeOS-Dev-Test-ContainerHost", docs)
        self.assertIn("rootless Podman", docs)
        self.assertIn("Ubuntu 24.04 WSL2", docs)
        self.assertIn("原生 Linux 内核", docs)
        self.assertIn("Linux CI", docs)


if __name__ == "__main__":
    unittest.main()
