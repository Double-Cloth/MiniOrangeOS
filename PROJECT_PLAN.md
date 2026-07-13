# MiniOrangeOS 从零实现项目计划书

> 文档版本：1.4
> 制定日期：2026-07-13  
> 目标平台：x86 32 位  
> Linux 构建与测试环境：独立 WSL2 Ubuntu 24.04 发行版 `MiniOrangeOS-Dev`
> 容器复验环境：Ubuntu 24.04 rootless OCI；按用户当前要求，T01 在独立 WSL2 测试发行版执行，原生 Linux 内核差异由后续 CI 复验
> Windows 角色：承载唯一权威工作树、文件编辑、Windows Git 和 WSL2 入口；不安装任何原生编译、调试或虚拟化工具链
> 环境目标：全部项目依赖集中、可追踪、可整体删除，不修改 Windows PATH，不向真实 Ubuntu 的 `/usr/local` 写入项目工具链  
> 最终产物：可由 BIOS 启动、运行 Ring 3 用户程序、支持分页、抢占式调度和持久化文件系统的 32 位教学操作系统

---

## 0. 修订记录

| 版本 | 日期 | 主要变更 |
|---|---|---|
| 1.0 | 2026-07-13 | 初始单人开发计划 |
| 1.1 | 2026-07-13 | 改为专用 WSL2 日常开发；Windows 不安装原生工具链；真实 Ubuntu 使用项目容器复验；新增环境创建、验证、备份和定向删除规范 |
| 1.2 | 2026-07-13 | 补充前置项目文档闭环；将架构、环境、启动、内存、进程、系统调用、文件系统、测试、来源和问题记录拆分到 `docs/`；明确 T73 后期职责从“新建文档”调整为“按真实代码校准文档” |
| 1.3 | 2026-07-13 | 按用户明确要求改为 Windows 项目目录作为唯一权威工作树；Windows Git 负责版本控制；MiniOrangeOS-Dev 只执行 Linux 构建、QEMU、GDB 和测试；环境载荷集中到 D:\ApplicationData\MiniOrangeOS |
| 1.4 | 2026-07-13 | 按用户“仅在 WSL 中测试”的当前指令，将 T01 rootless OCI 集成验收放到独立 Ubuntu 24.04 WSL2 测试发行版；原生 Linux 内核差异由后续 CI 复验并通过 ADR 跟踪 |

---

## 1. 文档用途

本计划书不是概念性路线图，而是 Codex 可逐项执行的工程任务书。执行时必须遵循以下规则：

1. 不跳过任务依赖，不以“后续再补”代替当前任务的完成定义。
2. 每个任务必须在独立分支中完成，至少包含一次有效提交。
3. Codex 可以执行命令、创建和修改文件、重构目录、提交 Git，但不得绕过测试或直接修改 `main`。
4. 唯一权威工作树位于 `D:\DC\program-projects\OTHER\MiniOrangeOS`，由 Windows 侧 Codex 编辑并使用 Windows Git。`MiniOrangeOS-Dev` 通过 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS` 访问同一工作树，只执行 Linux 构建、QEMU、GDB 和测试，不运行 Git。不创建第二份活动工作树；`.gitattributes` 强制跨环境文本格式。
5. Windows 主机禁止安装项目专用的原生 GCC、NASM、Make、QEMU、GDB、MSYS2、Cygwin 或 MinGW，禁止修改 Windows PATH、注册表、文件关联和系统服务。WSL2 功能及专用发行版注册是不可避免的宿主变化，但项目载荷必须集中在一个可指定、可整体删除的目录中。
6. 当某项命令在 Windows 侧无法直接运行时，Codex 必须通过 `wsl.exe -d MiniOrangeOS-Dev -- bash -lc ...` 在专用 WSL 中执行，不得建立 Windows 专用构建链，也不得以 Windows 无法运行作为跳过测试的理由。
7. 每个任务结束时必须报告：
   - 修改文件；
   - 关键设计；
   - 执行命令；
   - 测试结果；
   - 未解决问题；
   - Git 提交哈希。
8. 任何来自参考代码、书籍或网络的实现都必须记录来源；禁止整段复制参考操作系统代码后宣称从零实现。
9. Codex 生成的代码必须由开发者阅读、解释和验收。答辩时必须能够说明每个核心模块的设计和控制流。

### 1.1 前置项目文档闭环

本计划书 v1.2 已将路线图中的关键实现约束拆分为 `docs/` 下的前置设计文档。后续代码任务必须把这些文档作为输入，而不是等到项目末尾再补写文档。

| 文档 | 作用 | 主要覆盖任务 |
|---|---|---|
| `docs/README.md` | 文档索引、阅读顺序、维护规则 | 全部任务 |
| `docs/environment.md` | WSL、真实 Ubuntu 容器、工具链隔离、清理验收 | T00-T01、T72、T74 |
| `docs/development-workflow.md` | 分支、提交、报告、文档同步点 | 全部任务 |
| `docs/architecture.md` | 总体分层、目录职责、初始化顺序、错误模型 | T00-T74 |
| `docs/boot.md` | Stage 1、Stage 2、A20、E820、保护模式、内核 ELF 加载 | T10-T15 |
| `docs/memory.md` | PMM、VMM、高半映射、内核堆、用户地址空间、usercopy | T20、T30-T34 |
| `docs/process.md` | PCB、调度、Ring 3、TSS、ELF 用户程序、Shell | T40-T53 |
| `docs/syscall.md` | `int 0x80` ABI、系统调用表、用户指针安全、fd 语义 | T43-T44、T66-T67 |
| `docs/filesystem.md` | ATA、块设备、MiniFS、VFS、mkfs、fsck | T60-T68 |
| `docs/testing.md` | 测试层级、串口协议、负面测试、CI 要求 | T03、T70-T72 |
| `docs/provenance.md` | 来源登记、自主实现证明、审查记录 | 全部实现任务 |
| `docs/problems.md` | 风险、降级、问题和环境清理演练记录 | 全部任务 |

闭环规则：

1. 计划书定义任务顺序和完成定义，`docs/` 定义实现契约和验收细节。
2. 代码实现若需要偏离 `docs/`，必须先修改对应文档并说明原因。
3. T73 不再从零创建文档，而是在核心功能稳定后按真实代码、真实函数和真实测试结果校准全部文档。
4. 答辩前必须消除文档中“前置设计”“待实现”与实际状态不一致的表述。

---

## 2. 课程目标与 A 类难度映射

课程 A 类项目要求独立完成一个简单操作系统，覆盖引导程序、核心代码、文件系统、控制台等部分，并保证项目组完成至少一半代码。本项目采用从零实现策略，核心代码不建立在 Orange’S、xv6、Minix 或其他教学操作系统源码之上。

| A 类要求 | 本项目对应实现 |
|---|---|
| 引导程序 | 自写 512 字节 Boot Sector 和二级 Loader |
| 核心代码 | 自写保护模式内核、中断、内存管理、调度和系统调用 |
| 控制台 | VGA 文本控制台、串口日志、PS/2 键盘和用户态 Shell |
| 文件系统 | 自定义 inode 文件系统、目录、文件读写、删除和重启持久化 |
| 自主代码量 | 不复制参考内核源码；维护来源登记、提交历史和代码量统计 |
| 难度与工作量 | Ring 3、分页、独立地址空间、ELF 用户程序加载和抢占式调度 |
| 文档及源码 | 架构、启动、分页、进程、系统调用、文件系统、测试和问题记录 |
| 答辩 | 一键构建、启动、异常隔离、并发调度、用户程序和文件持久化演示 |

### 2.1 最终演示闭环

```text
BIOS
  ↓
自写 Boot Sector
  ↓
自写二级 Loader
  ↓
读取 E820 内存布局
  ↓
开启 A20、建立 GDT、进入 32 位保护模式
  ↓
从磁盘加载 ELF32 内核
  ↓
建立分页并进入高半内核
  ↓
初始化 IDT、PIC、PIT、键盘、ATA
  ↓
创建进程和独立地址空间
  ↓
切换到 Ring 3
  ↓
从文件系统加载 /bin/init 和 /bin/sh
  ↓
用户程序通过 int 0x80 调用内核
  ↓
Shell 创建并读取文件
  ↓
