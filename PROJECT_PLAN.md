# MiniOrangeOS 项目实施计划

> 文档版本：2.0
> 更新日期：2026-07-14
> 目标平台：x86 32 位 BIOS Legacy
> 权威工作树：`D:\DC\program-projects\OTHER\MiniOrangeOS`
> Linux 构建与测试：专用 WSL2 发行版 `MiniOrangeOS-Dev`

本文档只保留项目推进所需的约束、阶段和验收标准。历史 T00-T11 已完成并保留在 `docs/task-reports/`；后续不再把每个小步骤拆成独立任务，改为按阶段交付。

## 1. 项目目标

MiniOrangeOS 是一个从零实现的 x86 32 位教学操作系统。最低交付必须证明：

- 自写 Stage 1 Boot Sector 和 Stage 2 Loader；
- Loader 能进入保护模式并加载 ELF32 高半内核；
- 内核支持分页、异常处理、PIT/PIC、键盘、Ring 3、抢占式调度和 `int 0x80`；
- 用户程序以静态 ELF32 运行，并从持久化 MiniFS 加载；
- Shell 能执行基础命令，文件重启后仍可读取；
- 构建、QEMU 测试、来源记录和文档状态可审计。

## 2. 不变约束

- Windows 目录是唯一权威工作树；Git 只在 Windows 侧操作。
- WSL 只负责 Linux 构建、QEMU、GDB 和测试；禁止在 WSL 中运行 Git 或维护第二份活动工作树。
- 禁止在 Windows 安装项目专用 GCC、NASM、Make、QEMU、GDB、MSYS2、Cygwin 或 MinGW。
- 内核和用户态最低实现不得依赖宿主 glibc、Linux ABI、动态链接器或 GRUB。
- 不复制 Orange'S、xv6、Minix 或其他教学 OS 源码；参考资料必须记录到 `docs/provenance.md`。
- 只有真实运行并 PASS 的命令才能写入完成报告。

## 3. 技术基线

| 类别 | 决策 |
|---|---|
| CPU | x86 32 位，i686 目标 |
| 启动 | BIOS Legacy，自写 Stage 1 + Stage 2 |
| 内核格式 | ELF32，高半内核起始 `0xC0000000` |
| 内核语言 | C11 Freestanding + NASM Intel 语法 |
| 构建 | GNU Make、`i686-elf-gcc`、`i686-elf-ld` |
| 模拟与调试 | QEMU、GDB remote |
| 内存 | 4 KiB 页、两级页表、E820、bitmap PMM、first-fit kernel heap |
| 进程 | 独立页目录、TSS、Ring 3、抢占式时间片轮转 |
| 系统调用 | `int 0x80` |
| 存储 | ATA PIO、512 字节扇区、4 KiB 文件系统块 |
| 文件系统 | 自定义 inode MiniFS，直接块 + 一级间接块 |
| 用户程序 | 静态 ELF32，`/bin/init` 启动 `/bin/sh` |

最低版本不做 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接、Swap、完整 POSIX、文件系统日志、权限系统和复杂 Shell。

## 4. 文档使用方式

实施前只需要读三类文档：

1. 本计划：确认当前阶段和验收标准。
2. `docs/development-workflow.md`：确认分支、测试、提交和报告规则。
3. 当前阶段相关专题文档：

| 阶段 | 主要文档 |
|---|---|
| 启动链 | `docs/boot.md`、`docs/architecture.md`、`docs/testing.md` |
| 内核基础 | `docs/architecture.md`、`docs/memory.md`、`docs/testing.md` |
| 内存管理 | `docs/memory.md`、`docs/syscall.md`、`docs/testing.md` |
| 进程与系统调用 | `docs/process.md`、`docs/syscall.md`、`docs/testing.md` |
| 用户态 | `docs/process.md`、`docs/syscall.md`、`docs/filesystem.md` |
| 文件系统 | `docs/filesystem.md`、`docs/syscall.md`、`docs/testing.md` |
| 收尾验收 | `docs/testing.md`、`docs/provenance.md`、`docs/problems.md` |

如果实现需要偏离专题文档，先改对应文档并说明原因，再改代码。

## 5. 当前状态

已完成：

- P0 工程基础：历史 T00-T03 已完成并合并。
- P1 启动链：历史 T10-T11 与阶段分支 `feature/P1-boot-chain` 完成 A20、E820、保护模式、ATA PIO、ELF32 高半内核加载和 Boot Info 交接，真实 QEMU 已到达内核早期入口。

P2 已完成：早期分页、控制台/panic、Ring 0 GDT、IDT/异常、8259 PIC、IRQ 分发、100 Hz PIT 与 PS/2 键盘均已通过真实 QEMU。下一步进入 P3：基于 E820 的 PMM、正式 VMM、内核堆与 usercopy。

## 6. 新实施路线

后续按 P1-P7 推进。每个阶段可以在一个分支完成，也可以在风险过高时拆成少量子分支；默认不要再为每个微步骤单独开任务。

### P1：完成启动链

目标：Stage 2 从实模式进入保护模式，读取内存布局，加载 ELF32 内核并跳转。

范围：

- A20 开启与验证；
- E820 内存探测；
- 临时 GDT 与保护模式切换；
- 保护模式 ATA PIO LBA 读取；
- ELF32 内核加载、段边界校验和入口跳转；
- Boot Info 结构传递给内核。

验收：

