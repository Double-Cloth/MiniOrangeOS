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