重启后文件仍然存在
```

---

## 3. 已确定的技术决策

### 3.1 平台和启动

| 项目 | 决策 |
|---|---|
| CPU 架构 | x86 32 位，i686 目标 |
| 启动固件 | BIOS Legacy |
| 引导方式 | 自写 Boot Sector + 二级 Loader |
| 内核格式 | ELF32 |
| 用户程序格式 | 静态链接 ELF32 |
| 模拟器 | QEMU 为主 |
| 调试器 | GDB 远程调试 |
| 实机启动 | 非最低交付要求，作为扩展验证 |
| Bochs | 非最低要求，可用于交叉验证 |

选择 BIOS 和自写 Loader 的原因：它能够直接覆盖 A 类对“引导程序”的要求，且比使用 GRUB 更容易证明启动链路由项目自主完成。

### 3.2 编程语言和工具链

| 项目 | 决策 |
|---|---|
| 内核语言 | C11 Freestanding |
| 汇编 | NASM，Intel 语法 |
| 交叉编译器 | `i686-elf-gcc` |
| 链接器 | `i686-elf-ld` |
| 二进制工具 | `i686-elf-objcopy`、`readelf`、`nm` |
| 构建系统 | GNU Make |
| 辅助脚本 | Bash + Python 3 |
| 格式化 | `clang-format` |
| 静态检查 | 编译器警告；可选 `clang-tidy` 的宿主侧检查 |
| 版本控制 | Windows Git，仅操作 Windows 权威工作树；WSL 不运行 Git |
| WSL 发行版 | 独立 `MiniOrangeOS-Dev`，项目结束后整体注销 |
| WSL 项目工具根目录 | `${XDG_DATA_HOME:-$HOME/.local/share}/miniorangeos-dev` |
| 真实 Ubuntu 隔离方式 | rootless Podman 优先；已有 Docker 可作为兼容后端 |
| Python 依赖 | 隔离环境内的项目专用 venv，不使用 `sudo pip` |
| CI | Linux 容器环境自动构建和 QEMU 无界面测试 |

所有内核 C 文件默认使用：

```text
-std=c11
-ffreestanding
-fno-builtin
-fno-stack-protector
-fno-pic
-fno-pie
-m32
-mno-mmx
-mno-sse
-mno-sse2
-Wall
-Wextra
-Wpedantic
-Wshadow
-Wconversion
-Wmissing-prototypes
-Wstrict-prototypes
```

链接阶段不得依赖宿主系统的 glibc、动态链接器或 Linux ABI。

### 3.3 内核架构

| 子系统 | 决策 |
|---|---|
| 内核地址布局 | 高半内核，起始虚拟地址 `0xC0000000` |
| 页大小 | 4 KiB |
| 页表 | x86 两级页表 |
| 物理内存管理 | Bitmap 页分配器 |
| 内核堆 | 可合并空闲链表的 first-fit 分配器 |
| 用户地址空间 | 每进程独立页目录，内核高半映射共享 |
| 缺页处理 | 非法访问终止用户进程；支持受控的懒分配 |
| 页面置换 | 不实现 |
| Swap | 不实现 |
| 写时复制 | 不作为最低目标 |
| 中断控制器 | 8259A PIC |
| 定时器 | PIT |
| 系统调用 | `int 0x80` |
| 用户态切换 | TSS + Ring 3 段描述符 + `iret` |
| 调度 | 抢占式时间片轮转 |
| 进程生命周期 | create/spawn、exec、exit、wait、sleep、yield |
| `fork` | 扩展目标，不属于最低交付 |
| IPC | 最低实现等待队列；管道作为扩展目标 |

### 3.4 设备和文件系统

| 子系统 | 决策 |
|---|---|
| 主控制台 | VGA 80×25 文本模式 |
| 调试日志 | COM1 串口 |
| 输入 | PS/2 键盘 |
| 磁盘 | ATA PIO，QEMU IDE 设备 |
| 块大小 | 512 字节扇区；文件系统逻辑块为 4096 字节 |
| 文件系统 | 自定义类 Unix inode 文件系统 |
| 目录 | 支持根目录和多级目录 |
| 文件块索引 | 直接块 + 一级间接块 |
| 持久化 | 必须支持重启后数据保留 |
| 一致性 | 基础挂载校验和宿主侧 `fsck` 工具 |
| 日志文件系统 | 不作为最低目标 |
| 权限、链接 | 不作为最低目标 |
| 缓存 | 基础块缓存作为增强目标 |

---

## 4. 明确不做的内容

以下功能不属于最低交付，Codex 不得擅自扩大范围：

- x86_64；
- UEFI；
- SMP 和多核调度；
- APIC；
- 网络协议栈；
- USB；
- 图形桌面和窗口系统；
- 声卡、鼠标；
- 动态链接；
- ELF 共享库；
- 页面置换和磁盘 Swap；
- 完整 POSIX 兼容；
- 用户、组和权限系统；
- 文件系统日志；
- 硬链接和软链接；
- 信号机制；
- 复杂管道和 Shell 脚本语言。

只有在全部最低验收项通过后，才允许从扩展目标中选择功能。

---

## 5. 总体架构

```text
+-------------------------------------------------------------+
|                       用户态 Ring 3                         |
|  /bin/init   /bin/sh   /bin/echo   /bin/ls   /bin/cat      |
|  user libc / syscall wrappers / crt0                        |
+-------------------------- int 0x80 --------------------------+
|                       内核态 Ring 0                         |
|  syscall | process | scheduler | ELF loader | VFS | FS      |
|  paging  | PMM     | heap      | interrupt  | timer         |
|  console | serial  | keyboard  | ATA PIO    | block layer   |
+-------------------------------------------------------------+
|                Boot Sector + Stage 2 Loader                  |
|  BIOS disk | A20 | E820 | GDT | protected mode | ELF load   |
+-------------------------------------------------------------+
|                          QEMU x86                            |
+-------------------------------------------------------------+
```

### 5.1 启动阶段职责

#### Stage 1：Boot Sector

- 被 BIOS 加载到 `0x7C00`；
- 初始化必要段寄存器和栈；
- 保存 BIOS 启动盘号；
- 使用 INT 13h 扩展读取二级 Loader；
- 校验读取结果；
- 跳转到 Loader；
- 保持在 512 字节以内并包含 `0xAA55` 签名。

#### Stage 2：Loader

- 输出可识别的启动日志；
- 开启 A20；
- 使用 BIOS E820 获取内存映射；
- 建立临时 GDT；
- 进入 32 位保护模式；
- 使用 ATA PIO 或保护模式磁盘读取加载内核；
- 解析 ELF32 Program Header；
- 将各段加载到指定物理地址；
- 建立最小临时页表；
- 传递 Boot Info；
- 跳转到内核入口。

### 5.2 内核启动阶段

1. 汇编入口建立内核栈；
2. 清零 `.bss`；
3. 接收并校验 Boot Info；
4. 初始化串口和 VGA；
5. 初始化 GDT/TSS；
6. 初始化 IDT 和异常处理；
7. 根据 E820 初始化物理页分配器；
8. 建立正式高半页表；
9. 初始化内核堆；
10. 初始化 PIC、PIT 和键盘；
11. 初始化 ATA 和块设备层；
12. 挂载文件系统；
13. 初始化进程和调度器；
14. 从文件系统加载 `/bin/init`；
15. 开启中断；
16. 进入调度循环。

---

## 6. 内存布局

### 6.1 物理内存建议布局

| 物理地址范围 | 用途 |
|---|---|
| `0x00000000–0x000003FF` | 实模式中断向量表 |
| `0x00000400–0x000004FF` | BIOS 数据区 |
| `0x00007C00–0x00007DFF` | Boot Sector |
| `0x00008000–0x0000FFFF` | 二级 Loader |
| `0x00010000–0x0009EFFF` | Loader 缓冲区、E820、临时数据 |
| `0x000A0000–0x000FFFFF` | 保留和设备映射区域 |
| `0x00100000` 起 | 内核物理镜像 |
| 内核之后 | 初始页目录、页表、元数据 |
| 其余可用内存 | Bitmap 管理的物理页 |

实际可用范围必须以 E820 结果为准，禁止假定固定内存大小。

### 6.2 虚拟地址空间

```text
0x00000000 +------------------------------+
           | 用户程序代码、数据、堆       |
           |                              |
           | 用户映射                     |
           |                              |
0xBFF00000 | 用户栈和保护页               |
0xC0000000 +------------------------------+
           | 高半内核映射                 |
           | 内核代码、数据、堆           |
           | 设备和临时映射               |
0xFFC00000 | 递归页表映射                 |
0xFFFFFFFF +------------------------------+
```

规则：

- 用户页必须设置 `U/S=1`；
- 内核页必须设置 `U/S=0`；
- 用户态不得映射内核物理页；
- 系统调用必须校验用户指针范围、跨页情况和页权限；
- 每个进程拥有独立页目录；
- 内核高半区域的页表项在进程之间共享；
- 用户栈下方至少保留一个不可访问保护页；
- 销毁进程时必须释放用户页表和物理页，不释放共享内核映射。

---

## 7. 进程和用户态模型

### 7.1 进程控制块

PCB 至少包含：

```c
struct process {
    int pid;
    enum process_state state;
    char name[32];

    struct cpu_context context;
    uintptr_t kernel_stack_top;
    uintptr_t user_stack_top;

    uint32_t *page_directory;
    int exit_code;
    int parent_pid;

    uint64_t wake_tick;
    unsigned time_slice;

    struct file *fd_table[MAX_FDS];
    struct list_node run_node;
    struct list_node wait_node;
};
```

### 7.2 进程状态

```text
NEW → READY → RUNNING
              ↓   ↑
           BLOCKED
              ↓
            READY

RUNNING → ZOMBIE → REAPED
```

最低支持：

- 内核线程；
- Ring 3 用户进程；
- 抢占式调度；
- `yield`；
- `sleep`；
- `exit`；
- `waitpid`；
- 用户进程异常退出；
- 父子关系；
- 僵尸回收。

### 7.3 不实现 `fork` 的理由

本项目的主要目标是 Ring 3、分页隔离和 ELF 加载。最低版本采用 `spawn(path, argv)` 创建新进程，避免在时间受限时引入写时复制或完整地址空间复制。`fork` 仅作为全部最低目标完成后的扩展任务。

---

## 8. 系统调用设计

采用 `int 0x80`，系统调用号放入 `EAX`，参数依次放入 `EBX`、`ECX`、`EDX`、`ESI`、`EDI`，返回值放入 `EAX`。

最低系统调用集合：

| 编号 | 名称 | 功能 |
|---:|---|---|
| 0 | `SYS_exit` | 结束当前进程 |
| 1 | `SYS_write` | 写控制台或文件 |
| 2 | `SYS_read` | 读键盘或文件 |
| 3 | `SYS_open` | 打开文件 |
| 4 | `SYS_close` | 关闭文件 |
| 5 | `SYS_lseek` | 修改文件偏移 |
| 6 | `SYS_create` | 创建文件 |
| 7 | `SYS_unlink` | 删除文件 |
| 8 | `SYS_mkdir` | 创建目录 |
| 9 | `SYS_readdir` | 读取目录项 |
| 10 | `SYS_spawn` | 从 ELF 文件创建进程 |
| 11 | `SYS_waitpid` | 等待子进程 |
| 12 | `SYS_getpid` | 获取 PID |
| 13 | `SYS_yield` | 主动让出 CPU |
| 14 | `SYS_sleep` | 按 tick 睡眠 |
| 15 | `SYS_sbrk` | 调整用户堆 |
| 16 | `SYS_stat` | 获取文件信息 |
| 17 | `SYS_getticks` | 获取系统 tick |

安全要求：

- 校验系统调用号；
- 校验用户指针位于用户空间；
- 校验指针覆盖的每一页已映射；
- 根据方向校验页的可读或可写权限；
- 字符串必须限制最大长度；
- 内核不得直接信任用户给出的长度、文件描述符和路径；
- 错误使用负数错误码返回；
- 用户进程的非法指针只能终止当前进程，不能导致内核崩溃。

---

## 9. ELF 用户程序加载

### 9.1 支持范围

只支持：

- ELF32；
- Little-endian；
- `EM_386`；
- 静态链接；
- `ET_EXEC`；
- `PT_LOAD` 段；
- 无动态链接器；
- 无共享库；
- 固定用户虚拟地址；
- 独立用户栈；
- `argc/argv`。

加载流程：

1. 通过 VFS 打开 ELF；
2. 读取并验证 ELF Header；
3. 验证目标架构和 Program Header；
4. 创建新页目录；
5. 为每个 `PT_LOAD` 段分配页；
6. 从文件复制 `filesz` 字节；
7. 对 `memsz - filesz` 区域清零；
8. 根据 ELF 权限设置页表位；
9. 分配用户栈和保护页；
10. 在用户栈构造 `argc/argv`；
11. 创建内核栈和初始中断帧；
12. 通过 `iret` 进入 ELF Entry。

必须拒绝：

- ELF 魔数错误；
- 不是 32 位；
- 不是 i386；
- Program Header 越界；
- 段地址溢出；
- 段覆盖内核空间；
- `filesz > memsz`；
- 文件长度不足；
- 段互相非法重叠。

---

## 10. 文件系统设计

### 10.1 磁盘镜像布局

```text
+------------------------------+ LBA 0
| Boot Sector                  |
+------------------------------+
| Stage 2 Loader               |
+------------------------------+
| Kernel ELF                   |
+------------------------------+
| 保留区域 / 对齐              |
+------------------------------+
| File System Superblock       |
+------------------------------+
| Block Bitmap                 |
+------------------------------+
| Inode Bitmap                 |
+------------------------------+
| Inode Table                  |
+------------------------------+
| Data Blocks                  |
+------------------------------+
```

Boot、Loader、Kernel 和文件系统分区的位置必须由统一的镜像布局配置生成，禁止在多个源文件中重复硬编码不同 LBA。

### 10.2 Superblock

至少包含：

```c
struct fs_superblock {
    uint32_t magic;
    uint32_t version;
    uint32_t block_size;
    uint32_t total_blocks;
    uint32_t total_inodes;

    uint32_t block_bitmap_start;
    uint32_t block_bitmap_blocks;
    uint32_t inode_bitmap_start;
    uint32_t inode_bitmap_blocks;
    uint32_t inode_table_start;
    uint32_t inode_table_blocks;
    uint32_t data_start;

