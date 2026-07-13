"""定义 T01 隔离环境生命周期的静态契约。"""

from __future__ import annotations

import re
import shlex
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
    "environment/lib/common.sh",
    "environment/bootstrap-inside.sh",
    "environment/with-env.sh",
    "environment/verify.sh",
    "environment/ubuntu/lib.sh",
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

PROTECTED_SHELL_TARGET = re.compile(
    r"(?:/usr/local(?:/|\b)|/etc/environment\b|"
    r"(?:\$HOME|\$\{HOME\}|~)/\.(?:bashrc|profile)\b|"
    r"(?<![\w/])\.(?:bashrc|profile)\b)"
)

COMMON_PROTECTED_LITERAL_LINES = (
    re.compile(
        r"^\s*(?:readonly\s+)?MINIOS_FORBIDDEN_ENV_ROOTS="
        r"\(\s*[\"']/[\"']\s+[\"']/usr[\"']\s+"
        r"[\"']/usr/local[\"']\s*\)\s*$"
    ),
)

VERIFY_READ_ONLY_PROTECTED_LINES = (
    re.compile(
        r"^\s*(?:if\s+)?compgen\s+-G\s+"
        r"[\"']?/usr/local/bin/i686-elf-\*[\"']?\s*>\s*/dev/null"
        r"\s*(?:;\s*then)?\s*$"
    ),
    re.compile(
        r"^\s*find\s+[\"']?/usr/local/bin[\"']?\s+-maxdepth\s+1\s+"
        r"-type\s+f\s+-name\s+[\"']?i686-elf-\*[\"']?\s+-print"
        r"(?:\s+-quit)?\s*$"
    ),
    re.compile(
        r"^\s*(?:if\s+)?(?:test\s+-(?:e|f|d|L)|\[\[?\s+-(?:e|f|d|L))"
        r"\s+[\"']?/usr/local/bin/i686-elf-(?:gcc|ld|\*)[\"']?"
        r"\s*(?:\]\]?|;\s*then)?\s*$"
    ),
)

