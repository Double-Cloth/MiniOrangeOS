# T00 项目初始化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 MiniOrangeOS 的可追踪仓库骨架、Windows 权威工作树与 WSL 测试边界、工程规范、静态契约测试及文档闭环。

**Architecture:** 当前 Windows 项目目录是唯一权威工作树，文件修改和 Git 由 Windows 执行；专用 Ubuntu 24.04 WSL2 发行版 MiniOrangeOS-Dev 只负责 Linux 构建和测试。T00 不实现操作系统功能，只建立后续 T01–T74 依赖的目录、规则、测试和记录入口。

**Tech Stack:** Git for Windows、PowerShell 7、WSL2 2.6.3、Ubuntu 24.04、Python 3 标准库 unittest、Markdown。

## Global Constraints

- 所有回复、解释、文档和代码注释使用中文；代码标识符、命令和第三方 API 名称保持原文。
- 唯一权威工作树固定为 D:/DC/program-projects/OTHER/MiniOrangeOS。
- Linux 测试路径固定为 /mnt/d/DC/program-projects/OTHER/MiniOrangeOS。
- 专用发行版名称固定为 MiniOrangeOS-Dev，环境集中目录固定为 D:/ApplicationData/MiniOrangeOS。
- Windows Git 是唯一操作该工作树的 Git；禁止在 WSL 中运行 Git。
- Linux 构建、QEMU、GDB 和测试只能在 MiniOrangeOS-Dev 中执行。
- 不修改 Windows PATH、注册表、全局 Git 配置或 Linux 全局 Shell 配置。
- 文本文件必须为 UTF-8 和 LF；构建产物、磁盘镜像、工具链、venv 和环境状态不得提交。
- T00 不添加 Boot、Loader、Kernel、用户态或文件系统功能代码，不安装项目工具链。
- Git 分支固定为 feature/T00-project-bootstrap；提交使用 type(scope): summary，并在正文包含 Refs: T00。
- 实际未运行的命令不得记录为 PASS；失败时停止合并并更新 docs/problems.md。

---

## File Structure

本计划创建或修改以下文件，每个文件只有一个清晰职责：

- Create: .gitignore — 排除构建、镜像、工具链、venv、缓存和日志。
- Create: .gitattributes — 强制文本格式和 Linux 脚本可执行位策略。
- Create: LICENSE — MIT License。
- Create: README.md — 项目入口、开发边界和当前状态。
- Create: CONTRIBUTING.md — 任务分支、测试、提交、合并和文档规则。
- Create: tests/__init__.py — Python 测试包标记。
- Create: tests/host/__init__.py — 宿主契约测试包标记。
- Create: tests/host/test_project_layout.py — T00 目录、元文件、忽略规则和 LF 契约。
- Create: docs/coding-standards.md — C、NASM、Python、Shell、命名、整数和错误码约定。
- Create: docs/progress.md — TXX 和里程碑进度表。
- Create: docs/review-notes.md — 里程碑阅读、理解、问题和心得。
- Create: docs/decisions/0001-windows-worktree-wsl-tests.md — 用户指定环境决策。
- Create: docs/task-reports/T00-project-bootstrap.md — T00 的实际任务报告。
- Create: environment/README.md — 环境目录职责和 T01 边界。
- Rename: MiniOrangeOS_Codex_Project_Plan_v1.1.md → PROJECT_PLAN.md — 消除文件名版本与文档版本不一致，建立稳定入口。
- Modify: PROJECT_PLAN.md — 修订 Windows 工作树与 WSL 测试规则，版本升为 1.3。
- Modify: docs/README.md — 纳入新文档和稳定计划入口。
- Modify: docs/environment.md — 改为 Windows 权威工作树、WSL 测试模型。
- Modify: docs/development-workflow.md — 明确 Windows Git、WSL 测试和自动 no-ff 合并。
- Modify: docs/testing.md — 明确有效测试证据来自 MiniOrangeOS-Dev。
- Modify: docs/provenance.md — 登记 T00 规范和契约测试状态。
- Modify: docs/problems.md — 记录 /mnt/d 的性能和权限语义风险。
- Track: boot、kernel、user、tools、tests、environment 的计划目录骨架。

---

### Task 1: 一次性引导 MiniOrangeOS-Dev 测试环境

**Files:**
- No repository files changed.
- Create external: D:/ApplicationData/MiniOrangeOS/rootfs
- Create external: D:/ApplicationData/MiniOrangeOS/downloads
- Create external: D:/ApplicationData/MiniOrangeOS/exports
- Create external: D:/ApplicationData/MiniOrangeOS/logs

**Interfaces:**
- Consumes: Windows WSL 2.6.3、在线发行版 Ubuntu-24.04、用户对 D:/ApplicationData/MiniOrangeOS 的明确授权。
- Produces: 可通过 wsl.exe -d MiniOrangeOS-Dev 调用的 Ubuntu 24.04 测试环境，默认用户 minios，可访问 /mnt/d 权威工作树。

- [ ] **Step 1: 执行无副作用预检**