    uint32_t root_inode;
    uint32_t checksum;
};
```

### 10.3 Inode

最低字段：

```c
struct fs_inode {
    uint16_t mode;
    uint16_t link_count;
    uint32_t size;
    uint32_t direct[10];
    uint32_t indirect;
    uint32_t created_tick;
    uint32_t modified_tick;
};
```

### 10.4 目录项

```c
struct fs_dirent {
    uint32_t inode;
    uint8_t type;
    char name[59];
};
```

目录必须包含 `.` 和 `..`。路径解析必须支持：

- `/`；
- 绝对路径；
- 多级目录；
- 重复 `/`；
- `.`；
- `..`；
- 不存在的中间目录；
- 文件名长度上限；
- 禁止越过根目录。

### 10.5 最低文件系统能力

必须完成：

- 宿主侧 `mkfs`；
- 内核挂载；
- Superblock 校验；
- inode 和数据块分配；
- 创建文件；
- 打开、关闭；
- 顺序读写；
- 随机偏移读写；
- 文件扩容；
- 文件截断；
- 删除文件；
- 空目录创建和删除；
- 多级目录；
- `readdir`；
- 空间回收；
- 重启持久化；
- 宿主侧只读 `fsck`；
- 对损坏元数据返回错误而不是越界访问。

增强目标：

- 块缓存；
- 延迟写回；
- 管道抽象；
- 文件追加原子性；
- 简单崩溃标记；
- 文件系统统计命令。

---

## 11. 用户态程序

最低用户程序：

| 程序 | 功能 |
|---|---|
| `/bin/init` | 启动首个用户进程并拉起 Shell |
| `/bin/sh` | 用户态命令解释器 |
| `/bin/echo` | 输出参数 |
| `/bin/ls` | 列出目录 |
| `/bin/cat` | 输出文件 |
| `/bin/touch` | 创建文件 |
| `/bin/write` | 写入或覆盖文件 |
| `/bin/mkdir` | 创建目录 |
| `/bin/rm` | 删除文件 |
| `/bin/ps` | 显示进程 |
| `/bin/memtest` | 验证用户空间隔离 |
| `/bin/fault` | 主动触发非法访问，验证异常隔离 |

Shell 最低支持：

- 命令行输入；
- 退格和回车；
- 空白分词；
- `argc/argv`；
- 可执行文件路径查找；
- 子进程创建；
- 等待前台进程；
- 未知命令错误；
- 最长命令限制；
- `help`、`clear`、`cd`、`pwd` 作为内建命令。

管道、重定向、后台任务不是最低要求。

---

## 12. 仓库目录

```text
MiniOrangeOS/
├── .github/
│   └── workflows/
│       └── ci.yml
├── boot/
│   ├── stage1/
│   │   └── boot.asm
│   ├── stage2/
│   │   ├── entry.asm
│   │   ├── bios.asm
│   │   ├── e820.asm
│   │   ├── disk.asm
│   │   ├── elf.c
│   │   └── loader.c
│   └── include/
├── kernel/
│   ├── arch/x86/
│   │   ├── entry.asm
│   │   ├── gdt.c
│   │   ├── tss.c
│   │   ├── idt.c
│   │   ├── isr.asm
│   │   ├── context.asm
│   │   ├── paging.c
│   │   └── syscall.asm
│   ├── core/
│   │   ├── kernel.c
│   │   ├── panic.c
│   │   ├── log.c
│   │   └── list.c
│   ├── mm/
│   │   ├── pmm.c
│   │   ├── vmm.c
│   │   ├── heap.c
│   │   └── usercopy.c
│   ├── proc/
│   │   ├── process.c
│   │   ├── scheduler.c
│   │   ├── wait.c
│   │   └── elf_loader.c
│   ├── syscall/
│   │   ├── dispatch.c
│   │   └── handlers.c
│   ├── drivers/
│   │   ├── serial.c
│   │   ├── vga.c
│   │   ├── pic.c
│   │   ├── pit.c
│   │   ├── keyboard.c
│   │   └── ata.c
│   ├── block/
│   │   └── block.c
│   ├── fs/
│   │   ├── vfs.c
│   │   ├── minifs.c
│   │   ├── inode.c
│   │   ├── bitmap.c
│   │   ├── directory.c
│   │   ├── file.c
│   │   └── path.c
│   └── include/
├── user/
│   ├── crt0.asm
│   ├── libc/
│   ├── linker.ld
│   └── programs/
├── environment/
│   ├── versions.env                 # 固定工具版本、下载地址和校验值
│   ├── packages-ubuntu24.04.txt     # 隔离环境内的 apt 包清单
│   ├── Containerfile               # 真实 Ubuntu/CI 共用开发镜像
│   ├── with-env.sh                 # 临时注入 PATH，不修改 Shell 配置
│   ├── bootstrap-inside.sh         # 在隔离 Linux 环境内安装依赖
│   ├── verify.sh                   # 输出环境指纹并检查宿主污染约束
│   ├── wsl/
│   │   ├── create.ps1              # 导入专用 WSL 发行版
│   │   ├── enter.ps1               # 进入发行版或执行单条命令
│   │   ├── backup.ps1              # 导出可选备份
│   │   └── destroy.ps1             # 注销发行版并删除集中目录
│   └── ubuntu/
│       ├── create.sh               # 构建 rootless OCI 开发镜像
│       ├── run.sh                  # 在容器中执行构建、QEMU 和 GDB
│       ├── shell.sh                # 进入交互式容器
│       └── destroy.sh              # 删除容器、镜像、卷和项目缓存
├── tools/
│   ├── build_toolchain.sh
│   ├── make_image.py
│   ├── mkfs.py
│   ├── fsck.py
│   ├── run_qemu.sh
│   ├── qemu_test.py
│   └── loc_report.py
├── tests/
│   ├── host/
│   ├── qemu/
│   └── fixtures/
├── docs/
│   ├── architecture.md
│   ├── boot.md
│   ├── memory.md
│   ├── process.md
│   ├── syscall.md
│   ├── filesystem.md
│   ├── testing.md
│   ├── problems.md
│   ├── provenance.md
│   └── defense.md
├── Makefile
├── linker.ld
├── README.md
├── PROJECT_PLAN.md
├── CONTRIBUTING.md
├── LICENSE
└── .gitattributes
```

---

## 13. 构建目标

顶层 `Makefile` 必须提供：

```bash
make all          # 编译 Boot、Loader、Kernel 和用户程序
make image        # 生成完整磁盘镜像
make run          # 默认终端/串口方式启动 QEMU，不依赖宿主图形环境
make run-serial   # 串口输出到当前终端
make run-curses   # 终端内显示 VGA 文本并接收 PS/2 键盘输入
make debug        # QEMU -S -s，等待 GDB
make gdb          # 连接同一隔离环境中的 QEMU 并加载符号
make env-check    # 验证工具版本、路径和环境隔离约束
make test-host    # 宿主侧单元测试
make test-qemu    # QEMU 无界面集成测试
make test         # 全部测试
make format       # 格式化源码
make check        # 编译警告、格式和静态检查
make loc          # 生成自主代码量报告
make clean
make distclean
```

构建必须具备以下特性：

- 从干净仓库可复现；
- 自动创建 `build/`；
- 不在源码目录生成 `.o`；
- 依赖关系正确；
- 并行构建安全；
- 失败时返回非零状态；
- 不吞掉编译器错误；
- `build/` 和磁盘镜像不提交 Git；
- 用户程序自动写入文件系统镜像；
- 镜像布局由单一配置产生；
- 可通过环境变量覆盖 QEMU 和交叉编译器前缀；
- 默认通过 `environment/with-env.sh` 临时设置工具路径，不修改 `~/.bashrc`、`~/.profile` 或系统级环境；
- `make run`、`make test-qemu` 和 `make debug` 必须能在 WSL2 与 rootless 容器中无特权运行；
- 除可选 KVM 加速外，不要求访问宿主硬件设备。

---

## 14. 隔离开发环境与可逆清理

### 14.1 “不污染宿主”的可验收定义

本项目中的“不污染 Windows”不是指 Windows 磁盘上绝对不产生任何文件。启用 WSL2、注册发行版和保存发行版虚拟磁盘本身就是宿主变化。可验收标准定义为：

- Windows 不安装项目专用的 GCC、NASM、Make、QEMU、GDB、Python 包管理环境、MSYS2、Cygwin 或 MinGW；
- 不修改 Windows PATH、注册表、文件关联、系统代理、全局 Git 配置和系统服务；
- 不在 `Program Files`、`Windows`、Windows 用户配置目录中散落项目依赖；
- 专用 WSL 的 rootfs、虚拟磁盘、下载缓存和备份全部位于用户明确指定的单一目录；
- Windows 项目目录是唯一权威工作树，不保留第二份活动工作树；
- 删除环境时可以通过注销 WSL 发行版并删除该目录完成，不需要逐项卸载工具。

真实 Ubuntu 的“最小污染”定义为：

- 默认不直接向宿主 `/usr/local`、`/opt`、`/usr/lib` 安装项目工具链；
- 默认不执行项目脚本中的 `sudo apt install`、`sudo pip install` 或全局 npm 安装；
- 编译器、QEMU、GDB、Python venv、下载缓存和构建依赖均位于 rootless OCI 容器镜像或项目命名卷中；
- 宿主只需已有的 Podman，或明确选择已有 Docker 作为后端；项目脚本不得自动安装容器运行时；
- 删除容器、镜像、命名卷和项目缓存后，宿主恢复到项目开始前状态。

### 14.2 Windows 上的专用 WSL2 发行版

发行版固定命名为：

```text
MiniOrangeOS-Dev
```

用户必须为发行版指定集中存储目录，例如：

```powershell
$EnvRoot = "D:\ApplicationData\MiniOrangeOS"
```

该目录应包含：

```text
D:\ApplicationData\MiniOrangeOS\
├── rootfs\                 # WSL 虚拟磁盘和发行版文件
├── downloads\              # Ubuntu rootfs、工具链源码和校验文件
├── exports\                # 可选 wsl --export 备份
└── logs\                   # 创建、验证和清理日志
```

创建命令由仓库脚本封装：

```powershell
powershell -ExecutionPolicy Bypass -File .\environment\wsl\create.ps1 `
  -InstallRoot "D:\ApplicationData\MiniOrangeOS"
```

`create.ps1` 必须：

1. 检查 WSL2 是否已经可用；若未启用，只打印人工启用说明并停止，不得静默修改 Windows 可选功能或自动重启；
2. 下载并校验 Ubuntu 24.04 rootfs，或接收用户提供的本地 rootfs tar；
3. 使用 `wsl --import MiniOrangeOS-Dev <InstallRoot>\rootfs <rootfs.tar> --version 2` 导入，而不是把发行版安装到不可控的默认应用目录；
4. 在发行版内创建普通用户 `minios`，并通过 `/etc/wsl.conf` 设置为默认用户；
5. 仅在该发行版内部使用 apt 安装依赖；
6. 验证 Windows 权威工作树可通过 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS` 访问，不在 WSL 中克隆第二份活动仓库；
7. 调用 `environment/bootstrap-inside.sh` 构建交叉工具链；
8. 生成环境指纹和安装清单；
9. 不调用 `winget`、Chocolatey、Scoop，不执行 `setx PATH`，不安装 Windows 版 QEMU/GDB/GCC。

进入环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\environment\wsl\enter.ps1
```

执行单条命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\environment\wsl\enter.ps1 `
  -Command "cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS && ./environment/with-env.sh make test"
```

Codex 从 Windows 发起命令时，底层必须等价于：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc `
  'cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS && ./environment/with-env.sh make test'
```