- `make image` 生成可启动镜像；
- `make test-qemu` 验证通用 QEMU runner，`make test-boot-qemu` 覆盖启动链成功和关键失败路径；
- 串口日志能证明 Stage 2 已进入保护模式并跳到内核入口；
- `docs/boot.md` 与真实实现一致。

### P2：内核基础与中断

目标：内核具备可靠输出、异常处理和基本硬件中断。

范围：

- 高半入口和早期页表；
- `.bss` 清零、Boot Info 校验、初始化编排；
- COM1、VGA、最小格式化输出、panic；
- GDT、IDT、CPU 异常入口和 trap frame；
- PIC、PIT、PS/2 键盘和控制台输入。

验收：

- CPU 异常不会静默死机，panic 可从串口定位；
- PIT tick 和键盘输入可被 QEMU 测试观察；
- 中断和异常的负面测试纳入 `make test-qemu`。

### P3：内存管理

目标：内核具备正式 PMM、VMM、堆和用户指针安全边界。

范围：

- 基于 E820 的物理页 bitmap；
- 正式两级页表管理；
- 高半内核映射和每进程页目录准备；
- first-fit 内核堆；
- 用户地址空间 API；
- `copy_from_user`、`copy_to_user` 和 page fault 处理。

验收：

- 页分配、释放、映射冲突、用户越界和 double free 有测试；
- page fault 能区分内核错误与用户进程错误；
- `docs/memory.md` 与实现状态一致。

### P4：进程、调度与系统调用

目标：能运行内核线程和 Ring 3 用户进程，支持最小系统调用。

范围：

- PCB、PID、内核栈、运行队列和上下文切换；
- 抢占式时间片调度；
- TSS 和 Ring 3 `iret` 进入路径；
- `int 0x80` 入口、系统调用表和参数校验；
- `yield`、`sleep`、`exit`、`waitpid`、基础进程生命周期。

验收：

- 至少三个进程可被时间片轮转；
- 用户进程非法访问只终止当前进程；
- 系统调用号、用户指针和 fd 负面测试通过。

### P5：ELF 用户态与 Shell

目标：从内核加载静态 ELF32 用户程序，并进入可交互 Shell。

范围：

- 用户态 ELF32 加载器；
- crt0、最小 libc 和 syscall wrapper；
- `/bin/init`、`/bin/sh`；
- 基础命令：`echo`、`ps`、`memtest`、`fault`；
- Shell 命令分词、前台执行、等待退出。

验收：

- `/bin/init` 能拉起 Shell；
- 用户程序能通过系统调用输出、退出和触发受控 fault；
- QEMU 测试能自动执行 Shell 脚本并判断 PASS。

### P6：磁盘与 MiniFS

目标：提供可持久化的文件系统和用户态文件命令。

范围：

- 内核 ATA PIO 驱动；
- block device 层；
- 宿主侧 `mkfs`、镜像装配和只读 `fsck`；
- MiniFS superblock、bitmap、inode、目录、路径解析；
- VFS、file object、fd table；
- `open`、`read`、`write`、`lseek`、`close`、`mkdir`、`unlink`、`readdir`、`stat`；
- 用户命令：`ls`、`cat`、`touch`、`write`、`mkdir`、`rm`。

验收：

- Shell 能创建、读取、删除文件和目录；
- 重启后文件内容仍存在；
- 磁盘满、inode 耗尽、损坏 superblock、bitmap 不一致等负面测试通过。

### P7：CI、文档和答辩版本

目标：把项目整理成可复验、可讲解、可交付的版本。

范围：

- 收敛 `make test`；
- Linux CI；
- 来源记录、风险记录和专题文档校准；
- 演示脚本、代码量统计、最终 release checklist；
- 清理临时实验文件和过期表述。

验收：

- 干净环境完整构建和测试通过；
- `docs/progress.md`、`docs/task-reports/`、`docs/provenance.md` 与真实状态一致；
- 最终演示能从启动到文件持久化闭环运行。

## 7. 阶段执行规则

每个阶段按这个短流程执行：

1. 确认当前分支、工作树和相关专题文档。
2. 建一个阶段分支，例如 `feature/P1-boot-chain`。
3. 先补关键测试，再做最小可验收实现。
4. 在 `MiniOrangeOS-Dev` 运行阶段测试和已有回归。
5. 更新相关专题文档、来源记录、进度和阶段报告。
6. 提交并按需要合并。

报告只写事实：

```text
阶段：
分支：
提交：
修改文件：
关键实现：
执行命令：
测试结果：
未解决问题：
文档同步：
```

不再为每个函数、每个小文件或每个实验步骤写独立长报告。

## 8. 测试底线

阶段内可先跑局部测试，但阶段完成前必须至少运行：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
./environment/verify.sh
make test
'
```

如果 `make test` 暂时还没有覆盖全部阶段内容，报告必须写清楚实际运行的命令、覆盖范围和缺口。

## 9. 最终演示闭环

```text
BIOS
  -> Stage 1
  -> Stage 2
  -> E820 + A20 + GDT + protected mode
  -> ELF32 high-half kernel
  -> IDT/PIC/PIT/keyboard/ATA
  -> paging + heap
  -> process + Ring 3 + syscall
  -> /bin/init
  -> /bin/sh
  -> create/read file
  -> reboot
  -> read persisted file
```

项目完成定义：上述闭环真实运行，核心负面测试通过，文档只描述已实现和已验证的事实。
