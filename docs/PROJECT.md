# MiniOrangeOS 项目总览

本文是实现层面的总文档，描述当前代码已经具备的架构和接口。运行、安装与卸载见根目录 `README.md`；开发流程见 `docs/DEVELOPMENT.md`；历史证据见 `docs/HISTORY.md`。

## 目标与边界

MiniOrangeOS 用 C11 Freestanding 和 NASM 从零实现 x86 32 位教学操作系统，证明从 BIOS 启动到 Ring 3 用户程序、持久化文件系统和自动化验证的完整闭环：

```text
BIOS
  -> Stage 1 Boot Sector
  -> Stage 2 Loader
  -> A20 + E820 + protected mode
  -> ELF32 high-half kernel
  -> GDT/IDT/PIC/PIT/keyboard/ATA
  -> paging + PMM/VMM/Heap
  -> process + Ring 3 + int 0x80
  -> MiniFS + VFS
  -> /bin/init -> /bin/sh
  -> create/read file -> reboot -> read persisted file
```

最低版本有意排除 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接、Swap、`fork`、管道、完整 POSIX、权限系统、文件系统日志和复杂 Shell。

## 技术基线

| 类别 | 当前实现 |
|---|---|
| CPU | i686 目标，x86 32 位 |
| 启动 | BIOS Legacy，自写 Stage 1 + Stage 2 |
| 内核 | ELF32 `ET_EXEC`，高半起始 `0xC0000000` |
| 语言 | C11 Freestanding + NASM Intel 语法 |
| 构建 | GNU Make、`i686-elf-gcc`、`i686-elf-ld` |
| 模拟调试 | QEMU `qemu-system-i386`、GDB remote |
| 内存 | E820、4 KiB 页、两级页表、bitmap PMM、first-fit Heap |
| 进程 | 独立页目录、TSS、Ring 3、PIT 抢占式轮转 |
| 系统调用 | `int 0x80`，18 个调用 |
| 存储 | primary master ATA PIO LBA28、512-byte sector |
| 文件系统 | 4 KiB block、自定义 inode MiniFS、VFS/fd |
| 用户态 | 静态 ELF32，`/bin/init` 拉起 `/bin/sh` |

## 目录结构

```text
MiniOrangeOS/
├── boot/                 Stage 1、Stage 2 与 Boot Info ABI
├── config/               磁盘镜像唯一布局配置
├── include/minios/abi/   内核与用户态共享 ABI
├── kernel/
│   ├── arch/x86/         入口、GDT、IDT、异常、IRQ、上下文切换
│   ├── block/            4 KiB 块设备层
│   ├── core/             初始化、控制台、panic、syscall 分发
│   ├── drivers/          ATA、PIC、PIT、PS/2、COM1、VGA
│   ├── fs/               MiniFS 与 VFS
│   ├── mm/               PMM、VMM、Heap、地址空间、usercopy
│   ├── proc/             ELF loader、程序注册表、调度器
│   └── include/          内核私有公开接口
├── user/                 crt0、最小 libc、linker script 与 12 个程序
├── tools/                构建守卫、镜像、MiniFS、QEMU、LOC 工具
├── tests/                宿主合同、运行时与 QEMU 测试
├── environment/          WSL、工具链、OCI 环境生命周期
├── docs/                 总览、开发和历史文档
└── Makefile              唯一公共构建入口
```

模块依赖保持单向：用户程序通过 syscall 进入内核；VFS 调用 MiniFS，MiniFS 调用 block，block 调用 ATA。文件系统代码不直接访问 ATA 端口，用户 ABI 不暴露内核私有结构。

## 启动链

### Stage 1

`boot/stage1/boot.asm` 严格限制为 512 bytes，末尾签名为 `55 AA`。BIOS 将其加载到 `0x0000:0x7C00`。Stage 1：

1. 关闭中断并规范化 `CS`；
2. 初始化段寄存器、栈和方向标志；
3. 保存 BIOS 传入的启动盘号 `DL`；
4. 检查 INT 13h Extensions；
5. 用两个 DAP 读取 Stage 2，避免跨越 64 KiB DMA 边界；
6. 保持 `DS=ES=SS=0`、`SP=0x7C00`、`DF=IF=0`，跳转到 `0000:8000`。