WSL_OWNERSHIP_SOURCE_CHAIN = re.compile(
    r"(?im)^\s*\$LxssRoot\s*=\s*"
    r"[\"']HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss[\"']"
    r"\s*$\s*"
    r"^\s*\$LxssKey\s*=\s*Get-ChildItem\s+-LiteralPath\s+\$LxssRoot\b"
    r"[^\r\n]*\bDistributionName\b[^\r\n]*-ceq\s+\$DistroName\b"
    r"[^\r\n]*Select-Object\s+-ExpandProperty\s+PSPath(?:\s+-First\s+1)?"
    r"\s*$\s*"
    r"^\s*\$Registration\s*=\s*Get-ItemProperty\s+"
    r"-LiteralPath\s+\$LxssKey\s*$\s*"
    r"^\s*\$RegisteredBasePath\s*=\s*\$Registration\.BasePath\s*$\s*"
    r"^\s*\$RegisteredVersion\s*=\s*\$Registration\.Version\s*$"
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

    def _expand_simple_shell_assignments(self, content: str) -> str:
        assignments: dict[str, str] = {}
        expanded_lines: list[str] = []
        assignment_pattern = re.compile(
            r"^\s*(?:(?:export|readonly|local)\s+)?([A-Za-z_][A-Za-z0-9_]*)="
            r"(?:\"([^\"]*)\"|'([^']*)'|([^\s;]+))\s*$"
        )
        variable_pattern = re.compile(
            r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))"
        )

        def expand(value: str) -> str:
            for _ in range(len(assignments) + 1):
                expanded = variable_pattern.sub(
                    lambda match: assignments.get(
                        match.group(1) or match.group(2), match.group(0)
                    ),
                    value,
                )
                if expanded == value:
                    return value
                value = expanded
            return value

        def split_unquoted_semicolons(line: str) -> list[str]:
            segments: list[str] = []
            start = 0
            quote: str | None = None
            escaped = False
            for index, character in enumerate(line):
                if escaped:
                    escaped = False
                    continue
                if character == "\\":
                    escaped = True
                    continue
                if quote is not None:
                    if character == quote:
                        quote = None
                    continue
                if character in {"'", '"'}:
                    quote = character
                elif character == ";":
                    segments.append(line[start:index])
                    start = index + 1
            segments.append(line[start:])
            return segments

        for line in content.splitlines():
            for segment in split_unquoted_semicolons(line):
                expanded_segment = expand(segment.strip())
                try:
                    tokens = shlex.split(expanded_segment, comments=False)
                except ValueError:
                    tokens = []
                if tokens and tokens[0] in {"export", "readonly", "local"}:
                    compound_assignments = tokens[1:]
                    if compound_assignments and all(
                        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token)
                        for token in compound_assignments
                    ):
                        expanded_tokens = [tokens[0]]
                        for token in compound_assignments:
                            key, raw_value = token.split("=", 1)
                            value = expand(raw_value)
                            assignments[key] = value
                            expanded_tokens.append(f"{key}={value}")
                        expanded_lines.append(" ".join(expanded_tokens))
                        continue

                match = assignment_pattern.match(expanded_segment)
                if match is not None:
                    raw_value = next(
                        value for value in match.groups()[1:] if value is not None
                    )
                    assignments[match.group(1)] = expand(raw_value)
                expanded_lines.append(expanded_segment)
        return "\n".join(expanded_lines)

    def _shell_policy_violations(
        self, relative_path: str, content: str
    ) -> list[str]:
        uncommented = self._without_comments(content)
        expanded = self._expand_simple_shell_assignments(uncommented)
        violations: list[str] = []

        forbidden_patterns = (
            ("global prune", re.compile(r"(?i)\b(?:podman|docker)\s+system\s+prune\b")),
            (
                "root delete",
                re.compile(
                    r"(?m)\brm\s+(?:-[^\s]+\s+)*(?:--\s+)?/"
                    r"[ \t]*(?:$|[;&|])"
                ),
            ),
            ("eval", re.compile(r"(?m)(?:^|[;&|]\s*|\s)eval(?:\s|$)")),
            (
                "shell -c",
                re.compile(r"(?m)(?:^|[\s;&|])(?:/[^\s]+/)?(?:ba)?sh\s+-c\b"),
            ),
            (
                "dynamic interpreter",
                re.compile(
                    r"(?im)\b(?:python(?:3(?:\.\d+)?)?|perl|ruby)\b[^\n]*"
                    r"(?:\s-(?:e|c)\b|\s-[A-Za-z]*[ec][A-Za-z]*\b)"
                ),
            ),
            (
                "protected redirection",
                re.compile(
                    r"(?im)(?:^|\s|[;&|])(?:\d*>>?|&>>?)\s*[\"']?"
                    + PROTECTED_SHELL_TARGET.pattern
                ),
            ),
            (
                "protected mutation command",
                re.compile(
                    r"(?im)\b(?:tee|install|cp|mv|rsync|mkdir|ln|touch|"
                    r"sed\s+-i|dd|truncate|tar|perl\s+-[^\s]*i)\b[^\n]*"
                    + PROTECTED_SHELL_TARGET.pattern
                ),
            ),
        )
        for description, pattern in forbidden_patterns:
            if pattern.search(expanded):
                violations.append(description)

        for line_number, line in enumerate(expanded.splitlines(), start=1):
            if PROTECTED_SHELL_TARGET.search(line) is None:
                continue
            if relative_path == "environment/lib/common.sh":
                allowed = any(
                    pattern.fullmatch(line)
                    for pattern in COMMON_PROTECTED_LITERAL_LINES
                )
            elif relative_path == "environment/verify.sh":
                allowed = any(
                    pattern.fullmatch(line)
                    for pattern in VERIFY_READ_ONLY_PROTECTED_LINES
                )
            else:
                allowed = False
            if not allowed:
                violations.append(f"protected literal at line {line_number}: {line.strip()}")
        return violations

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
        for relative_path in SHELL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertEqual(
                    [],
                    self._shell_policy_violations(relative_path, content),
                    "Shell 源码违反保守全局写入策略",
                )

    def test_shell_policy_rejects_synthetic_bypass_attempts(self) -> None:
        malicious_sources = {
            "dd": "dd if=tool of=/usr/local/bin/tool\n",
            "truncate": "truncate -s 0 \"$HOME/.bashrc\"\n",
            "tar": "tar -xf payload.tar -C /usr/local\n",
            "perl": "perl -pi -e 's/x/y/' /etc/environment\n",
            "python": "python3 -c 'open(path, \"w\").write(data)'\n",
            "variable split": (
                "root=/usr\nleaf=/local\ntarget=\"${root}${leaf}\"\n"
                "cp tool \"$target/bin/tool\"\n"
            ),
            "semicolon variable split": (
                "root=/usr; leaf=/local\ntarget=\"${root}${leaf}\"; "
                "cp tool \"$target/bin/tool\"\n"
            ),
            "local compound variable split": (
                "local root=/usr leaf=/local\n"
                "target=\"${root}${leaf}\"\ncp tool \"$target/bin/tool\"\n"
            ),
        }
        for bypass, source in malicious_sources.items():
            with self.subTest(bypass=bypass):
                self.assertTrue(
                    self._shell_policy_violations("environment/with-env.sh", source),
                    f"保守扫描器未拒绝合成绕过：{bypass}",
                )

        self.assertEqual(
            [],
            self._shell_policy_violations(
                "environment/lib/common.sh",
                'readonly MINIOS_FORBIDDEN_ENV_ROOTS=("/" "/usr" "/usr/local")\n',
            ),
        )
        self.assertEqual(
            [],
            self._shell_policy_violations(
                "environment/verify.sh",
                "if compgen -G '/usr/local/bin/i686-elf-*' > /dev/null; then\nfi\n",
            ),
        )

    def test_wsl_ownership_source_chain_rejects_unrelated_registry_value(
        self,
    ) -> None:
        valid_chain = r"""
$LxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
$LxssKey = Get-ChildItem -LiteralPath $LxssRoot | Where-Object { (Get-ItemProperty -LiteralPath $_.PSPath).DistributionName -ceq $DistroName } | Select-Object -ExpandProperty PSPath -First 1
$Registration = Get-ItemProperty -LiteralPath $LxssKey
$RegisteredBasePath = $Registration.BasePath
$RegisteredVersion = $Registration.Version
"""
        unrelated_bypass = r"""
$Unused = (Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss').BasePath
$RegisteredBasePath = (Get-ItemProperty -LiteralPath 'HKCU:\Software\Unrelated').BasePath
"""
        self.assertIsNotNone(WSL_OWNERSHIP_SOURCE_CHAIN.search(valid_chain))
        self.assertIsNone(
            WSL_OWNERSHIP_SOURCE_CHAIN.search(unrelated_bypass),
            "未使用的 Lxss 读取不能为无关 RegisteredBasePath 提供 ownership 证据",
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
            WSL_OWNERSHIP_SOURCE_CHAIN,
            "RegisteredBasePath 必须绑定到按 DistroName 选出的固定 HKCU LxssKey",
        )
        self.assertRegex(
            ownership,
            r"(?im)^\s*\$RegisteredFullPath\s*=\s*"
            r"\[IO\.Path\]::GetFullPath\(\$RegisteredBasePath\)\s*$",
            "RegisteredFullPath 必须直接源自 RegisteredBasePath 的规范化",
        )
        self.assertRegex(
            ownership,
            r"(?im)^\s*\$ExpectedFullPath\s*=\s*"
            r"\[IO\.Path\]::GetFullPath\(\$ExpectedPath\)\s*$",
            "ExpectedFullPath 必须直接源自 ExpectedPath 的规范化",
        )
        self.assertRegex(
            ownership,
            r"(?is)if\s*\(\s*\$RegisteredFullPath\s+-cne\s+"
            r"\$ExpectedFullPath\s*\)\s*\{[^}]*\bthrow\b",
            "必须直接比较注册规范化路径与预期规范化路径并拒绝不一致",
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

        unregister_tokens = list(re.finditer(r"(?i)--unregister\b", content))
        self.assertEqual(
            1,
            len(unregister_tokens),
            "去注释后的 destroy.ps1 全文只能有一个 --unregister",
        )
        unregister_start, unregister_end = self._function_span(
            content, "Invoke-ExactWslUnregister", powershell=True
        )
        self.assertTrue(
            unregister_start <= unregister_tokens[0].start() < unregister_end,
            "唯一 --unregister 只能位于 Invoke-ExactWslUnregister 内",
        )
        self.assertNotIn("--unregister", ownership.lower())
        self.assertNotIn("--unregister", confirmation.lower())

        main_flow = self._without_function_definitions(content, powershell=True)
        self.assertNotIn("--unregister", main_flow.lower())
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

    def test_wsl_lifecycle_uses_literal_paths_and_injectable_backend(self) -> None:
        for relative_path in WSL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._without_comments(
                    self._read_required(relative_path), powershell=True
                )
                self.assertIn("$WslExecutable", content)
                self.assertRegex(content, r"(?i)-LiteralPath\b")
                self.assertRegex(content, r"(?i)\[IO\.Path\]::GetFullPath\(")
                self.assertRegex(content, r"(?i)-replace\s+[\"']`0[\"']")
                self.assertRegex(content, r"(?i)-ceq\s+\$DistroName\b")

    def test_wsl_create_pins_partial_download_and_atomic_move(self) -> None:
        content = self._without_comments(
            self._read_required("environment/wsl/create.ps1"), powershell=True
        )
        self.assertIn("MINIOS_WSL_IMAGE_SHA256", content)
        self.assertIn(".partial", content)
        self.assertRegex(content, r"(?i)Get-FileHash\b[^\r\n]*SHA256")
        self.assertRegex(content, r"(?i)Move-Item\s+-LiteralPath\b")
        self.assertRegex(content, r"(?i)--import\b")
        self.assertRegex(content, r"(?i)--version\s+2\b")
        self.assertRegex(content, r"(?i)Assert-WslDistributionOwnership")

    def test_wsl_backup_refuses_overwrite_and_only_exports_exact_name(self) -> None:
        content = self._without_comments(
            self._read_required("environment/wsl/backup.ps1"), powershell=True
        )
        self.assertRegex(content, r"(?i)Test-Path\s+-LiteralPath\s+\$ExportPath")
        self.assertRegex(content, r"(?i)--terminate\s+(?:--\s+)?\$DistroName\b")
        self.assertRegex(content, r"(?i)--export\s+(?:--\s+)?\$DistroName\b")
        self.assertNotRegex(content, r"(?i)--export\s+[^$\r\n]")

    def test_wsl_backup_rechecks_artifacts_after_terminate(self) -> None:
        content = self._without_comments(
            self._read_required("environment/wsl/backup.ps1"), powershell=True
        )
        terminate = content.find("--terminate $DistroName")
        export = content.find("--export $DistroName")
        self.assertGreaterEqual(terminate, 0)
        self.assertGreater(export, terminate)
        window = content[terminate:export]
        self.assertRegex(window, r"(?i)Test-Path\s+-LiteralPath\s+\$ExportPath")
        self.assertRegex(window, r"(?i)Test-Path\s+-LiteralPath\s+\$PartialPath")

    def test_bootstrap_has_separate_privilege_phases_and_atomic_package_lock(
        self,
    ) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        writer = self._without_comments(
            self._read_required("environment/lib/package_state_writer.py")
        )
        for token in (
            "--system-only",
            "--toolchain-only",
            "apt-get",
            "dpkg-query",
            "apt-packages.lock.partial",
            "build_toolchain.sh",
            "sudo -n",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)
        self.assertRegex(content, r"(?m)^\s*if\s+\(\(\s*EUID\s*!=\s*0\s*\)\)")
        self.assertIn("os.replace", writer)
        self.assertNotIn("NOPASSWD", content)

    def test_wsl_ownership_gates_require_lxss_version_two(self) -> None:
        for relative_path in (
            "environment/wsl/create.ps1",
            "environment/wsl/enter.ps1",
            "environment/wsl/backup.ps1",
            "environment/wsl/destroy.ps1",
        ):
            with self.subTest(path=relative_path):
                content = self._without_comments(
                    self._read_required(relative_path), powershell=True
                )
                ownership = self._function_body(
                    content, "Assert-WslDistributionOwnership", powershell=True
                )
                self.assertRegex(ownership, r"(?i)\.Version\b")
                self.assertRegex(ownership, r"(?i)(?:-ne|-cne)\s*2\b")

    def test_bootstrap_and_verify_require_runtime_isolation_facts(self) -> None:
        for relative_path in (
            "environment/bootstrap-inside.sh",
            "environment/verify.sh",
        ):
            with self.subTest(path=relative_path):
                content = self._without_comments(self._read_required(relative_path))
                for token in (
                    "/proc/sys/kernel/osrelease",
                    "/proc/version",
                    "WSL2",
                    "/proc/1/cgroup",
                    "/proc/1/mountinfo",
                    "/.dockerenv",
                    "/run/.containerenv",
                ):
                    self.assertIn(token, content)

    def test_verify_invokes_runtime_and_instance_identity_checks(self) -> None:
        content = self._without_comments(self._read_required("environment/verify.sh"))
        isolation_gate = content[
            content.index('if [[ "${MINIOS_CONTAINER:-}"') : content.index(
                "printf 'environment_kind=", content.index('if [[ "${MINIOS_CONTAINER:-}"')
            )
        ].replace("\\\n", " ")
        self.assertRegex(
            isolation_gate,
            r"elif\s+\[\[[\s\S]*?\]\]\s*"
            r"&&\s*verify_wsl2_runtime_identity\s*"
            r"&&\s*verify_wsl_instance_identity\s*;\s*then",
        )

    def test_package_state_is_prepared_and_validated_before_apt(self) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        system_phase = self._function_body(
            content, "run_system_phase", powershell=False
        )
        prepare_position = system_phase.find("--prepare-package-state")
        apt_position = system_phase.find("apt-get update")
        self.assertGreaterEqual(prepare_position, 0)
        self.assertGreater(apt_position, prepare_position)
        state_gate = self._function_body(
            content, "validate_package_state_directory", powershell=False
        )
        for token in ("realpath", "stat", "target_uid", "022", "symlink"):
            self.assertIn(token, state_gate)

    def test_wsl_identity_record_is_provisioned_from_lxss_gate(self) -> None:
        create = self._without_comments(
            self._read_required("environment/wsl/create.ps1"), powershell=True
        )
        bootstrap = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        verify = self._without_comments(self._read_required("environment/verify.sh"))
        provision_call = create.find("Invoke-WslIdentityProvision")
        ownership_call = create.find("Assert-WslDistributionOwnership")
        self.assertGreater(provision_call, ownership_call)
        for token in (
            "--provision-wsl-identity",
            "--expected-distro",
            "--registration-id",
            "--base-path-sha256",
        ):
            self.assertIn(token, create)
        for content in (bootstrap, verify):
            self.assertIn("/etc/miniorangeos/instance.identity", content)
            self.assertIn("registration_id", content)
            self.assertIn("base_path_sha256", content)
        self.assertIn("MINIOS_WSL_IDENTITY_FILE", bootstrap)
        self.assertIn("测试覆盖仅允许", bootstrap)

    def test_package_lock_helper_uses_cloexec_openat_and_process_local_lock(self) -> None:
        bootstrap = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        writer = self._without_comments(
            self._read_required("environment/lib/package_state_writer.py")
        )
        system_phase = self._function_body(
            bootstrap, "run_system_phase", powershell=False
        )
        for token in (
            "os.open",
            "dir_fd=",
            "os.O_DIRECTORY",
            "os.O_NOFOLLOW",
            "os.O_CLOEXEC",
            "os.O_CREAT",
            "os.O_EXCL",
            "fcntl.flock",
            "os.fstat",
            "os.fsync",
            "os.fchmod",
            "os.fchown",
            "os.replace",
            "src_dir_fd=",
            "dst_dir_fd=",
            "os.unlink",
            "signal.signal",
            "signal.pthread_sigmask",
            "expected_partial_identity",
            "state_restricted",
        ):
            self.assertIn(token, writer)
        apt_position = system_phase.find("apt-get update")
        write_position = system_phase.find("write_package_lock_with_helper")
        self.assertGreaterEqual(apt_position, 0)
        self.assertGreater(write_position, apt_position)
        self.assertNotIn("open_and_lock_package_state", system_phase)
        self.assertNotIn("flock", system_phase)
        self.assertNotIn("exec {package_state_fd}", bootstrap)
        for forbidden in ("subprocess", "os.system", "os.fork", "os.exec"):
            self.assertNotIn(forbidden, writer)
        write_body = writer[
            writer.index("def write_package_lock(") : writer.index("def main()")
        ]
        self.assertGreaterEqual(write_body.count("assert_chain_unchanged"), 3)
        self.assertLess(
            write_body.index("assert_chain_unchanged"),
            write_body.index("create_partial"),
        )
        self.assertLess(
            write_body.rindex("assert_chain_unchanged", 0, write_body.index("os.replace")),
            write_body.index("os.replace"),
        )
        block_position = write_body.index("signal.pthread_sigmask")
        restrict_position = write_body.index("os.fchown(state_fd, 0, 0)")
        restore_position = write_body.rindex("os.fchown(")
        unblock_position = write_body.rindex("signal.pthread_sigmask")
        self.assertLess(block_position, restrict_position)
        self.assertLess(restore_position, unblock_position)
        for token in (
            "--recover-only",
            "recover_package_state",
            "PARTIAL_NAME_PATTERN",
            "follow_symlinks=False",
        ):
            self.assertIn(token, writer)
        system_phase = self._function_body(
            bootstrap, "run_system_phase", powershell=False
        )
        self.assertLess(
            system_phase.index("recover_package_state_after_crash"),
            system_phase.index("--prepare-package-state"),
        )

    def test_bootstrap_gates_identity_user_and_environment_before_mutation(
        self,
    ) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        for token in (
            "/etc/os-release",
            "VERSION_ID",
            "WSL_DISTRO_NAME",
            "MINIOS_CONTAINER",
            "MINIOS_ENV_ROOT",
            "/opt/miniorangeos-dev",
            "runuser",
            "lstat",
            "--write-package-lock",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)
        gate_positions = [
            content.find("validate_isolation_identity"),
            content.find("resolve_target_user"),
            content.find("validate_environment_root"),
        ]
        apt_position = content.find("apt-get update")
        self.assertTrue(all(position >= 0 for position in gate_positions))
        self.assertGreater(apt_position, max(gate_positions))
        root_phase = self._function_body(
            content, "run_system_phase", powershell=False
        )
        self.assertNotRegex(
            root_phase,
            r"(?m)^\s*(?:install|chown|chmod|mktemp|mv)\b[^\r\n]*"
            r"(?:environment_root|state_directory|lock_path)",
            "root 主流程不得在目标用户路径执行写入或权限变更",
        )

    def test_bootstrap_missing_user_creation_is_fixed_and_test_injection_scoped(
        self,
    ) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        for token in (
            "/usr/sbin/useradd",
            "--create-home",
            "--shell",
            "/bin/bash",
            "MINIOS_BOOTSTRAP_TEST_ROOT",
            "MINIOS_USERADD_EXECUTABLE",
            "MINIOS_EXPECTED_MINIOS_HOME",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)
        self.assertRegex(
            content,
            r"(?m)^\s*if\s+!\s+[\"']\$useradd_command[\"']\s+"
            r"--create-home\s+--shell\s+/bin/bash\s+--\s+minios\b",
        )
        preflight = self._function_body(content, "preflight", powershell=False)
        ordered_gates = (
            "validate_ubuntu_release",
            "validate_isolation_identity",
            "ensure_target_user",
            "validate_environment_root",
        )
        positions = [preflight.find(token) for token in ordered_gates]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(positions, sorted(positions))

    def test_bootstrap_fake_harness_uses_atomic_owned_temp_root(self) -> None:
        content = self._read_required("tests/host/test_wsl_lifecycle.ps1")
        for token in (
            "/usr/bin/mktemp -d /tmp/minios-bootstrap-test-XXXXXXXX",
            "/usr/bin/realpath -e",
            "/usr/bin/stat -c",
            "/usr/bin/rm -rf -- \"$root\"",
            "TMPDIR",
            "validate_test_root",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)

    def test_bootstrap_only_accepts_trusted_standard_os_release_link(self) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        for token in (
            "readlink",
            "../usr/lib/os-release",
            "/usr/lib/os-release",
            "realpath -e",
            "symbolic link",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)
        preflight = self._function_body(content, "preflight", powershell=False)
        self.assertLess(
            preflight.find("validate_ubuntu_release"),
            preflight.find("ensure_target_user"),
        )

    def test_bootstrap_allows_only_safe_root_or_target_owned_ancestors(
        self,
    ) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        body = self._function_body(
            content, "validate_user_owned_existing_components", powershell=False
        )
        for token in (
            "item_uid",
            "target_uid",
            "'0'",
            "current",
            "candidate",
            "mode_is_root_safe",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)
        self.assertIn("最终 environment root 必须由目标用户拥有", body)
        resolve = self._function_body(
            content, "resolve_target_user", powershell=False
        )
        self.assertIn("home_mode", resolve)
        self.assertIn("mode_is_root_safe", resolve)

    def test_bootstrap_checks_lexical_environment_path_before_resolution(
        self,
    ) -> None:
        content = self._without_comments(
            self._read_required("environment/bootstrap-inside.sh")
        )
        body = self._function_body(
            content, "validate_environment_root", powershell=False
        )
        for token in (
            "realpath -ms",
            "lexical_root",
            "resolved_root",
            "assert_no_symlink_components",
            "validate_user_owned_existing_components",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)
        lexical_check = body.find("validate_user_owned_existing_components")
        resolved_check = body.find("realpath -e")
        self.assertGreaterEqual(lexical_check, 0)
        self.assertGreater(resolved_check, lexical_check)

    def test_wsl_scripts_use_single_segment_test_names_and_skip_bootstrap(
        self,
    ) -> None:
        expected_pattern = (
            "^MiniOrangeOS-Dev-Test-[A-Za-z0-9][A-Za-z0-9_-]*$"
        )
        for relative_path in WSL_SCRIPTS:
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertIn(expected_pattern, content)
                self.assertIn("Assert-WslDistributionOwnership", content)
        create = self._read_required("environment/wsl/create.ps1")
        self.assertIn("$SkipBootstrap", create)
        self.assertRegex(
            create,
            r"(?is)if\s*\(\s*\$Bootstrap\s+-and\s+\$SkipBootstrap\s*\)"
            r"\s*\{[^}]*\bthrow\b",
        )

    def test_containerfile_pins_ubuntu_digest_and_project_labels(self) -> None:
        content = self._read_required("environment/Containerfile")
        self.assertIn(
            "FROM ubuntu:noble-20260509.1@sha256:"
            "786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54",
            content,
        )
        self.assertIn("org.miniorangeos.project=MiniOrangeOS", content)
        self.assertIn("org.miniorangeos.task=T01", content)
        self.assertIn("org.miniorangeos.source-version=T01", content)
        self.assertIn("MINIOS_CONTAINER=1", content)
        self.assertIn("MINIOS_ENV_ROOT=/opt/miniorangeos-dev", content)
        self.assertIn("bootstrap-inside.sh --system-only", content)
        self.assertIn("bootstrap-inside.sh --toolchain-only", content)
        self.assertNotRegex(content, r"(?m)^COPY\s+environment/?\s")
        for build_input in (
            "environment/versions.env",
            "environment/lib/common.sh",
            "environment/bootstrap-inside.sh",
            "tools/build_toolchain.sh",
        ):
            with self.subTest(build_input=build_input):
                self.assertRegex(
                    content,
                    rf"(?m)^COPY\s+{re.escape(build_input)}\s+",
                )
        self.assertRegex(content, r"(?m)^USER minios\s*$")
        self.assertRegex(content, r"(?m)^WORKDIR /workspace\s*$")
        self.assertNotRegex(content, r"(?m)^USER root\s*$[\s\S]*\Z")

    def test_ubuntu_adapters_share_strict_backend_library(self) -> None:
        library = self._read_required("environment/ubuntu/lib.sh")
        for token in (
            "MINIOS_CONTAINER_BACKEND",
            "podman",
            "docker",
            "container-storage",
            "graphroot",
            "runroot",
            "miniorangeos-dev-builder",
            "container.env",
            "container.lock",
            "flock",
            "MINIOS_CONTAINER_INTENT",
            "org.miniorangeos.intent",
        ):
            with self.subTest(token=token):
                self.assertIn(token, library)
        for relative_path in (
            "environment/ubuntu/create.sh",
            "environment/ubuntu/run.sh",
            "environment/ubuntu/destroy.sh",
        ):
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertIn('source "$SCRIPT_DIR/lib.sh"', content)

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
        self.assertIn("state_container_builder", content)
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
                self.assertRegex(content, r"(?:state_)?container_builder")

    def test_environment_documentation_lists_public_interfaces(self) -> None:
        content = self._read_required("docs/environment.md")
        for relative_path in PUBLIC_T01_FILES:
            with self.subTest(path=relative_path):
                self.assertIn(relative_path, content)
        self.assertIn("environment/ubuntu/destroy.sh --all", content)
        for relative_path in ("docs/environment.md", "environment/README.md"):
            with self.subTest(path=relative_path):
                lifecycle_docs = self._read_required(relative_path)
                self.assertIn("无参数只预览且不删除任何资源", lifecycle_docs)
                self.assertIn("只有 `--all`", lifecycle_docs)

    def test_public_environment_docs_exclude_tool_output_metadata(self) -> None:
        metadata = re.compile(r"^(?:Exit code:|Wall time:|Output:)(?:\s|$)", re.MULTILINE)
        for relative_path in ("docs/environment.md", "docs/testing.md"):
            with self.subTest(path=relative_path):
                content = self._read_required(relative_path)
                self.assertIsNone(metadata.search(content))

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