唯一权威工作树保存在 `D:\DC\program-projects\OTHER\MiniOrangeOS`，Windows 侧负责文件编辑和 Git。`MiniOrangeOS-Dev` 通过 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS` 访问同一工作树，只在 Linux 侧运行构建、QEMU、GDB 和测试。WSL 不运行 Git，不保存第二份活动工作树。

### 14.3 WSL 内部依赖布局

隔离环境内统一使用：

```bash
export MINIOS_ENV_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/miniorangeos-dev"
```

目录布局：

```text
$MINIOS_ENV_ROOT/
├── toolchain/              # i686-elf Binutils/GCC
├── sources/                # 固定版本源码压缩包和解压目录
├── build/                  # 工具链中间构建目录
├── cache/                  # 下载缓存
├── venv/                   # 项目 Python 虚拟环境
├── manifests/              # 包版本和环境指纹
└── logs/                   # 工具链构建日志
```

交叉工具链前缀固定为：

```text
$MINIOS_ENV_ROOT/toolchain
```

不允许把 PATH 永久写入 `~/.bashrc` 或 `~/.profile`。所有命令使用：

```bash
./environment/with-env.sh make all
./environment/with-env.sh make test
./environment/with-env.sh make debug
```

`with-env.sh` 只对当前子进程临时设置：

```text
PATH
CROSS_PREFIX
PYTHONNOUSERSITE=1
PIP_REQUIRE_VIRTUALENV=true
LC_ALL=C.UTF-8
TZ=UTC
SOURCE_DATE_EPOCH
```

Python 包必须安装到 `$MINIOS_ENV_ROOT/venv`，禁止 `sudo pip`、`pip install --user` 和污染系统 site-packages。

### 14.4 WSL 调试方式

日常启动：

```bash
./environment/with-env.sh make run-serial
```

需要键盘和 VGA 文本交互时：

```bash
./environment/with-env.sh make run-curses
```

GDB 调试使用两个 WSL 终端。

终端一：

```bash
./environment/with-env.sh make debug
```

终端二：

```bash
./environment/with-env.sh make gdb
```

QEMU 默认使用纯软件模拟，不要求 Windows 安装 QEMU，也不要求 WSL 访问 KVM。`make debug` 必须绑定到 WSL 内部回环地址，不向局域网开放 GDB 端口。

### 14.5 真实 Ubuntu 24.04 上的隔离复验

真实 Ubuntu 主机不直接安装项目工具链。仓库提供与 CI 共用的 `environment/Containerfile`，默认后端为 rootless Podman；若宿主已经安装 Docker，可通过环境变量显式切换：

```bash
export MINIOS_CONTAINER_RUNTIME=podman   # 默认
# 或
export MINIOS_CONTAINER_RUNTIME=docker
```

创建开发镜像：

```bash
./environment/ubuntu/create.sh
```

进入交互式环境：

```bash
./environment/ubuntu/shell.sh
```

在容器内执行完整测试：

```bash
./environment/ubuntu/run.sh make test
```

启动 QEMU 串口模式：

```bash
./environment/ubuntu/run.sh make run-serial
```

终端文本交互：

```bash
./environment/ubuntu/run.sh make run-curses
```

GDB 调试时应启动一个可复用的开发容器，QEMU 和 GDB 均在同一容器网络命名空间内运行。不得把 GDB 端口监听到 `0.0.0.0`。

容器运行要求：

- 使用 `--userns=keep-id` 或等效机制，避免生成 root 所有的源码文件；
- 源码目录只绑定项目仓库，不绑定整个 `$HOME`；
- 缓存使用带项目标签的命名卷；
- 默认不使用 `--privileged`；
- QEMU 采用 TCG 软件模拟，KVM 仅作为显式可选加速；
- 不挂载 `/var/run/docker.sock`；
- 不继承宿主 SSH Agent、GPG Agent、浏览器配置或云凭据；
- CI 与真实 Ubuntu 复验使用相同 Containerfile 和版本清单。

### 14.6 环境版本锁定与验证

`environment/versions.env` 至少固定：

- Ubuntu 基础镜像摘要；
- Binutils 版本与 SHA-256；
- GCC 版本与 SHA-256；
- QEMU、GDB、NASM、Python 的期望主版本；
- Python 包哈希；
- Containerfile 版本。

执行：

```bash
./environment/verify.sh
```

必须输出：

```text
ENV_KIND=wsl|container|ci
OS_RELEASE=Ubuntu 24.04
ARCH=x86_64
CROSS_GCC=...
BINUTILS=...
QEMU=...
GDB=...
NASM=...
PYTHON=...
TOOLCHAIN_PREFIX=...
WORKTREE_FS=...
HOST_PATH_MUTATED=no
HOST_FINGERPRINT_SOURCE=recorded-pre-post-check
RESULT=PASS
```

`make env-check` 应调用同一验证脚本。环境不符合约束时必须失败，不允许仅打印警告后继续。

### 14.7 一键清理和删除

删除专用 WSL 前必须先确认源码已提交并推送。可选备份：

```powershell
powershell -ExecutionPolicy Bypass -File .\environment\wsl\backup.ps1 `
  -Output "D:\ApplicationData\MiniOrangeOS\exports\MiniOrangeOS-Dev.tar"
```

彻底删除：

```powershell
powershell -ExecutionPolicy Bypass -File .\environment\wsl\destroy.ps1 `
  -InstallRoot "D:\ApplicationData\MiniOrangeOS" `
  -Force
```

`destroy.ps1` 必须依次：

1. 检查并提示未推送提交；
2. `wsl --terminate MiniOrangeOS-Dev`；
3. `wsl --unregister MiniOrangeOS-Dev`；
4. 删除用户指定的集中目录；
5. 验证发行版不再出现在 `wsl -l -v`；
6. 不删除其他 WSL 发行版，不修改全局 WSL 配置。

真实 Ubuntu 清理：

```bash
./environment/ubuntu/destroy.sh --all
```

该脚本只删除带以下名称或标签的资源：

```text
miniorangeos-dev
io.miniorangeos.project=MiniOrangeOS
```

不得执行无选择的 `podman system prune -a`、`docker system prune -a`，不得删除其他项目的镜像、卷或容器。

项目仓库内的临时产物通过：

```bash
make distclean
```

删除。环境清理流程必须在 M0 和 M8 各演练一次，并把结果记录到 `docs/environment.md`。

---

## 15. Windows Codex、专用 WSL 与真实 Ubuntu 的协作规则

1. 唯一权威工作树位于 `D:\DC\program-projects\OTHER\MiniOrangeOS`，由 Windows 侧 Codex 编辑并使用 Windows Git。
2. `MiniOrangeOS-Dev` 通过 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS` 访问同一工作树，只执行 Linux 构建、QEMU、GDB 和测试，不运行 Git。
3. 不创建第二份活动工作树；`.gitattributes` 强制跨环境文本格式。所有源码、Makefile 和脚本以 Linux 为唯一构建和运行目标。
4. `.gitattributes` 强制以下文件使用 LF：
   - `.c`、`.h`、`.asm`、`.ld`；
   - `Makefile`；
   - `.sh`、`.py`、`.yml`；
   - `Containerfile`、`.env`、`.txt` 版本清单。
5. Windows Git 是该工作树的唯一 Git；WSL 禁止运行 Git。`/mnt/d` 的构建性能、大小写和 Linux 权限语义差异已作为接受的风险，必须通过 metadata 挂载、LF、可执行位、并行和增量构建测试持续验证。
6. Codex 每个任务开始时必须在 Windows 使用 Git 检查工作树，并在 WSL 运行环境验证：

```powershell
git status --short
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
./environment/verify.sh
'
```

7. 每个任务结束时必须在 WSL 中运行指定测试；T72 建立 Linux CI 后，还必须由 CI 再验证一次。
8. M1、M4、M6、M8 必须在真实 Ubuntu 容器中复验；M8 还必须从全新容器镜像和干净 Git 克隆完成构建。
9. WSL 与真实 Ubuntu 的构建产物应具备可解释的一致性；至少比较 ELF Header、段布局、符号表摘要和磁盘镜像布局。原始镜像中非确定性字段必须记录原因。
10. Windows 主机不得作为测试通过的证据；有效证据只包括 WSL 日志、真实 Ubuntu 容器日志和 Linux CI 日志。
11. 若 WSL 环境损坏，优先导出日志和未提交补丁，再销毁并重建发行版，不在 Windows 上临时搭建替代工具链。
12. 环境脚本不得访问无关的用户目录、浏览器数据、SSH 私钥或其他项目凭据。

---

## 16. Git 工作流

### 16.1 分支

```text
main
└── feature/TXX-short-description
```

单人阶段不建立长期 `dev` 分支，避免额外合并层级。`main` 始终保持可构建。

### 16.2 提交格式

```text
type(scope): summary

body

Refs: TXX
```

允许的类型：

- `feat`
- `fix`
- `test`
- `refactor`
- `docs`
- `build`
- `chore`

示例：

```text
feat(mm): add bitmap physical page allocator

- initialize regions from E820
- reserve loader and kernel pages
- add allocation exhaustion checks

Refs: T30
```

### 16.3 合并要求

- 工作区干净；
- 任务验收命令通过；
- T72 建立 Linux CI 后，CI 通过；
- 无未解释警告；
- 文档同步；
- 不包含大体积构建产物；
- 提交信息包含任务编号；
- Codex 输出变更摘要；
- 人工审查关键控制流后合并。

---

## 17. Codex 通用执行协议

每次向 Codex 下发任务时使用以下前置提示：

```text
你正在实现 MiniOrangeOS。必须先阅读 PROJECT_PLAN.md、
docs/README.md、docs/development-workflow.md，以及本任务涉及模块的文档。

执行规则：
1. 在 Windows 权威工作树中编辑文件并使用 Windows Git；Linux 构建、QEMU、GDB 和测试必须运行在 `MiniOrangeOS-Dev` WSL、真实 Ubuntu 隔离容器或 Linux CI 中。
2. 在 Windows 运行 `git status --short`，再通过 `wsl.exe` 在 `MiniOrangeOS-Dev` 中运行 `./environment/verify.sh`；环境验证失败时立即停止。WSL 不运行 Git。
3. 创建 feature/<任务编号>-<简短名称> 分支。
4. 只实现当前任务，不提前实现后续模块。
5. 遵循 C11 freestanding、NASM Intel 和 Linux Makefile 约束。
6. 不复制其他操作系统源码。
7. 优先补测试，再实现功能。
8. 所有失败必须显式处理，禁止静默忽略。
9. 完成后通过 `./environment/with-env.sh` 运行任务指定测试和已有回归测试。
10. 更新相关文档和环境清单；不得修改 Windows PATH、Linux Shell 全局配置或宿主 `/usr/local`。
11. 使用 Windows Git 创建 commit；任务验证全部通过后，允许按项目流程自动执行 `--no-ff` 合并。
12. 最后报告：环境指纹、设计、修改文件、命令、测试结果、风险和提交哈希。
13. 未在 WSL 或真实 Ubuntu 容器中通过的任务不得标记为完成；T72 建立 Linux CI 后，还必须通过 CI 验证。
14. 若实现与 `docs/` 前置设计冲突，先更新文档并在任务报告中解释冲突点和取舍。
```

### 17.1 Codex 任务完成报告模板

```text
任务：
环境：
环境指纹：
分支：
提交：

实现内容：
- 

关键设计：
- 

修改文件：
- 

执行命令：
- 

测试结果：
- 

未解决问题：
- 