Stage 1 只负责最小加载，不包含文件系统、ELF 或分页逻辑。

### Stage 2

Stage 2 实模式入口位于物理 `0x8000`，主要内存约定：

| 区域 | 地址 |
|---|---|
| Loader 保留区 | `0x00008000-0x00017FFF` |
| 实模式栈 | `SS=0`、`SP=0x7000`，向下增长 |
| E820 缓冲 | `0x00018000-0x00018BFF`，最多 128 × 24 bytes |
| Boot Info | `0x00019000-0x0001903F` |
| ATA/ELF 临时缓冲 | `0x00020000` 起 |
| 内核物理加载 | `0x00100000` 起 |

Stage 2 先验证 A20；未开启时依次尝试 BIOS `INT 15h/AX=2401h` 和 Fast A20 端口 `0x92`。随后采集 E820，过滤零长度和无效项，检查溢出，并让非 type 1 保留区优先于重叠 usable 条目。

临时 GDT 提供平坦 32 位代码/数据段。设置 `CR0.PE` 并远跳后，Loader 用 primary master ATA PIO LBA28 读取 Kernel ELF。它只接受 ELF32、little-endian、`EM_386`、`ET_EXEC`、固定物理加载和 `p_vaddr-p_paddr=0xC0000000` 的 `PT_LOAD`，并拒绝 header 越界、`filesz > memsz`、地址溢出、段重叠、覆盖 Loader、目标不在 E820 usable 区等输入。

Boot Info 固定 64 bytes，包含 magic/version/size/checksum、启动盘、虚拟与物理入口、内核物理范围、E820 缓冲、Loader 保留范围和 Kernel LBA。跳转物理入口时 `EAX=0x534F494D`，`EBX=0x00019000`。

## 内核初始化

分页前汇编入口只使用位置无关路径校验 Boot Info，建立低端 0-4 MiB 恒等映射和 `0xC0000000` 高半别名，加载 CR3、设置 `CR0.PG` 后跳到高半入口。页目录、页表和 16 KiB 启动栈位于独立 NOBITS 启动区，不参与 `.bss` 清零。

进入 C 后的稳定顺序：

1. COM1 与 VGA 控制台；
2. Ring 0/Ring 3 GDT 和 TSS；
3. 256 项 IDT 与 CPU 异常；
4. 基于 E820 的 PMM；
5. 正式 VMM 与 CR0.WP；
6. 内核 Heap；
7. PIC、PIT、PS/2 键盘；
8. ATA 与 block device；
9. 挂载 MiniFS、初始化 VFS；
10. 初始化 PCB/调度器；
11. 从 `/bin/init` 加载首个用户进程；
12. 开启中断并进入调度。

串口是测试和调试的权威输出，VGA 用于交互显示。日志前缀包括 `[BOOT]`、`[KERN]`、`[MM]`、`[PROC]`、`[SYS]`、`[FS]`、`[DRV]`、`[TEST]` 和 `[PANIC]`。

## 中断与设备

- GDT 包含 Ring 0/3 code/data 与 32-bit available TSS；每次进程切换更新 `esp0`。
- IDT 有 256 个槽位；前 32 个异常入口统一 CPU 自动错误码和软件补零后的 trap frame。
- 8259 master/slave 重映射到 `0x20/0x28`，驱动就绪后逐项解除屏蔽。
- PIT channel 0 使用 mode 3、100 Hz，负责 tick、sleep 唤醒和抢占。
- PS/2 初始化执行控制器/端口自检、set-1 translation 和 scanning ACK；IRQ1 将 ASCII 写入 64-byte 环形缓冲。
- COM1 采用有界轮询；VGA 使用 text mode。panic 关闭中断、输出上下文并进入 `hlt` 循环。
- ATA 驱动支持 IDENTIFY、多扇区读写、BSY/DRQ/ERR/DF、超时、容量检查和 cache flush。

## 内存管理

地址空间分界：

```text
user   0x00000000-0xBFFFFFFF
kernel 0xC0000000-0xFFFFFFFF
```

