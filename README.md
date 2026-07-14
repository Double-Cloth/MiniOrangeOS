# MiniOrangeOS

MiniOrangeOS 是一个从零实现的 x86 32 位 BIOS 教学操作系统。目标包括自写 Stage 1/Stage 2、ELF32 高半内核、分页、Ring 3、抢占式调度、int 0x80 系统调用、用户态 Shell、ATA PIO 和持久化 MiniFS。

## 当前状态

P0 工程基础与 P1 启动链已完成，P2 内核基础与中断正在实施。当前镜像能从自写 Stage 1/Stage 2 经 A20、E820 和保护模式，使用 ATA PIO 加载 ELF32 高半内核；内核已具备早期分页、高半入口、控制台/panic、Ring 0 GDT、IDT、统一 trap frame、8259 PIC 和 100 Hz PIT tick。P2 后续将完成 PS/2 键盘与控制台输入。真实状态以 `docs/progress.md` 和阶段报告为准。

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

- PROJECT_PLAN.md：阶段路线、范围和完成定义。
- docs/README.md：专题文档索引和阶段阅读入口。
- docs/development-workflow.md：分支、测试、报告和提交规则。
- docs/progress.md：实际进度。
- CONTRIBUTING.md：分支、提交、测试和合并规则。
- docs/task-reports/：历史 T00-T11 任务报告和后续阶段报告。

## 范围限制

最低版本不实现 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接、Swap、完整 POSIX、文件系统日志、权限系统或复杂 Shell。

## License

MIT
