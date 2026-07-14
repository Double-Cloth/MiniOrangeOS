# P7 CI、文档和答辩版本阶段报告

阶段：P7 CI、文档和答辩版本

分支：`feature/P7-release-ci-docs`

提交：

- `fb15888`：`build(p7): add release verification workflow`
- `f56de5a`：`docs(p7): calibrate release state`
- `3daa1c1`：`fix(p7): preserve CI failure evidence`
- `dfb58ee`：`docs(p7): record CI failure evidence contract`
- `aa57ad9`：`fix(p7): resolve CI runner temp at step time`
- `e7be5d0`：`fix(p7): support BuildKit bootstrap identity`
- `a36dca1`：`fix(p7): include package state helper in image`
- `60c6697`：`fix(p7): run image toolchain as target user`
- `cf2f06a`：`fix(p7): manifest implicit archive directories`
- `69be0c2`：`fix(p7): trust nonroot container pid facts`
- `72add84`：`docs(p7): complete release evidence`

合并提交：`12cb2c5`：`merge: complete P7 release CI and docs`。

## 修改文件

- `Makefile`、`tools/loc_report.py`：统一 `check/test-host/test/loc/demo-persistence` 公开入口、递归 Make 隔离和来源分类代码量统计
- `.github/workflows/ci.yml`、`environment/ubuntu/ci-run.sh`：固定 Ubuntu runner、action SHA、最小权限、只读源码、完整输出和失败证据上传
- `environment/Containerfile`、`environment/verify.sh`：固定容器构建输入、BuildKit 身份兼容、普通用户工具链构建和真实 OCI runtime 校验
- `environment/ubuntu/run.sh`、`run-inside.sh`：把权威 checkout 只读挂载并复制到短生命周期可写工作副本，保持 argv 边界
- `tools/build_toolchain.sh`：使来源清单覆盖归档省略的隐式父目录，并保持显式目录覆盖与冲突拒绝
- `tests/host/`：聚合递归隔离、release/CI 合同、失败证据、来源清单和非 root PID 1 身份回归
- `docs/`、`PROJECT_PLAN.md`：release checklist、测试、来源、问题、进度、审查心得与最终阶段状态

## 关键实现