PMM 用两张覆盖 4 GiB 的 bitmap 区分当前占用和永久可分配资格。E820 usable 页先释放，reserved 后覆盖；低端 1 MiB、Loader、Boot Info、内核、页表和 MMIO 始终保留。分配返回最低可用 4 KiB 物理页，释放拒绝未对齐、保留或重复页。

VMM 使用 x86 两级 4 KiB 页表与 PDE 1023 递归映射。正式接管后移除普通低端恒等映射，按链接段收紧 text/rodata 权限并启用 CR0.WP。缺失页表通过受控 scratch 映射清零后发布；解除最后一个 PTE 时回收动态页表。

Kernel Heap 从 `0xD1000000` 开始，最大 16 MiB，使用 8-byte 对齐 first-fit、拆分和前后合并，按页扩展并在失败时回滚。单 CPU 抢占环境下，公开 Heap 操作保存 EFLAGS 并在完整元数据事务中关中断。

每个用户进程有独立页目录，高半内核 PDE 从主内核页目录刷新。用户 text 只读，data/stack 可写，栈下方保留未映射 guard page。x86 32 位最低实现没有 NX。

`validate_user_range`、`copy_from_user`、`copy_to_user` 和 `copy_user_string` 对每一页检查 present、U/S 和写权限。字符串逐字节验证到 NUL，允许合法终止于 `0xBFFFFFFF`；非法输入返回 `-EFAULT`。

## 进程与用户态

进程表固定 16 项，PCB 保存 PID、状态、上下文、16 KiB 内核栈、用户页目录、父子关系、退出码、wake tick、时间片和 16 项 fd 表。状态流为：

```text
NEW -> READY -> RUNNING -> READY/BLOCKED/ZOMBIE -> REAPED
```

PIT 时间片轮转可抢占不主动 `yield` 的线程。上下文切换保存 callee-saved 寄存器和 ESP，切换 CR3、TSS `esp0` 与内核栈。`sleep` 使用回绕安全 deadline；`waitpid` 支持指定子进程和 `-1`，父进程读取 ZOMBIE 退出码后负责回收。

首次进入用户态时构造 `SS:ESP/EFLAGS/CS:EIP` 并执行 `iret`。用户 page fault 只有在 error code U/S、`CS.RPL` 与当前用户 PCB 一致时才终止当前进程；内核 page fault 始终 panic。

用户 ELF loader 只接受静态 ELF32 `ET_EXEC`，先完整验证所有 Header/Program Header，再分配用户页、复制 `PT_LOAD`、清零 BSS、应用页级权限并构造 `argc/argv` 栈。`spawn` 从 VFS 读取磁盘 `/bin/*.elf`；内嵌的 6 个基础 ELF 仅用于迁移一致性自检，不参与运行时路径解析。

Shell 提供 128-byte 行缓冲、最多 16 项 argv、空格/Tab 分词、`/bin/` 补全和前台 spawn/wait。因没有 cwd syscall，`cd`/`pwd` 当前只承认根目录。

## 系统调用 ABI

系统调用通过 `int 0x80`：`EAX` 为调用号/返回值，`EBX`、`ECX`、`EDX`、`ESI`、`EDI` 为最多五个参数；成功返回非负值，失败返回负错误码。

| 编号 | 名称 | 主要语义 |
|---:|---|---|
| 0 | `exit` | 退出当前进程，不返回 |
| 1 | `write` | 控制台或普通文件写入 |
| 2 | `read` | 键盘或普通文件读取 |
| 3 | `open` | 打开文件/目录，支持受限 flags |
| 4 | `close` | 关闭 fd |
| 5 | `lseek` | 调整普通文件 offset |
| 6 | `create` | 创建普通文件 |
| 7 | `unlink` | 删除文件或空目录 |
| 8 | `mkdir` | 创建目录 |
| 9 | `readdir` | 返回共享 68-byte dirent |
| 10 | `spawn` | 从路径加载 ELF 并创建子进程 |
| 11 | `waitpid` | 等待直接子进程 |
| 12 | `getpid` | 返回 PID |
| 13 | `yield` | 主动让出 CPU |
| 14 | `sleep` | 按 PIT tick 阻塞 |
| 15 | 未分配 | 当前共享 ABI 保留该编号空缺 |
| 16 | `stat` | 查询路径元信息 |
| 17 | `getticks` | 返回 tick 低 32 位 |
| 18 | `ps` | 复制定长进程快照 |

