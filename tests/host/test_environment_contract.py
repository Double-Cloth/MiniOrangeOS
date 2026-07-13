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

EXPECTED_VERSION_LOCK = {
    "MINIOS_TARGET": "i686-elf",
    "MINIOS_WSL_DISTRO": "MiniOrangeOS-Dev",
    "MINIOS_WSL_IMAGE_VERSION": "24.04.4",
    "MINIOS_WSL_IMAGE_URL": (
        "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-wsl-amd64.wsl"
    ),
    "MINIOS_WSL_IMAGE_SHA256": (
        "9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5"
    ),
    "MINIOS_CONTAINER_IMAGE": "miniorangeos-dev:ubuntu-24.04",
    "MINIOS_CONTAINER_LABEL": "org.miniorangeos.project=MiniOrangeOS",
    "MINIOS_CONTAINER_BASE_IMAGE": "ubuntu:noble-20260509.1",
    "MINIOS_CONTAINER_BASE_DIGEST": (
        "sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54"
    ),
    "MINIOS_BINUTILS_VERSION": "2.42",
    "MINIOS_BINUTILS_URL": "https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz",
    "MINIOS_BINUTILS_SHA256": (
        "f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800"
    ),
    "MINIOS_GCC_VERSION": "13.2.0",
    "MINIOS_GCC_URL": (
        "https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz"
    ),
    "MINIOS_GCC_SHA256": (
        "e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da"
    ),
}


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

    def _without_comments(self, content: str, *, powershell: bool = False) -> str:
        if powershell:
            content = re.sub(r"(?s)<#.*?#>", "", content)

        uncommented_lines: list[str] = []
        for line in content.splitlines():
            quote: str | None = None
            escaped = False
            comment_at: int | None = None
            for index, character in enumerate(line):
                if escaped:
                    escaped = False
                    continue
                if character in {"\\", "`"}:
                    escaped = True
                    continue
                if quote is not None:
                    if character == quote:
                        quote = None
                    continue
                if character in {"'", '"'}:
                    quote = character
                    continue
                if character == "#" and (
                    index == 0
                    or line[index - 1].isspace()
                    or line[index - 1] in ";|&()"
                ):
                    comment_at = index
                    break
            uncommented_lines.append(line if comment_at is None else line[:comment_at])
        return "\n".join(uncommented_lines)

    def _function_span(
        self, content: str, name: str, *, powershell: bool
    ) -> tuple[int, int]:
        if powershell:
            pattern = rf"(?im)^\s*function\s+{re.escape(name)}\b[^{{]*{{"
        else:
            pattern = rf"(?m)^\s*(?:function\s+)?{re.escape(name)}\s*\(\s*\)\s*{{"
        match = re.search(pattern, content)
        self.assertIsNotNone(match, f"缺少稳定安全 helper：{name}")
        assert match is not None

        depth = 1
        index = match.end()
        while index < len(content) and depth:
            if content[index] == "{":
                depth += 1
            elif content[index] == "}":
                depth -= 1
            index += 1
        self.assertEqual(0, depth, f"helper 大括号不平衡：{name}")
        return match.start(), index

    def _function_body(self, content: str, name: str, *, powershell: bool) -> str:
        start, end = self._function_span(content, name, powershell=powershell)
        return content[start:end]

    def _without_function_definitions(self, content: str, *, powershell: bool) -> str:
        if powershell:
            names = re.findall(r"(?im)^\s*function\s+([\w-]+)\b", content)
        else:
            names = re.findall(
                r"(?m)^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*{",
                content,
            )
        spans = [
            self._function_span(content, name, powershell=powershell) for name in names
        ]
        main_flow = content
        for start, end in sorted(spans, reverse=True):
            main_flow = main_flow[:start] + "\n" + main_flow[end:]
        return main_flow

    def test_public_t01_files_exist(self) -> None:
        missing = [path for path in PUBLIC_T01_FILES if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"缺少 T01 生命周期文件：{missing}")

    def test_versions_lock_pins_all_external_sources(self) -> None:
        values = self._parse_versions()
        actual = {key: values.get(key) for key in EXPECTED_VERSION_LOCK}
        self.assertEqual(
            EXPECTED_VERSION_LOCK,
            actual,
            "锁文件必须使用规定 key；未知 key 不能替代稳定接口",
        )
        for key in (
            "MINIOS_WSL_IMAGE_SHA256",
            "MINIOS_BINUTILS_SHA256",
            "MINIOS_GCC_SHA256",
        ):
            with self.subTest(key=key):
                self.assertRegex(values.get(key, ""), r"^[0-9a-f]{64}$")

    def test_shell_scripts_use_strict_mode(self) -> None:
        for relative_path in SHELL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertRegex(content, r"(?m)^set -euo pipefail\s*$")

    def test_shell_scripts_avoid_global_or_unbounded_mutation(self) -> None:
        root_delete = re.compile(
            r"(?m)\brm\s+(?:-[^\s]+\s+)*(?:--\s+)?/[ \t]*(?:$|[;&|])"
        )
        protected_target = (
            r"(?:/usr/local(?:/[^\s;&|]*)?|/etc/environment|"
            r"(?:~|\$(?:HOME|\{HOME\}))/\.(?:bashrc|profile)|"
            r"\.(?:bashrc|profile))"
        )
        redirected_write = re.compile(
            rf"(?im)(?:^|\s|[;&|])(?:\d*>>?|&>>?)\s*[\"']?{protected_target}"
        )
        mutating_command = re.compile(
            rf"(?im)\b(?:tee|install|cp|mv|rsync|mkdir|ln|touch|sed\s+-i)\b"
            rf"[^\n]*{protected_target}"
        )
        for relative_path in SHELL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._without_comments(self._read_required(relative_path))
                self.assertNotIn("system prune", content.lower())
                self.assertIsNone(root_delete.search(content), "禁止递归删除根目录")
                self.assertIsNone(
                    redirected_write.search(content),
                    "禁止通过重定向写入全局路径或 Shell 启动文件",
                )
                self.assertIsNone(
                    mutating_command.search(content),
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

    def test_wsl_destroy_uses_ordered_safety_helpers(self) -> None:
        content = self._without_comments(
            self._read_required("environment/wsl/destroy.ps1"), powershell=True
        )
        ownership = self._function_body(
            content, "Assert-WslDistributionOwnership", powershell=True
        )
        confirmation = self._function_body(
            content, "Confirm-WslDestruction", powershell=True
        )
        unregister = self._function_body(
            content, "Invoke-ExactWslUnregister", powershell=True
        )

        self.assertRegex(
            ownership,
            r"(?is)Get-ItemProperty(?:Value)?\b.*Lxss.*BasePath",
            "ownership helper 必须从当前用户 Lxss 注册项读取 BasePath",
        )
        self.assertRegex(
            ownership,
            r"(?i)GetFullPath\s*\(\s*\$ExpectedPath\s*\)",
            "ownership helper 必须规范化预期安装路径",
        )
        self.assertRegex(
            ownership,
            r"(?is)if\s*\([^)]*(?:-cne|-ne|::Equals)[^)]*\)"
            r"\s*\{[^}]*\bthrow\b",
            "注册 BasePath 与预期路径不一致时必须拒绝",
        )
        self.assertRegex(
            ownership,
            r"(?is)if\s*\([^)]*ReparsePoint[^)]*\)\s*\{[^}]*\bthrow\b",
            "发现 reparse point 时必须拒绝",
        )

        self.assertRegex(
            confirmation,
            r"(?is)if\s*\(\s*-not\s+\$Apply\s*\)\s*"
            r"\{[^}]*(?:\breturn\b|\bthrow\b)",
            "未指定 Apply 时 confirmation helper 必须终止删除流程",
        )
        self.assertRegex(
            confirmation,
            r"(?is)if\s*\(\s*\$ConfirmName\s+-cne\s+\$DistroName\s*\)"
            r"\s*\{[^}]*(?:\breturn\b|\bthrow\b)",
            "确认 helper 必须同时检查 Apply 和区分大小写的精确名称",
        )

        self.assertRegex(unregister, r"(?i)param\s*\(")
        self.assertRegex(unregister, r"(?i)\$DistroName")
        self.assertNotIn("MiniOrangeOS-Dev", unregister)
        self.assertRegex(
            unregister,
            r"(?im)^\s*(?:&\s*)?wsl(?:\.exe)?\b[^\r\n]*"
            r"--unregister\s+(?:--\s+)?\$DistroName\b",
            "unregister helper 只能把参数化精确名称传给 wsl",
        )

        main_flow = self._without_function_definitions(content, powershell=True)
        calls = [
            re.search(rf"(?im)^\s*{re.escape(name)}\b", main_flow)
            for name in (
                "Assert-WslDistributionOwnership",
                "Confirm-WslDestruction",
                "Invoke-ExactWslUnregister",
            )
        ]
        self.assertTrue(all(calls), "主控制流必须调用全部三个安全 helper")
        self.assertEqual(
            sorted(call.start() for call in calls if call is not None),
            [call.start() for call in calls if call is not None],
            "主控制流必须按 ownership → confirmation → unregister 执行",
        )
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
        content = self._without_comments(
            self._read_required("environment/ubuntu/destroy.sh")
        ).lower()
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

        ownership_call = re.search(r"(?m)^\s*assert_owned_image(?:\s|$)", content)
        self.assertIsNotNone(
            ownership_call,
            "destroy --all 必须实际调用 assert_owned_image，而不只是定义或注释它",
        )
        removal_commands = list(
            re.finditer(
                r"(?im)^\s*(?:podman|docker|\"?\$\{?[a-z_][a-z0-9_]*\}?\"?)"
                r"[^\r\n]*\s(?:rm|rmi)\b",
                content,
            )
        )
        self.assertTrue(removal_commands, "destroy.sh 必须包含受保护的容器删除路径")
        assert ownership_call is not None
        self.assertTrue(
            all(ownership_call.start() < command.start() for command in removal_commands),
            "任何 podman/docker rm 或 rmi 之前必须先调用 assert_owned_image",
        )

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