- `make test` 先验证正式环境、执行完整镜像构建和 MiniFS fsck，再从清洁的递归 Make/Python 环境运行全量宿主与真实 QEMU 测试；命令行 `BUILD_DIR`、Make 递归状态和故障注入变量不会泄漏进测试私有工作区。
- CI 在 `ubuntu-24.04` 上从固定 digest 的 Ubuntu 基础镜像构建开发环境，只读挂载 checkout，并在容器临时工作副本运行与本地相同的聚合入口。workflow 仅授予 `contents: read`，官方 action 均固定完整提交 SHA。
- `ci-run.sh` 把完整输出、QEMU 实际 argv、残留串口日志、镜像布局和镜像 SHA-256 导出到 runner 临时目录；仅失败时上传并保留 14 天，成功时不产生 artifact。
- Containerfile 区分 BuildKit 构建事实与最终 Docker runtime：构建期 marker 可追踪并在最终层删除，工具链由 `runuser` 以 `minios` 写入，最终镜像保持 `USER minios`。
- 容器验证器要求 PID 1 事实位于真实 `procfs`、所有权与 `/proc/1` 一致、模式安全，并另外要求 root-owned OCI marker 与 overlay/cgroup 事实；因此支持非 root PID 1，但不接受环境变量自证。
- 工具链来源清单确定性合成上游 tar 未显式记录的父目录，继续拒绝路径类型冲突、非目录父路径、hardlink 环和保留 provenance 路径漂移。
- `make demo-persistence` 使用同一临时磁盘镜像完成两次真实启动：第一次由用户命令创建内容，逐轮 fsck 后第二次读取并验证，最终删除临时镜像。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/with-env.sh make BUILD_DIR=.p7-aggregate test
./environment/with-env.sh make BUILD_DIR=.p7-release clean
./environment/with-env.sh make BUILD_DIR=.p7-release -j4 image
./environment/with-env.sh make BUILD_DIR=.p7-release test-image
./environment/with-env.sh make demo-persistence
./environment/with-env.sh make loc
python3 -m unittest tests.host.test_environment_contract tests.host.test_release_contract tests.host.test_toolchain_provenance
```

结果：

- 正式 WSL 环境验证、完整镜像构建和 MiniFS fsck：PASS；
- WSL 聚合宿主/QEMU 回归：243/243 PASS，用时 898.861 秒；
- 独立清洁 `.p7-release` 镜像构建与 `make test-image`：PASS，MiniFS 工具 6/6 PASS；
- 双启动演示分别输出用户命令持久化 created/verified，两轮写入后的宿主 fsck 均 PASS；
- 当前 CI/环境/来源清单相关专项：48/48 PASS；
- `kernel.elf`：145,656 bytes，SHA-256 `2a0749ff4fb27289c79e1a9f75b186b7dcd66ac0b777a0177ad84734aa87873b`；
- `minifs.img`：66,060,288 bytes，SHA-256 `79fe925f71552cf9b4fd47cedd99ef91b08a3bfc1d97ec0d5c301435156ead2b`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `3c55f18a0a4768d98e8d834a9f783c47adf7d77c88d9576d436f4f35bb0001fe`。

原生 Linux 证据：

- GitHub Actions 运行：[29331275773](https://github.com/Double-Cloth/MiniOrangeOS/actions/runs/29331275773)；
- runner：`ubuntu-24.04`；最终分支 HEAD：`72add849f7ff5621e6404b62c232a826f7b5758c`；
- 固定开发镜像构建：PASS，用时 20 分 10 秒；
- 容器环境验证：`environment_kind=container`、`result=PASS`；
- 聚合宿主/QEMU 回归：246/246 PASS，用时 163.166 秒，23 项平台限定测试按设计跳过；
- 完整 job：PASS，用时 23 分 3 秒；失败 artifact 数量为 0。

首次远端运行依次暴露并修复 expression 求值阶段、BuildKit marker、遗漏 helper、构建用户身份、上游隐式目录和非 root PID 1 所有权差异。每次有 job 的失败运行均成功上传独立证据；完整根因和安全边界见 `docs/problems.md`。

## 代码量与来源边界

最终 `make loc` 在本报告与合并记录加入后重新生成：175 个文本文件、40,145 行、36,073 个非空行。统计区分 Boot/Loader、内核、共享 ABI、用户程序/libc、工具与环境脚本、测试、文档、构建配置、自动生成和第三方文件；自动生成与第三方类别均为 0，不计入自主核心代码。

核心 OS、工具、测试与 CI 编排由项目自主实现；第三方边界仅包括固定来源的 Ubuntu、GNU Binutils/GCC、QEMU/GDB/NASM/Python 工具以及两个固定提交的 GitHub 官方 action。详细登记见 `docs/provenance.md`。

## 已知限制

- CI 证明固定 Ubuntu 容器、宿主工具和 QEMU 路径，不等同于真实裸机硬件验收。
- MiniFS 不提供 journal 或任意掉电点的事务原子性；ATA 仅支持 primary master LBA28 PIO。
- Shell 无 cwd syscall，console/keyboard 尚未统一为 VFS file object，普通 fd 不跨 spawn 继承。
- 项目有意不支持 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接和完整 POSIX。
- CI 首次构建固定交叉工具链约需 21 分钟；当前不引入额外缓存 action，以保持来源和权限边界简单可审计。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、架构、测试、来源、问题、进度、release checklist 与审查心得。
- P7 分支已具备本地 WSL、原生 Linux CI、真实 QEMU、失败证据和最终演示闭环，并通过 `12cb2c5` 本地 no-ff 合并进入 `main`。
