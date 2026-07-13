# T00：初始化仓库和工程规范

任务：T00

分支：`feature/T00-project-bootstrap`

验收状态：完成；任务分支已推送，并通过独立 `--no-ff` 合并进入 `main`。

环境：Windows 权威工作树；`MiniOrangeOS-Dev` Ubuntu 24.04 执行 Linux 契约测试。

## 实现内容

- 建立计划目录骨架、Git 忽略规则、MIT License 和文本属性策略。
- 建立 README、贡献规范、编码规范和稳定的 `PROJECT_PLAN.md` 入口。
- 同步 Windows 权威工作树、Windows Git 与 WSL Linux 测试边界。
- 建立进度、ADR、来源、风险和审查心得入口。
- 添加并扩展 Python 标准库仓库契约测试，共 11 项。
- 将 T01 旧环境规则检查收窄到 T01 章节，避免历史或说明性引用导致误报。
- 最终全分支审查新增提交格式与 T01 环境脚本契约，并将文本测试扩展到严格 UTF-8、任意 CR、策略文件和全部 `.gitkeep`。

T00 未添加操作系统功能代码，未安装项目编译、汇编、虚拟化或调试工具链。

## 关键设计与环境边界

- 唯一权威工作树是 `D:\DC\program-projects\OTHER\MiniOrangeOS`，文件编辑和 Git 只由 Windows 执行。
- `MiniOrangeOS-Dev` 通过 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS` 读取同一工作树，只执行 Linux 构建、QEMU、GDB 和测试；WSL 内禁止运行 Git。
- 环境载荷集中在 `D:\ApplicationData\MiniOrangeOS`，没有在仓库中保存 rootfs、工具链或环境状态。
- `/mnt/d` 使用 metadata 挂载；`.gitattributes` 和仓库契约测试共同约束 LF 与跨环境文本一致性。
- 用户既有外部工具不视为项目自有工具链；验收只拒绝来自权威工作树或 `D:\ApplicationData\MiniOrangeOS` 的工具和 PATH 项，并禁止擅自修改用户环境。

## WSL 引导与来源校验

- 发行版：`MiniOrangeOS-Dev`，WSL 2，Ubuntu 24.04 LTS。
- 默认用户：`minios`。
- 原有 `docker-desktop` 仍存在且为 WSL 2；T00 未修改或删除它。
- rootfs：`ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz`。
- 来源：Ubuntu 官方 noble WSL 发布目录及同目录 `SHA256SUMS`。
- 期望与实际 SHA-256 均为 `2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934`，校验通过。

## 执行与验证

主要命令：

```powershell
git diff --check
git status --short --branch
git ls-files --eol
wsl.exe -d MiniOrangeOS-Dev -- bash -lc 'python3 -m unittest tests.host.test_project_layout -v'
wsl.exe --list --verbose
```

真实结果：

- `git diff --check`：无输出。
- 所有受控文本的 index 和工作树行尾均为 LF。
- T00 占位词扫描：0 个命中。
- `ProjectLayoutTests`：11/11 PASS，最终标记 `T00_TEST_RESULT=PASS`。
- WSL 环境：Ubuntu 24.04 LTS，默认用户 `minios`；`MiniOrangeOS-Dev` 与 `docker-desktop` 均为 WSL 2。
- Windows 命令解析：`i686-elf-gcc`、`nasm`、`qemu-system-i386` 未找到；预存外部 `gdb` 位于 `D:\ProgramFiles\GreenSoftware\development-tools\mingw64\bin\gdb.exe`。
- 项目自有 PATH 污染检查：PASS；User/Machine PATH 均不包含权威工作树或 `D:\ApplicationData\MiniOrangeOS`，未修改用户环境。

## 提交清单摘要

分支相对 `main` 包含以下可审计提交链：

- `3e3325b`：记录 M0 foundation design。
- `74ee4e1`、`3acfd92`：建立 T00 执行计划并修正 RED 阶段预期。
- `72db53d`：定义仓库布局契约测试。
- `52ce96c`：建立目录骨架、仓库策略、License 与稳定计划入口。
- `e633a7b`、`64ae3fa`：建立并修正工程规范与真实 Ubuntu 指引。
- `0a7b447`、`ebbeb0f`：同步权威文档、记录入口与 T01 环境边界。
- `f58447e`：将旧 T01 规则检查收窄到 T01 章节。
- `6bd73b4`：记录最终预合并验证、进度与实施计划校正。
- `4781d0f`：统一提交格式和 T01 环境脚本契约，并扩展 UTF-8/LF 测试覆盖。
- `f579299`：同步最终 11/11 契约测试计数。
- `def1657`：`merge: complete T00 project bootstrap`，以 `--no-ff` 合并到 `main`。

## 剩余风险与后续范围

- `/mnt/d` 的构建性能、大小写和 Linux 权限语义风险保留，由 T02 的并行/增量构建及后续 Shell 可执行位测试持续验证。
- T01 尚未实现可重复环境创建、备份、工具链安装、真实 Ubuntu 容器复验和定向销毁脚本。
- 用户 PATH 中存在项目目录之外的预存 `gdb`；本任务未安装、删除或重新配置该工具。后续验收继续按来源区分项目自有工具与用户既有工具。

## 文档同步

`PROJECT_PLAN.md`、`docs/README.md`、`docs/environment.md`、`docs/development-workflow.md`、`docs/testing.md`、`docs/provenance.md`、`docs/problems.md`、`docs/progress.md` 和 T00 实施计划已同步。

## 推送与合并状态

- `feature/T00-project-bootstrap` 已推送至 `origin`，分支头为 `f579299a20f884b92b5a9eae4d563bffe52c0f06`。
- 最终全分支审查结论为 `Approved for no-ff merge`。
- `main` 已创建合并提交 `def165725ed9f670abadc2cd7ae80cbc7150dcc9`，提交主题为 `merge: complete T00 project bootstrap`。
- 合并结果已在 WSL 中重新运行 `ProjectLayoutTests`，11/11 PASS；`origin/main` 已包含该合并提交。