下一任务前置条件：
- 
```

---

# 18. 里程碑计划

| 里程碑 | 目标日期 | 结果 |
|---|---|---|
| M0 | 2026-07-13 | 专用 WSL/真实 Ubuntu 隔离环境、仓库、交叉工具链、构建系统、串口测试框架 |
| M1 | 2026-07-14 | Boot Sector、Loader、保护模式、ELF 内核加载 |
| M2 | 2026-07-15 | 高半内核、VGA、串口、异常、PIC、PIT |
| M3 | 2026-07-17 | 键盘、分页基础、可重复启动的阶段演示 |
| M4 | 2026-07-24 | PMM、VMM、堆、进程、调度、Ring 3 |
| M5 | 2026-07-31 | 系统调用、ELF 用户程序、init、Shell |
| M6 | 2026-08-08 | ATA、VFS、自定义文件系统和持久化 |
| M7 | 2026-08-15 | 多级目录、完整文件命令、异常隔离和回归测试 |
| M8 | 2026-08-20 | 文档、代码量报告、演示脚本和答辩版本 |
| 缓冲期 | 2026-08-21 至 2026-08-31 | 修复、提前答辩和材料补充 |

里程碑日期是风险控制线，不是允许跳过质量门槛的理由。若进度落后，必须按照第 25 节的降级顺序收缩扩展功能。

---

# 19. 详细任务清单

## 阶段 0：工程基础

### T00：初始化仓库和工程规范

**依赖：** 无

**目标：**

- 创建目录骨架和 `environment/` 环境生命周期目录；
- 添加 `.gitignore`、`.gitattributes`、`LICENSE`；
- 添加 README、CONTRIBUTING 和计划书；
- 建立统一命名、错误码和整数类型约定。

**完成定义：**

- Windows Git 执行的 `git status` 干净；
- 文本文件行尾为 LF；
- `build/`、镜像和工具链不进入 Git；
- README 明确项目目标、Windows 权威工作树、Windows Git、专用 WSL 构建测试方式和真实 Ubuntu 容器复验方式；
- `.gitignore` 排除环境缓存、venv、工具链、容器状态文件和构建产物。
- `ProjectLayoutTests` 在 `MiniOrangeOS-Dev` 中通过。

**Codex 任务提示：**

```text
执行 T00。根据 PROJECT_PLAN.md 创建最小仓库骨架和工程规范文件。
不要添加功能代码。配置 LF 行尾、构建产物忽略规则、MIT License、
C/汇编命名规范和提交规范；创建环境脚本占位及 `docs/environment.md` 骨架。
不得安装任何依赖。完成后检查目录结构并提交。
```

---

### T01：隔离环境生命周期和交叉工具链

**依赖：** T00

**目标：**

- 实现 `environment/wsl/create.ps1`、`enter.ps1`、`backup.ps1`、`destroy.ps1`；
- 实现 `environment/Containerfile` 和 `environment/ubuntu/*.sh`；
- 实现 `environment/bootstrap-inside.sh`、`with-env.sh` 和 `verify.sh`；
- 编写可重复执行的 `tools/build_toolchain.sh`；
- 构建 `i686-elf-binutils` 和仅 C 前端的 GCC；
- 工具链安装到 `$MINIOS_ENV_ROOT/toolchain`，不写入 `/usr/local`；
- 固定版本、下载地址和 SHA-256；
- 提供环境创建、验证、备份和完整删除流程。

**完成定义：**

在专用 WSL 中：

```bash
./environment/verify.sh
./environment/with-env.sh i686-elf-gcc --version
./environment/with-env.sh i686-elf-ld --version
```

全部成功；重复执行 bootstrap 不破坏现有安装。

按用户当前“仅在 WSL 中测试”的要求，在独立 Ubuntu 24.04 WSL2 测试发行版中以非 root 用户运行 rootless Podman：

```bash
MINIOS_CONTAINER_BACKEND=podman ./environment/ubuntu/create.sh
MINIOS_CONTAINER_BACKEND=podman ./environment/ubuntu/run.sh ./environment/verify.sh
MINIOS_CONTAINER_BACKEND=podman ./environment/ubuntu/destroy.sh --all
```

可以创建、验证并只删除本项目资源和专用构建缓存。该验收覆盖 Ubuntu 24.04 用户态与 rootless OCI 语义，但不冒充原生 Linux 内核；物理或虚拟机 Ubuntu 的内核差异由后续 Linux CI 复验。

WSL 删除脚本必须通过一次空环境演练，确认不影响其他发行版。任何脚本均不得自动修改 Windows PATH、Windows 注册表、Linux `~/.bashrc` 或宿主 `/usr/local`。

**Codex 任务提示：**

```text
执行 T01。实现 MiniOrangeOS 的隔离环境生命周期。
Windows 使用 Windows Git 负责版本控制和文件编辑，不安装 Windows 原生编译、调试或虚拟化工具链；
Linux 构建和测试仅在 WSL 隔离模型中执行，专用日常发行版固定为 MiniOrangeOS-Dev；
容器集成测试使用独立 Ubuntu 24.04 WSL2 测试发行版中的 rootless Podman，原生 Linux 内核差异留给后续 CI。
实现 create/enter/backup/destroy、Containerfile、bootstrap、with-env 和 verify。
交叉工具链安装到 $MINIOS_ENV_ROOT/toolchain，固定版本并校验 SHA-256，
不修改任何永久 PATH、Shell 配置、/usr/local 或其他项目资源。
完成后分别验证 WSL 和容器创建/构建/清理，并更新 docs/environment.md。
```

---

### T02：最小构建系统

**依赖：** T01

**目标：**

- 建立顶层 Makefile；
- 编译空 Boot、Loader、Kernel 框架；
- 生成固定大小原始磁盘镜像；
- 添加链接脚本和符号文件。

**完成定义：**

```bash
./environment/with-env.sh make clean
./environment/with-env.sh make all
./environment/with-env.sh make image
```

全部成功，且第二次增量构建不重新编译无关文件。

**Codex 任务提示：**

```text
执行 T02。在已通过 verify.sh 的隔离 Linux 环境中建立 GNU Make 构建系统，编译 NASM Boot/Loader、
C11 freestanding 内核和链接脚本，并生成原始磁盘镜像。
当前代码只需最小占位，不实现启动功能。禁止在源码目录生成对象文件。
加入依赖文件和并行构建支持，运行构建测试后提交。
```

---

### T03：串口测试和 QEMU 自动化框架

**依赖：** T02

**目标：**

- 提供 `make run-serial` 和 `make run-curses`；
- 提供 `make debug`/`make gdb` 的本地回环调试接口；
- 提供超时退出的 QEMU 测试脚本；
- 约定 `[TEST] ... PASS/FAIL` 格式。

**完成定义：**

- QEMU 超时后可被脚本正确终止；
- 测试失败返回非零状态；
- 不残留 QEMU 进程；
- WSL 和容器模式均不需要 Windows/Ubuntu 宿主安装 QEMU；
- GDB 端口只监听隔离环境回环地址。

**Codex 任务提示：**

```text
执行 T03。实现可在专用 WSL 和真实 Ubuntu 容器中运行的 QEMU 串口、curses、GDB 和无界面测试框架。
测试脚本应启动 qemu-system-i386、捕获 COM1、设置超时、
识别 PASS/FAIL、清理子进程并返回正确状态。先用固定测试镜像或占位输出
验证脚本本身，补充测试文档并提交。
```

---

## 阶段 1：启动链

### T10：512 字节 Boot Sector

**依赖：** T02、T03

**目标：**

- BIOS 启动；
- 初始化段寄存器和栈；
- 输出启动标记；
- 保存启动盘号；
- 读取二级 Loader；
- 校验错误；
- 跳转到 Loader。

**完成定义：**

串口或屏幕输出：

```text
[S1] boot
[S1] loader loaded
```

Boot 二进制严格为 512 字节，末尾签名正确。

**Codex 任务提示：**

```text
执行 T10。从零编写 BIOS x86 Boot Sector，使用 NASM 16 位实模式。
初始化寄存器、栈和方向标志，保存 DL，使用 INT 13h 扩展读取固定布局的
二级 Loader，检查 Carry Flag 和返回状态，失败时显示错误并停机。
加入 boot 二进制尺寸和 0xAA55 签名测试，QEMU 验证后提交。
```

---

### T11：二级 Loader 实模式框架

**依赖：** T10

**目标：**

- Loader 被正确加载；
- 建立独立栈；
- 输出日志；
- 接收启动盘号；
- 提供 BIOS 输出和磁盘读接口。

**完成定义：**

```text
[S2] loader entered
[S2] boot drive=...
```

**Codex 任务提示：**

```text
执行 T11。实现二级 Loader 的 16 位入口、栈、日志和 BIOS 磁盘读取封装。
保持模块边界清晰，不进入保护模式。验证 Stage 1 传递的启动盘号，
为后续 E820 和内核加载准备接口。QEMU 测试并提交。
```

---

### T12：A20 和 E820 内存映射

**依赖：** T11

**目标：**

- 开启并验证 A20；
- 通过 INT 15h E820 获取内存区域；
- 过滤零长度项；
- 把结果放入 Boot Info。

**完成定义：**

串口打印至少一项可用内存区域；错误和条目上限得到处理。

**Codex 任务提示：**

```text
执行 T12。为 Loader 添加 A20 开启与验证，以及 BIOS E820 内存探测。
定义版本化 Boot Info 结构，限制条目数量，验证 SMAP 签名和返回长度，
忽略零长度条目但保留区域类型。添加宿主侧结构布局静态断言和 QEMU 日志测试。
```

---

### T13：GDT 和保护模式切换

**依赖：** T12

**目标：**

- 建立平坦内存模型 GDT；
- 禁用中断；
- 设置 CR0.PE；
- 远跳转进入 32 位；
- 重新加载段寄存器和栈。

**完成定义：**

```text
[S2] protected mode
```

且无重启、三重故障或卡死。

**Codex 任务提示：**

```text
执行 T13。实现 Loader 的临时 GDT 和实模式到 32 位保护模式切换。
代码段和数据段覆盖 4GiB，严格处理 far jump、段寄存器和 32 位栈。
进入保护模式后通过 VGA 或串口输出确认。加入 GDT 描述符布局检查并提交。
```

---

### T14：保护模式 ATA PIO 读取

**依赖：** T13

**目标：**

- 在 Loader 中实现 ATA PIO LBA28 读取；
- 超时检测；
- 错误位处理；
- 读取内核 ELF 到暂存区。

**完成定义：**

读取已知扇区并校验固定签名。

**Codex 任务提示：**

```text
执行 T14。在 Loader 保护模式中实现最小 ATA PIO LBA28 扇区读取。
仅支持主 IDE 主盘，包含 BSY/DRQ/ERR 检查、轮询超时和扇区数量限制。
通过读取镜像中的已知测试扇区验证数据，不解析 ELF。失败必须输出错误码。
```

---

### T15：Loader 解析 ELF32 内核

**依赖：** T14

**目标：**

- 验证 ELF Header；
- 遍历 `PT_LOAD`；
- 把段复制到物理地址；
- 清零 BSS；
- 构造 Boot Info；
- 跳转内核物理入口。

**完成定义：**

最小内核入口输出：

```text
[KERNEL] entered
```

**Codex 任务提示：**

```text
执行 T15。为 Loader 实现严格的 ELF32 内核加载器。
验证魔数、位数、端序、机器类型、Program Header 边界、
filesz/memsz 和目标物理范围。只处理 PT_LOAD，复制文件数据并清零 BSS，
将 Boot Info 指针传给内核入口。添加恶意 ELF 宿主测试和 QEMU 成功测试。
```

---

## 阶段 2：内核基础和中断

### T20：内核入口和高半切换

**依赖：** T15

**目标：**

- 内核链接到 `0xC0000000`；
- Loader 建立临时 identity + high-half 映射；
- 开启分页；
- 内核切换到高半地址；
- 移除不需要的 identity 映射。

**完成定义：**

内核日志显示当前 EIP 位于高半地址；访问低地址空指针触发页故障。

**Codex 任务提示：**

```text
执行 T20。实现 4KiB 两级分页的最小高半内核启动。
Loader 同时映射低端过渡区域和 0xC0000000 高半，设置 CR3、CR0.PG，
内核跳到高半入口后建立栈并取消不必要的低端映射。
更新 linker.ld，添加地址和页对齐断言，QEMU 验证空指针不再可访问。
```

---

### T21：串口、VGA、日志和 Panic

**依赖：** T20

**目标：**

- COM1 初始化；
- VGA 字符输出；
- `kprintf` 的最小安全实现；
- 分级日志；
- `panic(file,line,func,...)`；
- `assert`。

**完成定义：**

串口和 VGA 输出一致；Panic 停机且保留错误上下文。

**Codex 任务提示：**

```text
执行 T21。实现独立于标准库的 COM1、VGA 文本控制台、最小格式化输出、
日志等级、assert 和 panic。格式化支持 %s %c %d %u %x %p，
必须限制递归和缓冲区溢出。添加宿主侧格式化测试和 QEMU panic 测试。
```

---

### T22：GDT、IDT 和 CPU 异常

**依赖：** T21

**目标：**

- 内核 GDT；
- IDT；
- 0–31 号异常汇编桩；
- 统一中断帧；
- 错误码兼容；
- 异常名称和寄存器转储。

**完成定义：**

除零、无效操作码和页故障能够输出准确异常信息；内核异常 Panic。

**Codex 任务提示：**

```text
执行 T22。实现内核 GDT、IDT、32 个 CPU 异常入口和统一 trap frame。
正确区分 CPU 自动压入错误码的异常。保存通用寄存器和段寄存器，
调用 C 分发函数后恢复。添加除零和 ud2 测试，确保栈布局有静态断言。
```

---

### T23：PIC 和 PIT

**依赖：** T22

**目标：**

- 重映射 8259A；
- IRQ 屏蔽管理；
- EOI；
- PIT 周期中断；
- 全局 tick。

**完成定义：**

tick 单调增长；中断频率稳定；不会重复或遗漏 EOI。

**Codex 任务提示：**

```text
执行 T23。实现 8259A PIC 重映射、IRQ mask API、正确 EOI 顺序和 PIT 定时器。
设置合理频率，维护 64 位 ticks，加入短时自测。中断处理器不得执行阻塞操作。
QEMU 串口输出定时测试结果并提交。
```

---

### T24：PS/2 键盘和控制台输入

**依赖：** T23

**目标：**

- IRQ1；
- Scancode Set 1；
- Shift、Caps Lock、Backspace、Enter；
- 环形缓冲区；
- 阻塞读取接口。

**完成定义：**

能连续输入、退格和回车；缓冲区满时行为确定；无中断上下文死锁。

**Codex 任务提示：**

```text
执行 T24。实现 PS/2 键盘 IRQ1、Set 1 扫描码解析和线程安全环形缓冲。
支持字母、数字、常用符号、Shift、Caps Lock、Backspace、Enter。
中断只写缓冲区并唤醒等待者，不做复杂输出。添加扫描码宿主测试和 QEMU 交互测试。
```

---

## 阶段 3：内存管理

### T30：物理页 Bitmap 分配器

**依赖：** T20、T21

**目标：**

- 解析 E820；
- 标记可用和保留页；
- 保留内核、Loader、Boot Info、页表和设备区域；
- 分配、释放单页和连续页；
- 重复释放检测。

**完成定义：**

随机分配测试不产生重复页；耗尽时安全失败；释放后可复用。

**Codex 任务提示：**

```text
执行 T30。实现基于 E820 的 4KiB 物理页 Bitmap 分配器。
所有非 USABLE 区域默认保留，再显式释放可用页；保留内核和启动数据。
提供 alloc_page/free_page 和可选连续页接口，包含对齐、越界、重复释放检查。
为纯算法部分编写宿主测试，并在 QEMU 中做压力测试。
```

---

### T31：正式虚拟内存管理器

**依赖：** T30

**目标：**

- 创建和销毁页目录；
- 映射、解除映射；
- 查询物理地址；
- TLB 刷新；
- 共享内核高半映射；
- 递归页表映射。

**完成定义：**

映射测试、权限测试、解除映射测试通过；无页表内存泄漏。

**Codex 任务提示：**

```text
执行 T31。实现正式 x86 两级 VMM：页目录创建/销毁、4KiB map/unmap、
权限查询、invlpg、递归映射和共享内核高半。为用户页目录复制内核 PDE，
但不得共享用户页表。加入页表回收和映射冲突检查，QEMU 运行内存测试。
```

---

### T32：内核堆

**依赖：** T31

**目标：**

- `kmalloc`、`kcalloc`、`krealloc`、`kfree`；
- 对齐分配；
- 块分裂和合并；
- 元数据校验；
- 越界和双重释放检测。

**完成定义：**

随机分配释放测试通过；空闲块可合并；堆扩展通过 VMM 分配页。

**Codex 任务提示：**

```text
执行 T32。实现 first-fit 内核堆，支持块分裂、相邻空闲块合并、页级扩展、
基本校验和对齐分配。禁止依赖宿主 malloc。编写宿主模型测试和内核压力测试，
检测双重释放、错误指针和元数据损坏。
```

---

### T33：用户地址空间和安全拷贝

**依赖：** T31、T32

**目标：**

- 每进程独立地址空间；
- 用户页映射；
- 用户指针验证；
- `copy_from_user`、`copy_to_user`、`copy_string_from_user`。

**完成定义：**

跨页拷贝、未映射页、只读页、内核地址和长度溢出测试通过。

**Codex 任务提示：**

```text
执行 T33。实现用户地址空间 API 和安全 usercopy。
必须逐页验证范围、权限和整数溢出，支持跨页数据。
任何用户非法地址只返回错误，不直接解引用导致内核异常。
编写覆盖边界页、零长度、超长字符串和内核地址的测试。
```

---

### T34：页故障处理和受控懒分配

**依赖：** T33

**目标：**

- 解码 CR2 和错误码；
- 区分内核/用户错误；
- 支持用户堆和栈的受控懒分配；
- 非法访问终止用户进程。

**完成定义：**

用户空指针、写只读页和访问内核空间仅终止当前进程；内核页故障 Panic。

**Codex 任务提示：**

```text
执行 T34。增强 page fault handler，解析 present/write/user/reserved/instruction 位。
仅对注册过的用户堆或栈增长区域执行懒分配，并设置增长上限。
其他用户错误终止进程并记录原因；内核错误 panic。
添加多种非法访问用户程序测试。
```

---

## 阶段 4：进程、调度和 Ring 3

### T40：PCB、内核线程和上下文切换

**依赖：** T23、T32

**目标：**

- PCB 分配；
- 内核栈；
- 汇编上下文切换；
- 运行队列；
- idle 线程。

**完成定义：**

两个内核线程能反复切换并保持独立栈和寄存器状态。

**Codex 任务提示：**

```text
执行 T40。实现 PCB、内核栈、运行队列、idle 线程和 x86 汇编上下文切换。
明确 caller-saved/callee-saved 约定，保存 ESP、EBP、EBX、ESI、EDI 和返回地址。
先实现协作式 yield，使用两个线程做寄存器和栈隔离测试。
```

---

### T41：抢占式时间片调度

**依赖：** T40

**目标：**

- PIT 驱动抢占；
- Round-Robin；
- 临界区和调度禁用计数；
- READY/RUNNING/BLOCKED 状态；
- `sleep` 和唤醒队列。

**完成定义：**

CPU 密集线程不能独占；睡眠时间误差在一个 tick 范围内；无运行队列损坏。

**Codex 任务提示：**

```text
执行 T41。在 PIT 中断返回路径中加入抢占式时间片轮转。
实现 scheduler lock 嵌套计数、sleep/wakeup、状态转换和运行队列一致性检查。
中断和普通上下文中的调度入口必须明确。加入饥饿、睡眠和高频切换压力测试。
```

---

### T42：TSS 和 Ring 3 切换

**依赖：** T22、T33、T40

**目标：**

- 用户代码段和数据段；
- TSS；
- 每进程更新 `esp0`；
- 构造 `iret` 帧进入 Ring 3；
- 验证 CPL。

**完成定义：**

用户代码在 Ring 3 运行；直接执行特权指令触发保护异常并终止进程。

**Codex 任务提示：**

```text
执行 T42。为 GDT 增加 Ring 3 code/data 段和 TSS，加载 TR。
创建最小用户页、用户栈和内核栈，通过 iret 从 Ring 0 进入 Ring 3。
每次切换更新 TSS.esp0。编写用户程序验证 CPL=3，并测试 cli 等特权指令被拒绝。
```

---

### T43：系统调用入口和分发表

**依赖：** T42、T33

**目标：**

- IDT `0x80` DPL=3；
- 保存用户上下文；
- 系统调用号检查；
- 参数传递；
- 返回值；
- 可抢占性规则。

**完成定义：**

`getpid`、`write`、`yield` 三个最小调用从 Ring 3 成功执行。

**Codex 任务提示：**

```text
执行 T43。实现 int 0x80 系统调用入口、trap frame、分发表和最小
getpid/write/yield。IDT 门必须允许 Ring 3，入口保存完整用户上下文，
验证系统调用号，统一负错误码。write 必须使用 usercopy，不能直接信任指针。
```

---

### T44：进程生命周期

**依赖：** T41、T43

**目标：**

- PID 分配；
- 父子关系；
- `exit`；
- `waitpid`；
- Zombie；
- 资源回收；
- 用户异常退出。

**完成定义：**

父进程可获取子进程退出码；地址空间、内核栈和文件描述符被正确回收。

**Codex 任务提示：**

```text
执行 T44。实现进程 PID、父子关系、exit、waitpid、Zombie 和 reaping。
退出时关闭文件描述符并释放用户地址空间，但保留等待所需的最小状态。
处理父进程先退出和孤儿进程。添加正常退出、异常退出和重复等待测试。
```

---

## 阶段 5：ELF 用户程序和 Shell

### T50：内核 ELF32 用户程序加载器

**依赖：** T33、T42、T44、文件读取临时接口

**目标：**

- 完整验证 ELF32；
- 建立地址空间；
- 加载段；
- 用户栈；
- `argc/argv`；
- 返回可调度进程。

**完成定义：**

两个不同 ELF 程序能在独立地址空间运行；非法 ELF 被拒绝。

**Codex 任务提示：**

```text
执行 T50。实现内核 ELF32 用户加载器，严格按计划书验证 ELF 和 PT_LOAD。
创建独立页目录，按段权限映射，清零 BSS，构造带 argc/argv 的用户栈，
创建初始 trap frame。先允许从内核嵌入的测试文件读取，接口必须能后续接 VFS。
```

---

### T51：用户态启动代码和最小 libc

**依赖：** T43、T50

**目标：**

- `crt0.asm`；
- 系统调用封装；
- `strlen`、`strcmp`、`memcpy`、`memset`；
- 简单 `printf`；
- 用户链接脚本。

**完成定义：**

用户 `main(argc, argv)` 正确接收参数并返回到 `exit`。

**Codex 任务提示：**

```text
执行 T51。创建独立的用户态 crt0、linker.ld、系统调用封装和最小 libc。
不得链接宿主 libc。实现 main(argc,argv) 调用和返回后 SYS_exit。
加入用户库宿主测试，并构建两个静态 ELF32 测试程序。
```

---

### T52：init 和用户态 Shell

**依赖：** T44、T50、T51

**目标：**

- `/bin/init`；
- `/bin/sh`；
- 前台进程；
- 参数解析；
- 内建命令；
- spawn/wait。

**完成定义：**

启动后自动进入用户态 Shell，可执行 `echo`、`help`、`ps` 和故障测试程序。

**Codex 任务提示：**

```text
执行 T52。实现用户态 init 和 shell。init 启动 /bin/sh，并在异常退出后可重启。
shell 从标准输入读取，支持编辑、空白分词、argc/argv、内建 help/clear/pwd/cd，
通过 spawn+wait 执行外部程序。限制命令长度和参数数量，处理未知命令。
```

---

### T53：基础用户程序集

**依赖：** T52

**目标：**

实现 `echo`、`ps`、`memtest`、`fault`，为文件系统命令预留接口。

**完成定义：**

用户态程序不能直接访问内核内存；非法程序退出后 Shell 继续工作。

**Codex 任务提示：**

```text
执行 T53。实现 echo、ps、memtest、fault 等用户程序。
fault 应覆盖空指针、内核地址、只读页写入和特权指令。
每次故障只终止当前用户进程，Shell 必须继续运行。记录串口结果并提交。
```

---

## 阶段 6：磁盘和文件系统

### T60：内核 ATA PIO 驱动

**依赖：** T23、T32

**目标：**

- LBA28 读写；
- 设备识别；
- 状态轮询和超时；
- 互斥；
- 扇区边界检查。

**完成定义：**

测试扇区反复读写一致；超时和错误不会死锁内核。

**Codex 任务提示：**

```text
执行 T60。实现内核 ATA PIO 主 IDE 主盘驱动，支持 LBA28 单扇区和多扇区读写。
包含 IDENTIFY、BSY/DRQ/ERR/DF 检查、超时、锁和缓存 flush。
测试只操作镜像预留区域，避免破坏 Boot 和 Kernel。
```

---

### T61：块设备层

**依赖：** T60

**目标：**

- 统一块设备接口；
- 4 KiB 逻辑块到 512B 扇区转换；
- 设备边界；
- 并发序列化。

**完成定义：**

任意对齐逻辑块读写通过；越界访问被拒绝。

**Codex 任务提示：**

```text
执行 T61。在 ATA 上建立通用 block device 抽象。
定义设备容量、逻辑块大小、read_blocks/write_blocks，统一边界和错误码。
实现 4KiB 文件系统块到 512B 扇区的转换并添加读写一致性测试。
```

---

### T62：宿主侧 mkfs 和镜像装配

**依赖：** T61 的磁盘布局约定

**目标：**

- Python `mkfs.py`；
- 创建 Superblock、Bitmap、inode 表和根目录；
- 将用户 ELF 写入 `/bin`；
- 生成可启动镜像。

**完成定义：**

宿主工具可解析自己生成的镜像；镜像布局不重叠。

**Codex 任务提示：**

```text
执行 T62。编写 Python mkfs 和镜像装配工具，依据单一布局配置创建文件系统，
初始化 root、bin 目录并导入用户 ELF。所有结构使用显式 little-endian 编码，
不得直接依赖 Python 对象内存布局。添加镜像边界、确定性构建和往返解析测试。
```

---

### T63：文件系统挂载和分配器

**依赖：** T61、T62

**目标：**

- 挂载；
- Superblock 验证；
- inode/data bitmap；
- 分配和释放；
- 元数据同步。

**完成定义：**

内核能挂载镜像，读取根 inode；分配后重启仍一致。

**Codex 任务提示：**

```text
执行 T63。实现 MiniFS 挂载、Superblock 校验、inode/data bitmap 分配与释放。
检查 magic、版本、块大小、区域边界和 checksum。
元数据更新顺序必须明确，错误时不越界。加入耗尽、重复释放和重启一致性测试。
```

---

### T64：inode 数据块映射

**依赖：** T63

**目标：**

- 10 个直接块；
- 一级间接块；
- 文件扩容；
- 稀疏区域清零；
- 截断和回收。

**完成定义：**

跨直接/间接边界读写一致；截断后空间可复用。

**Codex 任务提示：**

```text
执行 T64。实现 inode 文件偏移到数据块的映射，支持直接块和一级间接块。
扩容时新块清零，失败时回滚已分配资源；截断释放多余块和间接块。
添加跨块、跨直接边界、磁盘满和截断回收测试。
```

---

### T65：目录和路径解析

**依赖：** T64

**目标：**

- 目录项；
- `.`、`..`；
- 绝对路径；
- 多级路径；
- 创建和删除空目录；
- 名称冲突。

**完成定义：**

复杂路径测试通过；不能删除非空目录；不能越过根目录。

**Codex 任务提示：**

```text
执行 T65。实现固定长度目录项、路径规范化和多级目录查找。
支持 /、重复斜杠、.、..，限制组件长度和总路径长度。
实现 mkdir、rmdir、lookup、readdir，禁止删除非空目录和根目录。
为路径解析编写宿主测试和内核集成测试。
```

---

### T66：VFS、文件对象和文件描述符

**依赖：** T44、T64、T65

**目标：**

- VFS 接口；
- inode/file 分层；
- 每进程 FD 表；
- 标准输入输出；
- open/read/write/lseek/close/stat。

**完成定义：**

多个进程拥有独立文件偏移；关闭和退出不会泄漏引用。

**Codex 任务提示：**

```text
执行 T66。建立最小 VFS 和 file object 层，把 MiniFS、控制台和键盘统一到
open/read/write/lseek/close/stat 接口。每进程维护 FD 表和引用计数，
0/1/2 对应标准输入输出错误。添加共享 inode、独立 offset 和退出清理测试。
```

---

### T67：文件系统系统调用和用户命令

**依赖：** T43、T52、T66

**目标：**

- 文件相关系统调用；
- 用户 `ls`、`cat`、`touch`、`write`、`mkdir`、`rm`；
- `cd`、`pwd`。

**完成定义：**

Shell 能创建目录和文件、写入、读取、删除；错误提示明确。

**Codex 任务提示：**

```text
执行 T67。把 VFS 接入 open/close/read/write/lseek/create/unlink/mkdir/readdir/stat
系统调用，所有路径和缓冲区使用 usercopy。实现 ls、cat、touch、write、mkdir、rm，
以及 Shell 的 cd/pwd。覆盖无权限概念下的所有边界错误和非法 FD。
```

---

### T68：持久化、fsck 和损坏防护

**依赖：** T67

**目标：**

- 重启持久化；
- 宿主侧 `fsck.py`；
- inode/块引用一致性；
- Bitmap 检查；
- 损坏镜像安全拒绝。

**完成定义：**

创建文件后重启仍可读取；fsck 对正常镜像通过，对人工损坏镜像报告问题。

**Codex 任务提示：**

```text
执行 T68。完成重启持久化验收和只读 fsck.py。
检查 Superblock、Bitmap、inode、目录引用、块重复占用、孤立 inode 和越界块。
构造损坏镜像测试，内核挂载时必须拒绝明显危险布局，不能因坏元数据越界。
```

---

## 阶段 7：测试、CI 和文档

### T70：宿主侧单元测试体系

**依赖：** 各纯算法模块

**目标：**

对以下模块建立宿主测试：

- Bitmap；
- 链表；
- 格式化；
- ELF 校验；
- 路径解析；
- 文件系统结构编解码；
- mkfs/fsck。

**完成定义：**

`make test-host` 可重复通过；测试不依赖 QEMU。

**Codex 任务提示：**

```text
执行 T70。整理宿主侧测试体系，把可移植纯算法与硬件代码隔离。
覆盖 bitmap、list、printf、ELF validator、path parser、mkfs/fsck。
测试需包含正常、边界和恶意输入，失败返回非零，接入 make test-host。
```

---

### T71：QEMU 集成测试矩阵

**依赖：** T53、T68

**目标：**

自动测试：

- 启动；
- 异常；
- 中断；
- 内存；
- 调度；
- Ring 3；
- 系统调用；
- ELF；
- 文件系统；
- 持久化。

**完成定义：**

`make test-qemu` 无人工输入完成测试，并生成日志文件。

**Codex 任务提示：**

```text
执行 T71。建立 QEMU 串口集成测试矩阵。
每个测试使用唯一标识和最终 PASS/FAIL，设置超时，确保 QEMU 被清理。
持久化测试分两次启动同一临时镜像：第一次写入，第二次读取验证。
失败日志保存在 build/test-logs。
```

---

### T72：Linux CI

**依赖：** T70、T71

**目标：**

- Ubuntu runner；
- 使用 `environment/Containerfile` 构建与真实 Ubuntu 相同的隔离镜像；
- 缓存交叉工具链和容器层；
- 构建；
- 宿主测试；
- QEMU 测试；
- 上传失败日志。

**完成定义：**

Pull Request 自动执行；失败可从日志定位。

**Codex 任务提示：**

```text
执行 T72。创建 Linux CI 工作流，使用 environment/Containerfile 构建固定环境，
缓存容器层和 i686-elf 工具链，先执行 environment/verify.sh，
再依次执行 make check、make test-host、make test-qemu。
失败时上传串口日志和构建日志。不得依赖 Windows runner。
```

---

### T73：架构和实现文档

**依赖：** 核心功能稳定；v1.2 已存在 `docs/` 前置设计文档

**目标：**

将前置设计文档校准为实现文档，覆盖：

- architecture；
- boot；
- memory；
- process；
- syscall；
- filesystem；
- testing；
- problems；
- provenance；
- environment。

**完成定义：**

文档与代码一致；包含流程图、内存图、磁盘图和关键数据结构；所有“前置设计”“待实现”表述已按真实状态更新；每份文档引用真实文件、关键函数、测试命令和测试结果；来源登记与代码量报告一致。

**Codex 任务提示：**

```text
执行 T73。根据当前代码校准 docs，而不是按计划猜测。
每份文档必须引用真实文件和函数，说明设计理由、控制流、边界条件、
已知限制和测试。保留并修正 Mermaid 图，但不得伪造尚未实现的功能。
核对 docs/README.md 中列出的全部文档，消除“前置设计”和实际实现不一致之处。
```

---

### T74：答辩版本和演示脚本

**依赖：** T71、T73

**目标：**

- 版本标签；
- 一键演示；
- 代码量报告；
- 来源报告；
- 备份日志和视频录制脚本；
- 答辩问题。

**完成定义：**

从干净环境执行：

```bash
./environment/verify.sh
./environment/with-env.sh make clean
./environment/with-env.sh make test
./environment/with-env.sh make image
./environment/with-env.sh make run-serial
```

全部正常；演示脚本在 8 分钟内完成核心证明。

**Codex 任务提示：**

```text
执行 T74。整理答辩版本：生成 release checklist、演示命令、代码量报告、
来源清单、测试摘要和常见答辩问题。创建只包含源码和文档链接的提交说明，
不要提交构建产物。所有演示步骤必须在新建 WSL 或全新真实 Ubuntu 容器中复验；最后演练环境销毁且不得影响其他项目资源。
```

---

# 20. 测试策略

## 20.1 测试层级

| 层级 | 目标 |
|---|---|
| 环境层 | 发行版/容器版本、工具路径、宿主污染约束、可删除性 |
| 编译期 | 静态断言、结构大小、链接地址、未定义符号 |
| 宿主单元测试 | 纯算法、解析器、Bitmap、路径、文件系统工具 |
| QEMU 内核测试 | 中断、分页、堆、调度、Ring 3、系统调用 |
| QEMU 用户测试 | ELF、用户指针、异常隔离、Shell |
| 镜像测试 | mkfs、fsck、持久化、损坏防护 |
| 人工调试 | GDB 断点、寄存器、页表和堆栈检查 |

## 20.2 必须覆盖的负面测试

- Boot 读取失败；
- ELF 魔数错误；
- ELF Header 越界；
- E820 条目过多；
- 物理页耗尽；
- 页表映射冲突；
- 用户指针越过 `0xC0000000`；
- 用户写只读页；
- 用户访问未映射页；
- 系统调用号越界；
- 文件描述符越界；
- 路径过长；
- 目录不存在；
- 磁盘满；
- inode 耗尽；
- 文件跨直接和间接块；
- 损坏 Superblock；
- Bitmap 与 inode 不一致；
- 用户进程崩溃后 Shell 继续运行。

## 20.3 串口测试协议

```text
[TEST] suite=test_name begin
[TEST] case=case_name PASS
[TEST] case=case_name FAIL code=...
[TEST] suite=test_name PASS
[TEST] all PASS
```

内核测试模式成功后使用 QEMU debug-exit 设备或约定 I/O 端口主动退出，避免只依赖超时。

---

# 21. A 类自主实现证明

必须维护 `docs/provenance.md`，包含：

| 模块 | 实现方式 | 参考资料 | 是否包含外部代码 | 审查人 |
|---|---|---|---|---|
| Boot | 从零 | Intel/BIOS 文档 | 否 | 开发者 |
| Paging | 从零 | Intel 手册 | 否 | 开发者 |
| MiniFS | 自主设计 | 文件系统教材 | 否 | 开发者 |

同时执行：

```bash
make loc
```

报告至少区分：

- Boot/Loader 汇编；
- 内核 C/汇编；
- 用户程序；
- 工具；
- 测试；
- 文档；
- 自动生成文件；
- 第三方文件。

不得把以下内容计入自主核心代码：

- 编译产物；
- 生成镜像；
- 复制的头文件；
- 第三方库；
- 自动生成的表格；
- 大量重复测试数据。

Codex 辅助生成不等于可以不理解。每个里程碑后，开发者必须在 `docs/review-notes.md` 记录：

- 阅读过的核心文件；
- 能解释的关键路径；
- 发现并修正的 Codex 问题；
- 尚不理解的部分；
- 后续补课内容。

---

# 22. 最终验收标准

项目只有同时满足以下条件才算完成：

## 22.1 启动

- QEMU 能从原始磁盘镜像启动；
- 使用自写 Stage 1 和 Stage 2；
- Loader 读取 E820；
- Loader 加载 ELF32 内核；
- 内核运行在高半地址；
- 启动过程无隐式 GRUB 依赖。

## 22.2 中断和设备

- CPU 异常可识别；
- PIC 和 PIT 工作；
- 键盘可输入；
- VGA 和串口日志工作；
- ATA 能稳定读写测试区域。

## 22.3 内存

- 物理页分配和释放；
- 两级分页；
- 每进程独立地址空间；
- Ring 3 无法访问内核；
- 用户页故障不会击穿内核；
- 内核堆压力测试通过。

## 22.4 进程

- 至少三个用户进程可被抢占调度；
- `sleep`、`yield`、`exit`、`waitpid` 工作；
- 用户进程异常退出后系统继续运行；
- 无明显进程资源泄漏。

## 22.5 用户程序

- 从文件系统读取 ELF；
- 验证并加载 ELF；
- `argc/argv` 正确；
- `/bin/init` 启动 `/bin/sh`；
- Shell 能执行外部用户程序。

## 22.6 文件系统

- 格式化和挂载；
- 创建、打开、读取、写入、偏移、关闭；
- 文件删除；
- 目录创建和多级路径；
- 空间回收；
- 重启持久化；
- `fsck` 正常镜像通过；
- 明显损坏镜像被检测。

## 22.7 工程质量

- `make test` 通过；
- Linux CI 通过；
- 构建无未解释警告；
- 文档与实现一致；
- Git 历史可追踪；
- 来源登记完整；
- 从干净仓库可复现；
- Windows 主机未安装项目原生工具链，未修改 PATH、注册表或全局 Git 配置；
- 真实 Ubuntu 仅保留用户明确接受的容器运行时，不残留项目容器、镜像、卷或工具链；
- WSL 和 Ubuntu 环境创建、验证、备份、删除脚本均已实际演练；
- 环境删除不会影响其他 WSL 发行版、容器或项目。

---

# 23. 答辩演示脚本

建议顺序：

1. 展示仓库目录和构建命令；
2. `make clean && make image`；
3. 启动 QEMU，展示 Stage 1、Stage 2、保护模式和高半内核日志；
4. 展示 `/bin/init` 和 Ring 3 Shell；
5. 执行 `ps`，展示抢占调度；
6. 执行 `memtest`，证明不同进程地址空间；
7. 执行 `fault`，证明用户异常只终止当前进程；
8. 创建目录和文件：

```text
sh> mkdir /demo
sh> write /demo/hello.txt "MiniOrangeOS"
sh> cat /demo/hello.txt
MiniOrangeOS
```

9. 重启；
10. 再次读取 `/demo/hello.txt`，证明持久化；
11. 展示 ELF 加载器、页表、系统调用和 inode 核心代码；
12. 展示自动化测试和代码量报告；
13. 说明未实现范围和后续方向。

---

# 24. 答辩重点问题

必须能够回答：

1. BIOS 如何找到并加载 Boot Sector？
2. 为什么 Stage 1 只有 512 字节？
3. Loader 如何从实模式进入保护模式？
4. A20 为什么必须开启？
5. E820 的作用是什么？
6. ELF Program Header 和 Section Header 的用途有什么不同？
7. 高半内核的优点是什么？
8. 两级页表如何完成地址转换？
9. 用户页和内核页如何通过 U/S 位隔离？
10. CR3 在进程切换时如何使用？
11. TSS 的 `esp0` 为什么需要更新？
12. `int 0x80` 如何从 Ring 3 进入 Ring 0？
13. 为什么必须校验用户指针？
14. PIT 中断如何触发抢占调度？
15. PCB 中保存哪些上下文？
16. 为什么最低方案不实现 `fork`？
17. ELF 用户程序如何建立栈和 `argc/argv`？
18. inode 如何映射到数据块？
19. 删除文件时如何回收 inode 和数据块？
20. 如何证明重启后文件不是内存模拟？
21. 如何检测文件系统元数据损坏？
22. 哪些代码是自主设计的？
23. Codex 在项目中承担什么角色？
24. 如何验证 Codex 生成代码的正确性？
25. 项目最困难的 Bug 是什么，如何定位？

---

# 25. 风险与降级方案

降级只允许减少扩展能力，不得删除 A 类核心链路。

| 风险 | 优先处理 | 允许的降级 |
|---|---|---|
| 自写 Loader 不稳定 | 保留最小磁盘布局和串口日志 | 内核先按连续扇区加载，但仍由自写 Loader 完成 |
| 高半映射调试困难 | GDB 检查 CR3/PDE/PTE | 暂时保留低端 identity 映射，最终必须恢复高半 |
| Ring 3 三重故障 | 单独测试 GDT/TSS/iret | 先运行单个用户程序，再接调度 |
| ELF 加载复杂 | 使用静态 ET_EXEC | 不支持重定位、PIE 和动态链接 |
| 调度不稳定 | 先协作式再抢占式 | 不实现优先级，但必须保留抢占 |
| 文件系统进度不足 | 优先单级目录和文件持久化 | 多级目录可延后，但不能只做内存文件系统 |
| 文件系统损坏 | 加强 fsck 和只读挂载 | 不做日志，不做复杂缓存 |
| Windows Codex 无法直接操作 Linux 工具 | 通过 `wsl.exe` 进入专用发行版 | 不允许安装 Windows 专用工具链 |
| 工期紧张 | 停止扩展项 | 不做 fork、管道、缓存、实机启动 |
| WSL 与真实 Ubuntu 环境漂移 | Containerfile、版本锁定、环境指纹 | 不允许以手工安装未登记依赖修复 |
| 环境清理误删其他资源 | 项目标签、白名单删除、二次确认 | 禁止全局 prune 和无范围 rm |
| Bug 难定位 | 串口、GDB、最小复现 | 禁止以大量延时或关闭优化掩盖问题 |

### 25.1 功能收缩顺序

进度落后时，按以下顺序删除：

1. Bochs 和真实硬件验证；
2. 块缓存；
3. Shell 历史和高级编辑；
4. 文件系统截断增强；
5. 多级目录中的复杂边界增强；
6. `fork`；
7. 管道；
8. 扩展系统调用。

不得删除：

- 自写 Boot/Loader；
- Ring 3；
- 分页；
- 独立地址空间；
- ELF 用户程序加载；
- 抢占式调度；
- 控制台；
- 持久化文件读写。

---

# 26. 第一条 Codex 总提示词

开始项目时，把以下内容交给 Codex：

```text
你将协助从零实现 MiniOrangeOS，一个面向课程设计的 x86 32 位教学操作系统。

权威规划文件是 PROJECT_PLAN.md。先完整阅读该文件，不要立即写代码。
唯一权威工作树是 D:\DC\program-projects\OTHER\MiniOrangeOS，由 Windows 侧编辑文件并使用 Windows Git。
MiniOrangeOS-Dev 通过 /mnt/d/DC/program-projects/OTHER/MiniOrangeOS 访问同一工作树，
只执行 Linux 构建、QEMU、GDB 和测试，不运行 Git，不创建第二份活动工作树。Windows 不安装 GCC、NASM、Make、QEMU、GDB，
不修改 PATH、注册表或系统服务。真实 Ubuntu 复验使用 environment/Containerfile
创建的 rootless 容器，并通过 Linux CI 验证。

项目必须包含：
- 自写 BIOS Boot Sector 和二级 Loader；
- 保护模式和高半内核；
- x86 两级分页；
- 每进程独立地址空间；
- Ring 3；
- 抢占式时间片调度；
- int 0x80 系统调用；
- ELF32 用户程序加载；
- 用户态 init 和 Shell；
- ATA PIO；
- 自定义 inode 文件系统和重启持久化。

禁止：
- 复制 Orange’S、xv6、Minix 或其他操作系统源码；
- 使用 GRUB 替代自写启动；
- 使用宿主 libc；
- 跳过测试；
- 修改 main；
- 为适配 Windows 破坏 Linux 构建；
- 在 Windows 安装原生开发工具，或在 WSL 中运行 Git；
- 修改 Windows PATH、Linux 全局 Shell 配置、宿主 /usr/local；
- 使用无范围的容器 prune 或删除其他 WSL/容器资源；
- T72 建立 Linux CI 后跳过 CI 或在 CI 失败时声称完成。

现在只执行 T00：
1. 确认 Windows 权威工作树可由 MiniOrangeOS-Dev 通过固定 `/mnt/d` 路径访问，并在 WSL 中运行 environment/verify.sh（脚本尚未实现时记录为 T00 待办）；
2. 使用 Windows Git 检查当前仓库；
3. 创建 feature/T00-project-bootstrap；
4. 建立目录骨架、environment/ 结构和规范文件；
5. 不实现任何内核功能；
6. 检查 LF 行尾和忽略规则；
7. 更新 README 和 docs/environment.md 骨架；
8. 提交 Git；
9. 按计划书模板报告结果。
```

---

# 27. 项目完成定义

“能够启动”不是完成，“代码很多”也不是完成。本项目的完成定义是：

> 在专用 WSL2 Ubuntu 24.04 或真实 Ubuntu 24.04 的隔离容器中，从干净仓库一键构建自写启动链和 32 位内核；QEMU 启动后进入高半分页内核，运行由 ELF 文件加载的 Ring 3 用户程序，通过 `int 0x80` 使用内核服务；多个用户进程可被抢占调度并拥有相互隔离的地址空间；用户态 Shell 能通过自定义持久化文件系统创建、读写、删除文件和目录；用户非法访问只终止当前进程；重启后文件仍可读取；全部宿主测试、QEMU 测试、Linux CI、文档和自主实现证明完整通过；Windows 不存在项目原生工具链污染，真实 Ubuntu 不残留项目容器或工具链，并且两类开发环境均可通过项目脚本完整删除。

只有达到这一状态，才满足本计划对 A 类课程设计的目标。