每个进程的 fd 0/1/2 保留给键盘输入、控制台输出和错误输出；普通文件从 fd 3 开始。全局 VFS 有 32 项 file object 池，每个对象保存 backend、inode、独立 offset、flags、refcount 和 ops。普通 fd 不跨 spawn 继承；进程 exit/fault 会关闭全部普通 fd。

稳定错误包括 `EINVAL`、`ENOENT`、`EEXIST`、`ENOMEM`、`ENOSPC`、`EIO`、`EFAULT`、`EBADF`、`ENOTDIR`、`EISDIR`、`ENOTEMPTY`、`EBUSY` 和 `ECHILD`。用户输入错误返回负错误码或终止当前进程；只有内核不变量破坏才 panic。

## 磁盘与 MiniFS

`config/image-layout.json` 是 Boot、Loader、Kernel、MiniFS、镜像工具和测试共用的唯一布局来源。当前 64 MiB 镜像中 MiniFS 从 LBA 2048（1 MiB）开始，到镜像末尾共 16128 个 4 KiB block。

MiniFS Superblock 位于卷 block 0，使用 magic `MFS1`、version 1 和完整 4096-byte IEEE CRC32。卷包含 block bitmap、inode bitmap、1024 个 64-byte inode、64-byte 磁盘目录项和数据区。bitmap 为 LSB-first，超出容量的尾部 bit 置 1。

每个 inode 包含 mode、link count、size、10 个 direct block、1 个一级 indirect block、created/modified tick。目录项包含 little-endian inode、type 和 NUL 结尾的 59-byte name 区域；有效名称最长 58 bytes。目录包含 `.`、`..`，路径解析支持绝对路径、重复 `/`、`.`、`..`、尾随 `/` 和多级目录。

文件支持创建、读取、覆盖、无稀疏扩展、direct/indirect 跨界和缩小截断。目录支持空洞复用、跨块扩展、link count、空目录删除和稳定迭代。删除根目录、非空目录或仍打开 inode 会失败。

无日志写入按“分配资源 -> 写数据/indirect -> 提交 inode -> 发布目录项”的顺序缩小不一致窗口，并在单次 I/O 失败时尽力逆序回滚，但不承诺掉电事务原子性。

宿主工具：

- `tools/mkfs.py`：确定性创建卷并导入 12 个用户 ELF；
- `tools/fsck.py`：只读检查 CRC、几何、bitmap、inode、目录、重复块和孤儿 inode；
- `tools/make_image.py`：按统一布局原子装配完整磁盘；
- `tools/demo_persistence.py`：用临时镜像完成两次 QEMU 启动与逐轮 fsck。

## 构建安全边界

所有产物进入 `BUILD_DIR`。`tools/build_dir_guard.py` 以仓库身份、构建目录身份和不可复制 marker 约束 prepare/clean；源码目录、仓库外目录、symlink、特殊文件和竞态替换均 fail closed。

镜像工具使用 nofollow dirfd、普通文件/单硬链接约束、分块 I/O 和同目录原子替换；失败不会覆盖已有镜像。QEMU runner 同样把镜像和日志绑定到已验证的构建目录 FD，并使用严格串口状态机、超时、debug-exit 状态和本次进程组清理。

## 已知限制

- 仅支持 BIOS Legacy、i686、primary master ATA LBA28 PIO；
- 单 CPU 抢占模型，不支持 SMP；
- MiniFS 无 journal、rename、链接、权限和崩溃原子性；
- 目录删除空洞可复用，但不会自动缩小尾部目录块；
- 进程表 16 项、用户栈固定一页，不支持 `fork`；
- console/keyboard 仍由 syscall 适配，不是统一 VFS file object；
- 普通 fd 不跨 spawn 继承，Shell 没有 cwd syscall；
- QEMU/CI 证据不等同于真实裸机验收。