Run from PowerShell:

~~~powershell
$target = 'D:\ApplicationData\MiniOrangeOS'
$existing = (wsl.exe --list --quiet) -replace [char]0
if ($existing -contains 'MiniOrangeOS-Dev') {
    throw 'MiniOrangeOS-Dev 已存在，停止以避免覆盖。'
}
if ((Test-Path -LiteralPath $target) -and
    (Get-ChildItem -Force -LiteralPath $target | Select-Object -First 1)) {
    throw "$target 非空，停止以避免覆盖未知数据。"
}
$freeGiB = [math]::Round((Get-PSDrive -Name D).Free / 1GB, 2)
if ($freeGiB -lt 20) {
    throw "D 盘可用空间不足 20 GiB：$freeGiB GiB"
}
wsl.exe --status
wsl.exe --list --online
~~~

Expected: MiniOrangeOS-Dev 不存在，目标目录为空或不存在，可用空间至少 20 GiB，在线列表包含 Ubuntu-24.04。

- [ ] **Step 2: 下载、校验并导入官方 Ubuntu 24.04 WSL rootfs**

Run from PowerShell:

~~~powershell
$root = 'D:\ApplicationData\MiniOrangeOS'
$baseUri = 'https://cloud-images.ubuntu.com/wsl/releases/noble/current'
$imageName = 'ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz'
$imagePath = Join-Path $root "downloads\$imageName"
$sumsPath = Join-Path $root 'downloads\SHA256SUMS'
@('downloads', 'exports', 'logs') |
    ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $root $_) | Out-Null }
Invoke-WebRequest -Uri "$baseUri/$imageName" -OutFile $imagePath
Invoke-WebRequest -Uri "$baseUri/SHA256SUMS" -OutFile $sumsPath
$escapedName = [regex]::Escape($imageName)
$sumLines = @(
    Get-Content -LiteralPath $sumsPath |
        Where-Object { $_ -match "\s+\*?$escapedName$" }
)
if ($sumLines.Count -ne 1) {
    throw "SHA256SUMS 中 $imageName 的记录数不是 1：$($sumLines.Count)"
}
$sumLine = $sumLines[0]
$expectedHash = ($sumLine -split '\s+')[0].ToLowerInvariant()
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $imagePath).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) {
    throw "rootfs SHA-256 不匹配：expected=$expectedHash actual=$actualHash"
}
wsl.exe --import MiniOrangeOS-Dev 'D:\ApplicationData\MiniOrangeOS\rootfs' $imagePath --version 2
if ($LASTEXITCODE -ne 0) {
    throw "WSL 导入失败，exit=$LASTEXITCODE"
}
~~~

Expected: 下载文件的 SHA-256 与同一 Ubuntu 官方发布目录的 SHA256SUMS 匹配；wsl.exe --list --verbose 显示 MiniOrangeOS-Dev，VERSION 为 2；所有环境载荷位于授权目录。

- [ ] **Step 3: 创建普通用户并配置该发行版的 NTFS metadata 挂载**

Run from PowerShell:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -u root -- bash -lc '
set -euo pipefail
if ! id minios >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash minios
fi
install -d -o minios -g minios /home/minios/.local/share/miniorangeos-dev
cat > /etc/wsl.conf <<'WSLCONF'
[user]
default=minios

[automount]
enabled=true
options=metadata,umask=022,fmask=011
mountFsTab=false
WSLCONF
'
if ($LASTEXITCODE -ne 0) {
    throw "WSL 用户配置失败，exit=$LASTEXITCODE"
}
wsl.exe --terminate MiniOrangeOS-Dev
~~~

Expected: /etc/wsl.conf 只影响 MiniOrangeOS-Dev；默认用户为 minios；未修改 Windows 或其他发行版配置。

- [ ] **Step 4: 验证发行版、默认用户和工作树映射**

Run from PowerShell:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
set -euo pipefail
test "$(id -un)" = "minios"
. /etc/os-release
test "$VERSION_ID" = "24.04"
test -d /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
test -r /mnt/d/DC/program-projects/OTHER/MiniOrangeOS/PROJECT_PLAN.md ||
test -r /mnt/d/DC/program-projects/OTHER/MiniOrangeOS/MiniOrangeOS_Codex_Project_Plan_v1.1.md
printf "bootstrap_user=%s\n" "$(id -un)"
printf "bootstrap_ubuntu=%s\n" "$VERSION_ID"
printf "bootstrap_worktree=PASS\n"
'
~~~

Expected:

~~~text
bootstrap_user=minios
bootstrap_ubuntu=24.04
bootstrap_worktree=PASS
~~~

---

### Task 2: 先建立失败的仓库契约测试

**Files:**
- Create: tests/__init__.py
- Create: tests/host/__init__.py
- Create: tests/host/test_project_layout.py

**Interfaces:**
- Consumes: Python 3 标准库、仓库根目录。
- Produces: ProjectLayoutTests，约束必需目录、必需根文件、忽略规则、属性规则、文档入口和 LF 行尾。

