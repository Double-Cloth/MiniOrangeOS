# MiniOrangeOS

MiniOrangeOS 是一个从零实现的 x86 32 位 BIOS 教学操作系统。目标包括自写 Stage 1/Stage 2、ELF32 高半内核、分页、Ring 3、抢占式调度、int 0x80 系统调用、用户态 Shell、ATA PIO 和持久化 MiniFS。

## 当前状态

当前处于 M0 工程基础阶段。T01 隔离环境和 `i686-elf` 工具链已完成并合并；T02 最小构建系统已通过验收，能够生成 Boot、Loader、ELF32 Kernel 占位产物和固定 64 MiB 原始镜像，但尚未实现可启动内核。真实状态以 `docs/progress.md` 和任务报告为准。

## 权威工作树

唯一权威工作树：

    D:\DC\program-projects\OTHER\MiniOrangeOS

源码和文档在该目录编辑，Git 只由 Windows Git 操作。禁止在 WSL 中运行 Git 或维护第二份活动工作树。

## 日常 Linux 构建与测试

专用测试发行版：MiniOrangeOS-Dev

WSL 路径：

    /mnt/d/DC/program-projects/OTHER/MiniOrangeOS

日常 Linux 构建、QEMU、GDB 和测试都通过该发行版执行。使用 `environment/with-env.sh` 只为子进程注入项目工具路径，使用 `environment/verify.sh` 验证版本、路径和污染边界。

## 真实 Ubuntu 复验

真实 Ubuntu 24.04 使用 rootless OCI 容器复验，不直接安装项目工具链。以下入口已经真实验收，T01 完成后可用：

    ./environment/ubuntu/create.sh
    ./environment/ubuntu/run.sh make test
    ./environment/ubuntu/destroy.sh --all

## 文档入口

- PROJECT_PLAN.md：任务顺序与完成定义。
- docs/README.md：专题文档索引。
- docs/superpowers/specs/2026-07-13-m0-foundation-design.md：M0 设计规格。
- docs/progress.md：实际进度。
- CONTRIBUTING.md：分支、提交、测试和合并规则。
- docs/task-reports/T01-environment-toolchain.md：T01 的真实安装、备份、容器与清理证据。
- docs/task-reports/T02-minimal-build-system.md：T02 的构建、镜像、安全边界与测试证据。

## 范围限制

最低版本不实现 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接、Swap、完整 POSIX、文件系统日志、权限系统或复杂 Shell。

## License

MIT