- [ ] **Step 1: 创建测试包标记**

tests/__init__.py:

~~~python
"""MiniOrangeOS 测试包。"""
~~~

tests/host/__init__.py:

~~~python
"""不依赖 QEMU 的宿主契约测试包。"""
~~~

- [ ] **Step 2: 编写完整且当前必然失败的布局测试**

tests/host/test_project_layout.py:

~~~python
"""验证 T00 仓库骨架和文本策略。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DIRECTORIES = (
    "boot/stage1",
    "boot/stage2",
    "boot/include",
    "kernel/arch/x86",
    "kernel/core",
    "kernel/mm",
    "kernel/proc",
    "kernel/syscall",
    "kernel/drivers",
    "kernel/block",
    "kernel/fs",
    "kernel/include",
    "user/crt",
    "user/libc",
    "user/programs",
    "tools",
    "tests/host",
    "tests/qemu",
    "tests/fixtures",
    "environment/wsl",
    "environment/ubuntu",
    "docs/decisions",
    "docs/task-reports",
)

REQUIRED_FILES = (
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "PROJECT_PLAN.md",
    "docs/coding-standards.md",
    "docs/progress.md",
    "docs/review-notes.md",
    "docs/decisions/0001-windows-worktree-wsl-tests.md",
    "environment/README.md",
)

REQUIRED_IGNORE_RULES = {
    "/build/",
    "*.img",
    "*.iso",
    "*.o",
    "*.elf",
    "*.bin",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    "/.cache/",
    "/environment/.state/",
}

REQUIRED_ATTRIBUTE_RULES = {
    "* text=auto eol=lf",
    "*.ps1 text eol=lf",
    "*.sh text eol=lf",
    "Makefile text eol=lf",
}

TEXT_SUFFIXES = {
    ".asm",
    ".c",
    ".h",
    ".ld",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".txt",
    ".yml",
    ".yaml",
}


class ProjectLayoutTests(unittest.TestCase):
    def test_required_directories_exist(self) -> None:
        missing = [path for path in REQUIRED_DIRECTORIES if not (ROOT / path).is_dir()]
        self.assertEqual([], missing, f"缺少目录：{missing}")

    def test_required_files_exist(self) -> None:
        missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"缺少文件：{missing}")

    def test_gitignore_contains_required_rules(self) -> None:
        path = ROOT / ".gitignore"
        self.assertTrue(path.is_file(), "缺少文件：.gitignore")
        rules = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(set(), REQUIRED_IGNORE_RULES - rules)

    def test_gitattributes_contains_required_rules(self) -> None:
        path = ROOT / ".gitattributes"
        self.assertTrue(path.is_file(), "缺少文件：.gitattributes")
        rules = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(set(), REQUIRED_ATTRIBUTE_RULES - rules)

    def test_text_files_use_lf(self) -> None:
        bad_files: list[str] = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or not path.is_file():
                continue
            if path.suffix in TEXT_SUFFIXES or path.name in {"Makefile", "Containerfile"}:
                if b"\r\n" in path.read_bytes():
                    bad_files.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], bad_files, f"发现 CRLF：{bad_files}")

    def test_readme_records_authoritative_worktree(self) -> None:
        path = ROOT / "README.md"
        self.assertTrue(path.is_file(), "缺少文件：README.md")
        content = path.read_text(encoding="utf-8")
        self.assertIn("D:\\DC\\program-projects\\OTHER\\MiniOrangeOS", content)
        self.assertIn("MiniOrangeOS-Dev", content)
        self.assertIn("/mnt/d/DC/program-projects/OTHER/MiniOrangeOS", content)

    def test_project_plan_has_stable_name(self) -> None:
        self.assertTrue((ROOT / "PROJECT_PLAN.md").is_file())
        self.assertFalse((ROOT / "MiniOrangeOS_Codex_Project_Plan_v1.1.md").exists())


if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 3: 在 MiniOrangeOS-Dev 中运行测试并确认失败**

Run from PowerShell:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
'
~~~

Expected: FAIL；至少报告缺少 boot/stage1、.gitignore、README.md 或 PROJECT_PLAN.md。若测试意外通过，停止并检查测试是否指向错误根目录。

- [ ] **Step 4: 提交失败测试**

Run from PowerShell:

~~~powershell
git add -- tests/__init__.py tests/host/__init__.py tests/host/test_project_layout.py
git diff --cached --check
git commit -m "test(repo): define T00 project layout contract" -m "Add failing host tests for the required directory skeleton, repository metadata, LF policy, and authoritative worktree documentation." -m "Refs: T00"
~~~

Expected: 新提交只包含测试契约；测试仍因实现缺失而失败。

---

### Task 3: 创建目录骨架和仓库文本策略

**Files:**
- Create: .gitignore
- Create: .gitattributes
- Create: LICENSE
- Rename: MiniOrangeOS_Codex_Project_Plan_v1.1.md → PROJECT_PLAN.md
- Create: leaf directory .gitkeep files listed below

**Interfaces:**
- Consumes: Task 2 的 REQUIRED_DIRECTORIES、REQUIRED_FILES、REQUIRED_IGNORE_RULES、REQUIRED_ATTRIBUTE_RULES。
- Produces: 可被干净 clone 复现的目录骨架和 Git 文本/忽略策略。

- [ ] **Step 1: 写入精确的忽略规则**

.gitignore:

~~~gitignore
# 构建和镜像产物
/build/
*.o
*.a
*.elf
*.bin
*.img
*.iso
*.map
*.d

# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/

# 项目隔离环境的仓库内状态
/.cache/
/environment/.state/
/environment/.venv/
/environment/toolchain/

# 测试和调试临时文件
*.log
*.pid
*.tmp
*.swp

# 编辑器和系统文件
.idea/
.vscode/
.DS_Store
Thumbs.db
~~~

- [ ] **Step 2: 写入精确的文本属性规则**

.gitattributes:

~~~gitattributes
* text=auto eol=lf

*.asm text eol=lf
*.c text eol=lf
*.h text eol=lf
*.ld text eol=lf
*.md text eol=lf
*.py text eol=lf
*.sh text eol=lf
*.txt text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
Makefile text eol=lf
Containerfile text eol=lf

*.ps1 text eol=lf

*.bin binary
*.elf binary
*.img binary
*.iso binary
*.png binary
*.jpg binary
*.tar binary
*.gz binary
*.xz binary
~~~

- [ ] **Step 3: 添加 MIT License**

LICENSE:

~~~text
MIT License

Copyright (c) 2026 MiniOrangeOS contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
~~~

- [ ] **Step 4: 建立稳定计划入口**

Run from PowerShell:

~~~powershell
git mv MiniOrangeOS_Codex_Project_Plan_v1.1.md PROJECT_PLAN.md
~~~

Expected: git status 显示一次 rename；文档内容不丢失。

- [ ] **Step 5: 创建所有受控叶目录**

Create one .gitkeep file containing the single line “由 Git 跟踪的空目录；功能文件由对应 TXX 任务添加。” in each path:

~~~text
boot/stage1/.gitkeep
boot/stage2/.gitkeep
boot/include/.gitkeep
kernel/arch/x86/.gitkeep
kernel/core/.gitkeep
kernel/mm/.gitkeep
kernel/proc/.gitkeep
kernel/syscall/.gitkeep
kernel/drivers/.gitkeep
kernel/block/.gitkeep
kernel/fs/.gitkeep
kernel/include/.gitkeep
user/crt/.gitkeep
user/libc/.gitkeep
user/programs/.gitkeep
tools/.gitkeep
tests/qemu/.gitkeep
tests/fixtures/.gitkeep
environment/wsl/.gitkeep
environment/ubuntu/.gitkeep
docs/decisions/.gitkeep
docs/task-reports/.gitkeep
~~~

- [ ] **Step 6: 重新运行契约测试并确认只剩文档类失败**

Run:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
'
~~~

Expected: 目录、.gitignore、.gitattributes、LICENSE 和 PROJECT_PLAN 测试 PASS；README、CONTRIBUTING、coding standards、progress、review notes、decision 和 environment README 仍使测试 FAIL。

- [ ] **Step 7: 提交目录和仓库策略**

Run:

~~~powershell
git add -- .gitignore .gitattributes LICENSE PROJECT_PLAN.md boot kernel user tools tests/qemu tests/fixtures environment/wsl environment/ubuntu docs/decisions docs/task-reports
git diff --cached --check
git commit -m "chore(repo): add T00 project skeleton" -m "Create the planned directory structure, stable project-plan entry, repository ignore rules, LF policy, and MIT license." -m "Refs: T00"
~~~

Expected: 提交成功；不包含 build、镜像或环境外部文件。

---

### Task 4: 编写项目入口、贡献规范和编码规范

**Files:**
- Create: README.md
- Create: CONTRIBUTING.md
- Create: docs/coding-standards.md
- Create: environment/README.md

**Interfaces:**
- Consumes: M0 设计规格、PROJECT_PLAN.md、Windows 权威工作树决策。
- Produces: 开发者可直接执行的项目入口和一致编码规则。

- [ ] **Step 1: 编写项目 README**

README.md:

~~~markdown
# MiniOrangeOS

MiniOrangeOS 是一个从零实现的 x86 32 位 BIOS 教学操作系统。目标包括自写 Stage 1/Stage 2、ELF32 高半内核、分页、Ring 3、抢占式调度、int 0x80 系统调用、用户态 Shell、ATA PIO 和持久化 MiniFS。

## 当前状态

当前处于 M0 工程基础阶段。尚未实现可启动内核；真实完成状态以 docs/progress.md、任务报告和测试日志摘要为准。

## 权威工作树

唯一权威工作树：

    D:\DC\program-projects\OTHER\MiniOrangeOS

源码和文档在该目录编辑，Git 只由 Windows Git 操作。禁止在 WSL 中运行 Git 或维护第二份活动工作树。

## Linux 构建与测试

专用测试发行版：MiniOrangeOS-Dev

WSL 路径：

    /mnt/d/DC/program-projects/OTHER/MiniOrangeOS

所有 Linux 构建、QEMU、GDB 和测试都通过该发行版执行。T01 完成后使用 environment/with-env.sh 注入项目工具路径。

## 文档入口

- PROJECT_PLAN.md：任务顺序与完成定义。
- docs/README.md：专题文档索引。
- docs/superpowers/specs/2026-07-13-m0-foundation-design.md：M0 设计规格。
- docs/progress.md：实际进度。
- CONTRIBUTING.md：分支、提交、测试和合并规则。

## 范围限制

最低版本不实现 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接、Swap、完整 POSIX、文件系统日志、权限系统或复杂 Shell。

## License

MIT
~~~

- [ ] **Step 2: 编写贡献和 Git 流程**

CONTRIBUTING.md:

~~~markdown
# MiniOrangeOS 贡献规范

## 开始任务

1. 阅读 PROJECT_PLAN.md、docs/README.md、docs/development-workflow.md 和对应专题文档。
2. 确认 Windows Git 工作区干净。
3. 从 main 创建 feature/TXX-short-description。
4. 先补测试或可执行验收约束，再写最小实现。

## 工作树边界

- 文件修改和 Git：D:\DC\program-projects\OTHER\MiniOrangeOS。
- Linux 构建和测试：MiniOrangeOS-Dev 中的 /mnt/d/DC/program-projects/OTHER/MiniOrangeOS。
- 禁止在 WSL 中运行 Git。
- 禁止修改 Windows PATH、注册表、全局 Git 配置和 Linux 全局 Shell 配置。

## 提交

格式：

    type(scope): summary

    说明变更原因、关键设计和测试范围。

    Refs: TXX

允许类型：feat、fix、test、refactor、docs、build、chore。

## 合并

只有当前任务测试和已有回归测试真实通过、文档已同步、工作区无未解释文件时，才推送任务分支并使用 --no-ff 合并到 main。失败或未运行的测试必须记录，且禁止合并。

## 文档同步

每个任务至少更新：

- docs/progress.md；
- docs/task-reports/TXX-*.md；
- 对应专题文档；
- docs/provenance.md；
- 有问题时更新 docs/problems.md；
- 里程碑结束时更新 docs/review-notes.md。
~~~

- [ ] **Step 3: 编写编码、整数和错误码约定**

docs/coding-standards.md:

~~~markdown
# 编码规范

## 通用规则

- 所有文本（包括 PowerShell 脚本）使用 UTF-8 和 LF。
- 代码标识符、文件名和第三方 API 使用英文；注释和项目文档使用中文。
- 单个模块只承担一个职责；跨模块依赖通过头文件中的公开接口。
- 不引入未被当前 TXX 要求的框架、依赖或抽象。

## C11 Freestanding

- 文件名和函数名使用 snake_case。
- 类型名使用带模块前缀的 snake_case；宏和常量使用 UPPER_SNAKE_CASE。
- 公开函数必须有原型；内部函数使用 static。
- 使用 stdint.h 和 stddef.h 的定宽类型，不使用 int 表示磁盘地址、物理地址或结构序列化字段。
- 指针和长度运算必须检查溢出；禁止依赖宿主 libc 或 Linux ABI。
- 默认编译警告以 PROJECT_PLAN.md 第 3.2 节为准，警告不得静默忽略。

## NASM

- 使用 Intel 语法；标签使用 snake_case。
- 入口、调用约定、寄存器所有权和栈布局必须在相邻中文注释中说明。
- 魔数、选择子和端口号使用命名常量。

## Python 与 Shell

- Python 工具只使用显式 little-endian 编解码磁盘结构，不依赖对象内存布局。
- Shell 脚本以 set -euo pipefail 开始，对外部输入加引号并显式检查路径边界。
- PowerShell 删除或移动前使用 LiteralPath 和已解析绝对路径检查。

## 错误模型

成功返回 0 或非负结果；失败返回负错误码。项目稳定错误名为：

    EINVAL
    ENOENT
    EEXIST
    ENOMEM
    ENOSPC
    EIO
    EFAULT
    EBADF
    ENOTDIR
    EISDIR
    ENOTEMPTY

错误码数值由首次引入公共错误头的任务统一定义，之后内核和用户态从同一来源生成或引用，禁止手写两份编号。

Kernel panic 只用于不可恢复的内核不变量破坏。用户输入、损坏镜像和用户进程异常必须返回错误或终止当前进程。
~~~

- [ ] **Step 4: 编写 environment 目录职责**

environment/README.md:

~~~markdown
# environment 目录

本目录只管理 MiniOrangeOS 的隔离测试环境，不保存源码副本。

## 固定边界

- 发行版：MiniOrangeOS-Dev。
- Windows 环境根：D:\ApplicationData\MiniOrangeOS。
- 权威工作树：D:\DC\program-projects\OTHER\MiniOrangeOS。
- WSL 测试路径：/mnt/d/DC/program-projects/OTHER/MiniOrangeOS。

## 子目录职责

- wsl：创建、进入、备份和定向销毁专用 WSL2 发行版。
- ubuntu：真实 Ubuntu 上的 rootless OCI 复验入口。
- 仓库根层脚本：版本清单、临时环境注入、依赖引导和环境验证。

生命周期脚本由 T01 实现并验收。任何清理命令都必须先预览，只能删除带 MiniOrangeOS 明确名称或路径边界的资源。
~~~

- [ ] **Step 5: 运行契约测试并观察仍缺少进度类文档**

Run:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
'
~~~

Expected: README 权威路径测试 PASS；仍因 progress、review notes 和 decision 文件缺失而 FAIL。

- [ ] **Step 6: 提交项目入口和规范**

Run:

~~~powershell
git add -- README.md CONTRIBUTING.md docs/coding-standards.md environment/README.md
git diff --cached --check
git commit -m "docs(repo): define T00 engineering conventions" -m "Document the authoritative worktree, WSL-only Linux testing, task Git flow, coding conventions, integer use, and error model." -m "Refs: T00"
~~~

Expected: 提交成功，只包含入口和规范文档。

---

### Task 5: 同步权威文档并建立进度、决策和心得记录

**Files:**
- Modify: PROJECT_PLAN.md
- Modify: docs/README.md
- Modify: docs/environment.md
- Modify: docs/development-workflow.md
- Modify: docs/testing.md
- Modify: docs/provenance.md
- Modify: docs/problems.md
- Create: docs/progress.md
- Create: docs/review-notes.md
- Create: docs/decisions/0001-windows-worktree-wsl-tests.md

**Interfaces:**
- Consumes: 用户确认的 Windows 权威工作树决策、Task 4 的入口文档。
- Produces: 不再与实际工作方式冲突的权威计划和专题文档，以及可持续维护的状态记录。

- [ ] **Step 1: 将 PROJECT_PLAN.md 升为 1.3 并同步环境规则**

Apply these exact semantic changes:

1. 文档版本改为 1.3。
2. 修订记录新增：

~~~markdown
| 1.3 | 2026-07-13 | 按用户明确要求改为 Windows 项目目录作为唯一权威工作树；Windows Git 负责版本控制；MiniOrangeOS-Dev 只执行 Linux 构建、QEMU、GDB 和测试；环境载荷集中到 D:\ApplicationData\MiniOrangeOS |
~~~

3. 将所有“源码编辑和 Git 必须在 WSL 内”“Windows 不维护工作树”“禁止 Windows Git”的规则统一替换为：

~~~markdown
- 唯一权威工作树位于 D:\DC\program-projects\OTHER\MiniOrangeOS，由 Windows 侧 Codex 编辑并使用 Windows Git。
- MiniOrangeOS-Dev 通过 /mnt/d/DC/program-projects/OTHER/MiniOrangeOS 访问同一工作树，只执行 Linux 构建、QEMU、GDB 和测试，不运行 Git。
- 不创建第二份活动工作树；.gitattributes 强制跨环境文本格式。
~~~

4. 将环境集中目录示例和命令统一为 D:\ApplicationData\MiniOrangeOS。
5. 保留“不安装 Windows 原生编译器、NASM、QEMU、GDB”和“不修改宿主全局配置”的约束。

- [ ] **Step 2: 同步专题文档**

Make these exact updates:

- docs/README.md：把 PROJECT_PLAN.md 设为计划入口，并在阅读顺序加入 coding-standards、progress、review-notes、decisions、task-reports。
- docs/environment.md：将 WSL2 日常开发模型改为“Windows 权威工作树 + WSL Linux 构建测试”，固定两侧路径，记录 /mnt/d 取舍。
- docs/development-workflow.md：任务开始在 Windows 检查 Git；测试命令通过 wsl.exe；禁止 WSL Git；验证通过后允许自动 --no-ff 合并。
- docs/testing.md：明确只有 MiniOrangeOS-Dev、真实 Ubuntu 容器和 Linux CI 的构建测试日志可作为 PASS 证据，Windows 原生命令只承担 Git 和静态文件检查。
- docs/provenance.md：新增“Project bootstrap”行，状态写“规范与契约测试已建立，功能代码不适用”。
- docs/problems.md：新增风险“/mnt/d 构建性能和权限语义差异”，定位手段为行尾、可执行位、大小写和增量构建测试，允许措施为 metadata 挂载和严格 .gitattributes，不允许维护第二份工作树。

- [ ] **Step 3: 创建环境决策记录**

docs/decisions/0001-windows-worktree-wsl-tests.md:

~~~markdown
# ADR-0001：Windows 权威工作树与 WSL 测试环境

## 状态

已接受，2026-07-13。

## 背景

原计划要求工作树位于 WSL ext4。用户明确要求代码保留在当前 Windows 项目目录，只在 WSL 中进行 Linux 构建和测试。用户当前指令优先于前置项目文档。

## 决策

- 唯一权威工作树为 D:\DC\program-projects\OTHER\MiniOrangeOS。
- 文件修改和 Git 由 Windows 执行。
- MiniOrangeOS-Dev 通过 /mnt/d 挂载同一工作树，仅执行 Linux 构建、QEMU、GDB 和测试。
- 不在 WSL 中运行 Git，不维护第二份活动工作树。
- 使用 .gitattributes、WSL automount metadata 和契约测试约束行尾、可执行位和文件布局。

## 影响

优点：代码保持在用户指定项目目录，不产生同步分叉；Git 所有权单一。

代价：/mnt/d 的构建性能、大小写和 Linux 权限语义弱于 ext4。后续任务必须持续验证并行构建、增量构建、Shell 可执行位和 LF；若出现无法规避的正确性问题，需要新的 ADR 和用户确认，不能静默迁移工作树。
~~~

- [ ] **Step 4: 创建进度与心得入口**

docs/progress.md:

~~~markdown
# 项目进度

> 只记录有提交和真实测试证据的状态；计划不等于完成。

| 任务 | 状态 | 分支 | 测试证据 | 合并 |
|---|---|---|---|---|
| T00 | 实施中 | feature/T00-project-bootstrap | tests.host.test_project_layout | 待验收 |
| T01–T74 | 未开始 | — | — | — |

## 里程碑

| 里程碑 | 状态 | 验收摘要 |
|---|---|---|
| M0 | 实施中 | T00–T03 |
| M1–M8 | 未开始 | 无 |
~~~

docs/review-notes.md:

~~~markdown
# 开发者审查与心得

本文档在每个里程碑结束时记录实际阅读、理解、问题修正和尚需学习的内容。任务级事实记录在 docs/task-reports，来源记录在 docs/provenance.md。

## M0 进行中

已确认的工程原则：

- Windows 目录是唯一工作树，Windows Git 是唯一 Git。
- WSL 只提供 Linux 构建和测试语义。
- 每个 TXX 独立分支、先测试、同步文档、验收后 no-ff 合并。
- 未运行的测试不能写成 PASS。

当前需要在 M0 结束前掌握：

- WSL 发行版创建、验证、备份和定向删除边界；
- i686-elf 工具链的组成和隔离路径；
- GNU Make 依赖、并行和增量构建行为；
- QEMU 串口、debug-exit、超时和 GDB 回环调试链。
~~~

- [ ] **Step 5: 运行完整契约测试**

Run:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
'
~~~

Expected: 7 tests PASS。

- [ ] **Step 6: 检查文档一致性和旧计划名残留**

Run from PowerShell:

~~~powershell
rg -n -g '!docs/superpowers/**' "MiniOrangeOS_Codex_Project_Plan_v1\.1\.md|工作树.*WSL ext4|禁止.*Windows Git" PROJECT_PLAN.md README.md CONTRIBUTING.md docs environment
~~~

Expected: 没有仍作为当前规则的旧文件名或冲突表述；历史背景和 ADR 中解释旧规则的文字允许存在，但必须明确已被覆盖。

- [ ] **Step 7: 提交文档同步**

Run:

~~~powershell
git add -- PROJECT_PLAN.md docs README.md CONTRIBUTING.md environment/README.md
git diff --cached --check
git commit -m "docs(project): align T00 workflow and records" -m "Synchronize the authoritative plan and topic documents with the approved Windows worktree, WSL test boundary, progress tracking, provenance, risks, and review notes." -m "Refs: T00"
~~~

Expected: 提交成功；文档不宣称 T01 或操作系统功能已经完成。

---

### Task 6: 完成 T00 报告、验证并合并

**Files:**
- Create: docs/task-reports/T00-project-bootstrap.md
- Modify: docs/progress.md

**Interfaces:**
- Consumes: Tasks 1–5 的真实命令输出和提交记录。
- Produces: T00 可审计任务报告、全绿验证、推送分支和 main 的 no-ff 合并提交。

- [ ] **Step 1: 执行最终 Windows 仓库检查**

Run:

~~~powershell
git diff --check
git status --short --branch
git ls-files --eol
$placeholderPatterns = @('T' + 'BD', 'T' + 'ODO', '后续' + '补充', '待' + '定')
rg -n ($placeholderPatterns -join '|') README.md CONTRIBUTING.md PROJECT_PLAN.md docs environment
~~~

Expected: diff check 无输出；所有受控文本的 index 为 LF；占位扫描只允许引用规则或风险模板中的字面词，不允许未完成的 T00 内容。

- [ ] **Step 2: 执行最终 WSL 契约测试**

Run:

~~~powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
set -euo pipefail
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
printf "T00_TEST_RESULT=PASS\n"
'
~~~

Expected: 7 tests PASS，最后输出 T00_TEST_RESULT=PASS。

- [ ] **Step 3: 验证宿主未被项目工具链污染**

Run from PowerShell:

~~~powershell
$forbidden = @('i686-elf-gcc', 'nasm', 'qemu-system-i386', 'gdb')
foreach ($name in $forbidden) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        throw "Windows PATH 中发现禁止的项目工具：$name -> $($command.Source)"
    }
}
wsl.exe --list --verbose
~~~

Expected: Windows PATH 未找到四项项目工具；MiniOrangeOS-Dev 和原有 docker-desktop 均存在。

- [ ] **Step 4: 写入实际任务报告并更新进度**

docs/task-reports/T00-project-bootstrap.md:

~~~markdown
# T00：初始化仓库和工程规范

任务：T00

分支：feature/T00-project-bootstrap

环境：Windows 权威工作树；MiniOrangeOS-Dev Ubuntu 24.04 执行测试

## 实现内容

- 建立计划目录骨架、Git 忽略和文本属性策略。
- 建立 README、贡献规范、编码规范和稳定 PROJECT_PLAN.md 入口。
- 同步 Windows 工作树与 WSL 测试边界。
- 建立进度、ADR、来源、风险和审查心得入口。
- 添加 Python 标准库仓库契约测试。

## 关键设计

- Windows Git 独占权威工作树；WSL 禁止运行 Git。
- /mnt/d 只用于 Linux 构建测试，使用 metadata、LF 契约和静态测试降低差异风险。
- T00 不包含任何操作系统功能代码或项目工具链安装。

## 执行命令

- wsl.exe --import MiniOrangeOS-Dev D:\ApplicationData\MiniOrangeOS\rootfs D:\ApplicationData\MiniOrangeOS\downloads\ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz --version 2
- wsl.exe -d MiniOrangeOS-Dev -- bash -lc 'python3 -m unittest tests.host.test_project_layout -v'
- git diff --check
- git ls-files --eol

## 测试结果

- ProjectLayoutTests：PASS（7 项）。
- Ubuntu 版本：24.04。
- 默认 WSL 用户：minios。
- Windows PATH 项目工具污染检查：PASS。

## 未解决问题

- /mnt/d 的性能和权限语义风险保留，由 T02 增量/并行构建和后续 Shell 可执行位测试持续验证。
- T01 尚未实现可重复创建、备份、工具链安装和定向销毁脚本。

## 文档同步

- PROJECT_PLAN.md、docs/README.md、docs/environment.md、docs/development-workflow.md、docs/testing.md、docs/provenance.md、docs/problems.md 已同步。

## 提交

提交清单以 git log --oneline main..feature/T00-project-bootstrap 的实际输出和最终任务回复为准。
~~~

Update docs/progress.md T00 row to:

~~~markdown
| T00 | 完成 | feature/T00-project-bootstrap | ProjectLayoutTests 7/7 PASS | merge: complete T00 project bootstrap |
~~~

- [ ] **Step 5: 提交任务报告**

Run:

~~~powershell
git add -- docs/task-reports/T00-project-bootstrap.md docs/progress.md
git diff --cached --check
git commit -m "docs(t00): record bootstrap verification" -m "Record the verified WSL bootstrap, project layout tests, host pollution check, remaining risks, and T00 progress state." -m "Refs: T00"
~~~

Expected: 工作区干净；git log main..HEAD 包含设计、计划、测试、骨架、规范、同步和报告提交。

- [ ] **Step 6: 推送任务分支**

Run:

~~~powershell
git push --set-upstream origin feature/T00-project-bootstrap
~~~

Expected: origin/feature/T00-project-bootstrap 指向本地 HEAD。若 SSH 凭据不可用，保留干净本地分支并在任务报告中记录，禁止假称已推送。

- [ ] **Step 7: 以 no-ff 合并到 main 并推送**

Run only after Steps 1–6 all pass:

~~~powershell
git switch main
git pull --ff-only origin main
git merge --no-ff feature/T00-project-bootstrap -m "merge: complete T00 project bootstrap"
git push origin main
~~~

Expected: main 包含一个独立 merge commit；origin/main 与本地 main 一致。

- [ ] **Step 8: 删除已合并分支并验证 main**

Run:

~~~powershell
git branch -d feature/T00-project-bootstrap
git push origin --delete feature/T00-project-bootstrap
git status --short --branch
git log --graph --oneline --decorate -12
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
'
~~~

Expected: main 工作区干净；图中保留 T00 no-ff merge；删除任务分支后 7 项测试仍 PASS。

---

## Plan Self-Review Matrix

| 规格要求 | 覆盖任务 |
|---|---|
| Windows 唯一权威工作树、WSL 只测试 | Tasks 1、4、5、6 |
| D:/ApplicationData/MiniOrangeOS 集中环境 | Task 1 |
| T00 目录骨架和工程规范 | Tasks 2–4 |
| LF、忽略规则和无构建产物 | Tasks 2、3、6 |
| Windows Git、独立分支、no-ff 合并 | Tasks 4、6 |
| 测试优先和真实 PASS | Tasks 2、3、5、6 |
| 文档、来源、风险、进度、任务报告、心得 | Tasks 4–6 |
| 不添加功能代码或工具链 | Global Constraints、Tasks 3–4 |
| 不污染宿主全局配置 | Tasks 1、6 |
| 失败不合并 | Global Constraints、Task 6 |
