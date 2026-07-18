# MiniOrangeOS 开发历史

本文合并原项目计划、进度表、阶段报告、ADR、问题记录、审查心得、来源登记和发布证据。它保留有意义的开发过程，同时移除按任务散落、重复或已过期的旧文档。

## 历史阅读规则

- “PASS” 只表示当时在对应提交和环境真实执行通过，不自动证明后续提交仍通过；
- 产物大小、SHA-256、测试计数和耗时是阶段证据，不是长期稳定接口；
- 早期阶段报告中的“未实现”由后续阶段完成时，以后续记录为准；
- 当前实现与运行方式以 `docs/PROJECT.md` 和 `README.md` 为准。

## 核心工程决策

### Windows 工作树，WSL 只执行 Linux 工作负载

2026-07-13：确定了唯一工作树位于 Windows Git仓库目录，并且 Git 只由 Windows 执行。`MiniOrangeOS-Dev` 通过该目录动态映射的 `/mnt/<drive>/...` 路径访问同一份文件，只运行构建、QEMU、GDB 和测试。

2026-07-14：移除代码、测试和公开文档中与单台机器绑定的仓库绝对路径。WSL 脚本从自身位置解析仓库根并推导挂载路径；因 ownership 安全校验必须保持绝对形式的环境授权根集中到 `config/wsl.psd1`。

这样设计收益是没有双工作树同步分叉；代价是 DrvFS 性能、大小写、权限、rename 可见性和 inode 行为弱于 ext4。项目以 `.gitattributes`、metadata 挂载、构建身份、并行/增量测试和 Linux CI 管理这些差异，而不是静默复制第二份源码。

### T01 容器集成先在独立 WSL2 宿主完成

T01 使用独立 `MiniOrangeOS-Dev-Test-ContainerHost`、Ubuntu 24.04.4 WSL2 和 rootless Podman 4.9.3 验证容器生命周期，graphroot 位于发行版 ext4，`/mnt/d` 只提供只读 context。验收后通过精确 preview/confirm 注销测试发行版。

该证据只代表 Ubuntu 用户态 + Microsoft WSL2 内核，不冒充原生 Linux。P7 再由 GitHub `ubuntu-24.04` runner 补齐原生 Linux CI。

## 阶段总览

| 阶段 | 分支 | 合并提交 | 交付摘要 |
|---|---|---|---|
| T00 | `feature/T00-project-bootstrap` | `def1657` | 仓库骨架、规则、文档入口、文本与布局合同 |
| T01 | `feature/T01-environment-toolchain` | `c07fe81` | WSL/OCI 生命周期、固定 i686-elf 工具链、来源与清理边界 |
| T02 | `feature/T02-minimal-build-system` | `83323db` | 并行/增量 Make、构建目录守卫、原子镜像装配 |
| T03 | `feature/T03-qemu-test-framework` | `5577dc4` | 严格串口协议、QEMU/GDB、超时和进程树清理 |
| T10 | `feature/T10-boot-sector` | `789f18f` | 512-byte BIOS Stage 1 与真实交接/失败测试 |
| T11 | `feature/T11-stage2-real-mode` | `e02acfb` | 16-bit Stage 2 入口和 BIOS API |
| P1 | `feature/P1-boot-chain` | `d8fab7b` | A20、E820、保护模式、ATA、Kernel ELF、Boot Info |
| P2 | `feature/P2-kernel-interrupts` | `6a307e8` | 高半分页、控制台、GDT/IDT、异常、PIC/PIT/键盘 |
| P3 | `feature/P3-memory-management` | `54d7cf3` | PMM、VMM、Heap、用户地址空间、usercopy/page fault |
| P4 | `feature/P4-process-syscall` | `29a2c7d` | TSS/Ring 3、抢占调度、进程生命周期、基础 syscall |
| P5 | `feature/P5-user-shell` | `f4363cb` | 用户 ELF、crt/libc、init/Shell、诊断程序 |
| P6 | `feature/P6-minifs` | `7de8d07` | ATA/block、可写 MiniFS、VFS/fd、文件命令、持久化 |
| P7 | `feature/P7-release-ci-docs` | `12cb2c5` | 聚合测试、Linux CI、失败证据、演示、LOC、发布校准 |

## T00：工程基础

T00 建立目录骨架、MIT License、`.gitignore`、`.gitattributes`、README/贡献/编码/计划/风险/来源/ADR 文档和 11 项仓库合同测试。它没有增加 OS 功能代码，也没有安装工具链。

关键提交链：

- `3e3325b`：M0 foundation design；
- `74ee4e1`、`3acfd92`：执行计划与 RED 阶段修正；
- `72db53d`：仓库布局合同；
- `52ce96c`：目录骨架、策略、License 和计划入口；
- `e633a7b`、`64ae3fa`：工程规范与 Ubuntu 指引；
- `0a7b447`、`ebbeb0f`：权威文档、记录入口与 T01 环境边界；
- `f58447e`：收窄旧 T01 规则检查；
- `6bd73b4`：预合并验证与计划校正；
- `4781d0f`：统一提交格式，扩展 UTF-8/LF 与脚本合同；
- `f579299`：同步 11/11 测试；
- `def1657`：no-ff 合并。

验收：`ProjectLayoutTests` 11/11 PASS，受控文本 UTF-8/LF，项目 PATH 无污染。T00 使用当时的 Ubuntu WSL rootfs 来源；后续 T01 将固定来源升级到 `environment/versions.env` 当前值。

## T01：隔离环境与工具链

T01 固定 Ubuntu WSL、OCI base、Binutils 2.42 和 GCC 13.2.0 的来源与哈希，提供 WSL create/enter/backup/destroy、两阶段 bootstrap、临时 PATH 注入、环境验证和 rootless OCI create/run/destroy。

正式 `MiniOrangeOS-Dev` 首次成功 bootstrap 约 6 分 15 秒，紧接的幂等执行约 5 秒并报告 `toolchain_status=up-to-date`。工具安装到 `/home/minios/.local/share/miniorangeos-dev/toolchain`；GCC 13.2.0、GNU ld 2.42、`i686-elf` target、prefix 内 libgcc 和 ELF32 freestanding 编译均通过。

安全审查最初发现 6 个 Important，后续全部修复：

- stale/运行中容器、stop 后 auto-remove 和 ready 资源漂移可恢复清理；
- `enter.ps1 -Command` 实现单字符串 `bash -lc` 语义；
- source manifest 绑定完整树、mode、symlink、内容和 hardlink 拓扑；
- WSL 身份绑定 Lxss `Version=2` 与 root-owned identity，容器身份来自真实 runtime；
- package-state 使用 `openat`、`O_NOFOLLOW`、`O_CLOEXEC`、锁和同目录原子替换；
- handled signal 与 `SIGKILL` residue 有严格 schema 与下一次恢复路径。

正式发行版曾因缺少新 identity 按预期验证失败；随后用 `create.ps1 ... -SkipBootstrap` 补建缺失的 Linux 用户及其身份配置，未触发 apt/dpkg 或工具链重建，迁移后验证 PASS。

rootless Podman 实测：首次 create 42m48s，第二次幂等 3s，run/verify 3.645s，destroy 2s；默认 Podman images/containers/volumes 未变化。集成修复了过长 runroot、错误的 `image rmi` 子命令和 subuid overlay 无法由普通 `rm -rf` 清理的问题。

T01 曾生成 6,179,215,360-byte 正式 WSL 导出备份；仓库只保留事实摘要，没有提交 rootfs、VHDX、工具链或大型日志。

## T02：安全构建系统

T02 建立顶层 GNU Make：NASM Stage 1/2、C11 Freestanding Kernel、ELF/map/symbol/binary/depfile、并行和精确增量构建，产物统一放在可配置 `BUILD_DIR`。`config/image-layout.json` 成为 64 MiB raw image 的唯一布局来源。

核心安全实现：

- `build_dir_guard.py` 绑定仓库、构建目录与 marker identity；
- clean/distclean 拒绝源码、外部目录、symlink、复制 marker 和替换竞态；
- Make 原始变量在任何路径展开/配方执行前检查命令替换和控制字符；
- `make_image.py` 以 nofollow dirfd、普通文件/单硬链接、稀疏感知分块 I/O 和原子替换装配镜像；
- 写失败、信号、FIFO、hardlink 和目录替换不覆盖已有镜像。

初版曾存在危险 `BUILD_DIR=boot` 清理、空格路径、镜像 TOCTOU、全量内存加载和可覆盖守卫变量；独立审查推动全部闭环。

验收：build contract/runtime 25/25、全量宿主 149/149、PowerShell lifecycle 29/29，环境、clean、`make -j4 all`、image 和无重建增量检查 PASS。

## T03：QEMU/GDB 自动化

T03 增加 `run-serial`、`run-curses`、`debug`、`gdb`、`test-qemu`。`qemu_test.py` 不只解析 PASS 文本，还要求完整有序状态机、没有 FAIL、QEMU 真实退出和精确 debug-exit 状态。

进程清理只作用于本次 leader/PGID，并以 subreaper 回收容器中的双重 fork 后代；镜像和日志绑定已验证构建目录 FD，日志有大小上限并原子提交。

审查修复了局部 PASS 假成功、信号残留、PGID 复用、孤儿进程、非回环 GDB、路径替换和日志竞态。真实 `/mnt/d` 运行又暴露重挂载导致 `st_dev` 同步变化，以及 rename 后写 FD 未关闭时新名称暂不可见；marker 重基和提交逻辑据此加固。

验收：QEMU contract/runtime 35/35、全量宿主 185/185、PowerShell 29/29，真实串口、debug-exit 33 和 batch GDB 回环 PASS。

## T10-T11：BIOS 启动骨架

T10 实现完整 512-byte Stage 1。初版一次读取 127 sectors 会跨 64 KiB DMA 边界，最终改为 64+63 两个 DAP。真实交接 fixture 验证寄存器、标志和 debug-exit，floppy 路径验证磁盘错误和无残留进程。Stage 1 专项 9/9、宿主 194/194、既有 QEMU 35/35 PASS。

T11 将 Stage 2 固定为物理 `0x8000` 的 16-bit 实模式入口，建立独立栈，导出 `bios_write_char` 和 `bios_disk_read_edd`，并用直接链接正式对象的动态 QEMU fixture 调用 BIOS API。链接脚本断言入口和绝对地址不越过 16 位范围。Stage 2 专项 8/8、宿主 202/202、PowerShell 29/29 PASS。

重要经验：ELF32 链接容器不改变 CPU 当前位宽；BIOS wrapper 的可靠性必须通过调用约定、寄存器、flags 和真实调用验证，静态反汇编匹配不足以排除假绿。

## P1：完整启动链

提交：

- `414a5e7`：A20、E820、临时 GDT 和保护模式；
- `8bdb7be`：ATA PIO 加载高半 Kernel ELF；
- `1916ea5`：阶段文档；
- `d8fab7b`：no-ff 合并。

Stage 2 完成 E820 非 type 1 优先校验、ELF32 header/segment/范围/重叠验证、按 `p_paddr` 加载与 BSS 清零，构造 64-byte Boot Info，并以 `EAX/EBX` 交给分页前内核入口。

验收：启动专项 11/11、完整宿主 205/205。真实串口到达 protected mode、Kernel loaded `0xC0100000` 和 Boot Info valid；坏 magic、`filesz > memsz`、覆盖 Loader、段重叠均在进入内核前失败。

经验：高半 ELF 的分页前路径只能依赖相对寻址和显式物理指针；E820 重叠不能因为先找到 usable 条目就接受；布局生成必须同时服务 Stage 1、Stage 2、镜像和测试。

## P2：内核基础与中断

提交：`473ff53`、`558fd30`、`771d9fb`、`79a6df8`、`bc5f204`、`2927c89`、`714b36f`，合并 `6a307e8`。

实现低端/高半双映射与高半跳转、独立 NOBITS 页表/栈、`.bss` 清零探针、COM1/VGA 双输出、格式化、panic、正式 GDT、256 项 IDT、统一异常帧、PIC、100 Hz PIT 和 PS/2 set-1 键盘。

验收：启动专项 20/20、宿主 214/214。真实产品到达全部中断里程碑；独立 `int3` 输出 panic 上下文，HMP `sendkey a` 验证 IRQ1/ASCII 全链路。

经验：活动页表/栈不能放在会被当前代码清零的 `.bss`；COM1 panic 输出也必须有界；异常入口先归一化错误码；PIC 在 handler 就绪后才放开；PS/2 控制器与键盘扫描是两层状态机。

## P3：内存管理

提交：`be16dee`、`61ddc58`、`66a4c0f`、`4fc5db5`、`29c7a0b`，合并 `54d7cf3`。

实现覆盖 4 GiB 的 used/allocatable bitmap PMM、递归页表、低端映射回收、按段只读权限和 CR0.WP、16 MiB first-fit Kernel Heap、非当前用户地址空间、逐页 usercopy 与 page fault 来源分类。

验收：启动专项 25/25、宿主 219/219。真实 PMM/VMM/Heap/user memory 自检继续到 PIT；独立 kernel #PF、`int3` 和键盘回归 PASS。

经验：usable 页向内对齐，reserved 页向外对齐；新页表发布前必须经 scratch 映射清零；Boot Info 低地址指针在移除 PDE 0 前必须消费完；Heap 跨 PMM/VMM 扩展失败要逆序回滚；usercopy 必须检查范围内每页。

## P4：进程、Ring 3 与基础 syscall

提交：`99b490e`、`24743ba`、`ef5af0e`、`33bca13`、`a8f9f3d`、`ed5a0f4`、`3c03146`、`12d1393`、`a9c2059`、`8f6c678`、`89fbcee`，合并 `29a2c7d`。

实现 Ring 3 GDT/TSS、16 项 PCB、16 KiB 内核栈、汇编上下文切换、PIT 抢占、用户 CR3、`iret` 进入、`int 0x80`、用户 #PF 隔离、sleep/waitpid/PID 复用和单 CPU IRQ-safe Heap。

验收：启动专项 28/28、宿主 222/222。三个无 `yield` 线程由 PIT 轮转并回收；Ring 3 正常/负面 syscall、sleep、退出资源回收 PASS；用户 #PF 只终止当前进程，kernel #PF 仍 panic。

经验：每次切换前更新 TSS `esp0`；IRQ 内抢占必须保留完整中断调用链；PIC EOI 先于调度；用户页目录必须从主内核页目录刷新 PDE；syscall/IRQ/异常入口都需正确保存用户段；waitpid 由父进程在读取退出码后回收 ZOMBIE。

## P5：ELF 用户态与 Shell

提交：`3ba9d8a`、`43b2cc5`、`70ecdfe`、`f7d1264`、`ae44349`、`d9eeba7`，合并 `f4363cb`。

实现共享 ABI、静态用户 ELF 构建、严格 ELF loader、argc/argv 栈、crt0、最小 libc、init、Shell、echo、ps、memtest 和 fault。P5 先以只读内嵌 ELF 注册表过渡，保持 `spawn(path, argv)` 接口，以便 P6 无缝切到 VFS。

Shell 自动验收真实走分词、路径补全、spawn 和 wait，不直接打印伪造 PASS。DrvFS 新建目录曾短暂报告 inode 0，构建守卫最终通过关闭创建句柄、从 parent dirfd 重绑并要求稳定非零 identity 解决。

验收：启动专项 28/28、宿主 225/225。真实 QEMU 完成 echo、Shell command、ps、memtest、fault isolation、init 和 ELF user process PASS。

## P6：ATA、MiniFS、VFS 与文件命令

提交：

- `be6d134`：ATA/block；
- `864eb2d`：确定性 MiniFS 镜像；
- `19c87c5`：内核挂载与只读；
- `44f90b7`：可写文件与持久化；
- `1f6617b`：VFS、fd 与文件 syscall；
- `0552a8f`：可变目录；
- `64fb8b9`：用户文件命令；
- `7de8d07`：no-ff 合并。

实现 primary master LBA28 PIO、4 KiB block、CRC32 Superblock、bitmap、inode、direct/indirect、目录、严格宿主 mkfs/fsck、VFS file object、每进程 fd 和磁盘 ELF spawn。新增 ls/cat/touch/write/mkdir/rm，Shell 完成创建、覆盖、读取、列举、删除和重启持久化。

专用双启动第一次创建 45,179-byte 跨 direct/indirect 文件和 65 个目录文件，第二次逐字节校验、截断、迭代和删除；两次启动后 fsck PASS。产品双启动由用户 `write` 创建 `/p6-command-persist`，第二次用 `cat` 验证。

验收：构建/MiniFS/启动组合 49/49、受影响构建专项 2/2、全量宿主 239/239，独立 image/test-image PASS。

经验：磁盘格式是宿主和内核共享 ABI；无日志仍需按数据、索引、inode、目录项顺序提交；目录空洞的查找/迭代/复用/fsck 语义必须一致；VFS object 与 fd 是两层引用；持久化测试必须等用户完成标记并在每轮后 fsck。

## P7：发布、CI 与最终证据

提交：

- `fb15888`：聚合入口、CI、LOC、演示；
- `f56de5a`：校准发布状态；
- `3daa1c1`、`dfb58ee`：保存 CI 失败证据与合同；
- `aa57ad9`：在 step 阶段解析 runner temp；
- `e7be5d0`：BuildKit 身份；
- `a36dca1`：补齐 package state helper；
- `60c6697`：以目标普通用户构建工具链；
- `cf2f06a`：来源清单合成隐式归档父目录；
- `69be0c2`：信任安全的非 root PID 1 procfs 事实；
- `72add84`：完成发布证据；
- `12cb2c5`：no-ff 合并。

P7 增加 `make check/test-host/test/loc/demo-persistence`，隔离递归 Make 状态、`BUILD_DIR` 和故障注入变量。CI 在固定 Ubuntu 容器中只读挂载 checkout、复制到短生命周期工作区、运行聚合测试，并在失败时导出完整输出、QEMU argv、串口日志、布局和哈希。

校准过程暴露并修复：

- job 级 `${{ runner.temp }}` 求值过早，改为 step 内 `$RUNNER_TEMP`；
- BuildKit 不保证 `/.dockerenv`，使用构建期可追踪 marker 并在最终层删除；
- Containerfile 遗漏 `package_state_writer.py`；
- 直接 `USER minios` 破坏 PID 1 身份预期，改为 root layer 中 `runuser`；
- Binutils tar 省略隐式父目录，manifest 确定性合成；
- 最终容器 PID 1 可合法属于普通用户，验证改为 procfs、owner 一致性、安全 mode、root-owned OCI marker 和 overlay/cgroup 联合证据。

每次真正进入 job 的失败运行都成功上传独立证据，因此修复依据来自对应 runner，而不是本地猜测。

最终 WSL：`make BUILD_DIR=.p7-aggregate test` 完成环境、构建、fsck 与 243/243 PASS，用时 898.861 秒；独立 release 构建、test-image、双启动 demo 和 LOC PASS。

最终原生 Linux CI：[GitHub Actions 29331275773](https://github.com/Double-Cloth/MiniOrangeOS/actions/runs/29331275773)，`ubuntu-24.04`，分支 HEAD `72add849f7ff5621e6404b62c232a826f7b5758c`。固定开发镜像构建 20m10s；环境验证 PASS；聚合 246/246 PASS、23 项平台限定测试跳过、用时 163.166s；完整 job 23m03s；成功路径失败 artifact 数量为 0。

最终产物：

| 产物 | 大小 | SHA-256 |
|---|---:|---|
| `kernel.elf` | 145,656 bytes | `2a0749ff4fb27289c79e1a9f75b186b7dcd66ac0b777a0177ad84734aa87873b` |
| `minifs.img` | 66,060,288 bytes | `79fe925f71552cf9b4fd47cedd99ef91b08a3bfc1d97ec0d5c301435156ead2b` |
| `miniorangeos.img` | 67,108,864 bytes | `3c55f18a0a4768d98e8d834a9f783c47adf7d77c88d9576d436f4f35bb0001fe` |

当时 `make loc` 统计 175 个文本文件、40,145 行、36,073 个非空行；自动生成与第三方类别均为 0。文档整理后文件数和文档行数自然变化，不应继续把该数字当作当前结果。

## 2026-07-15 命令可用性完善

目标：全面完善各种命令，使系统达到基本可用状态。开发分支为 `codex/complete-commands`。

本轮把原演示型命令层扩展为可持续交互使用的最小环境：

- 共享 ABI 增加 `chdir/getcwd`，PCB 保存规范绝对工作目录，spawn 子进程继承父进程目录；所有路径型系统调用统一支持绝对/相对路径、重复 `/`、`.` 与 `..`；
- Shell 行缓冲提升到 256 bytes，支持单引号、双引号、反斜杠转义、带工作目录的提示符、`cd/pwd`、`exit [status]`、明确的解析/启动/退出错误和输入溢出恢复；随后补齐退格/Delete/方向键/Home/End、8 项命令历史和 `Ctrl+A/E/C/D/K/L/U` 行编辑；
- `ls` 增加 `-a/-l` 与多路径，`cat/touch/mkdir/rm` 支持多操作数，`rm -f`、`echo -n`、`write -n` 可用，`ps` 显示可读进程状态；
- 新增 `cp`、`stat`、`sleep`、`uptime`，用户程序由 12 个增至 16 个，并全部进入 Make、MiniFS、产物、depfile 和真实 QEMU 自检合同；
- 新增最小用户 I/O 公共层，统一完整写入、整数格式化、错误文本与命令错误报告。
- PS/2 set-1 驱动补齐标点、`E0/E1` 扩展扫描码与独立左右 Shift/Ctrl 状态；共享按键 ABI 将特殊键交给用户态，VGA 同步支持硬件光标、退格与清屏序列。

验证：

- `make check` PASS，MiniFS 包含 16 个程序；
- 构建合同、MiniFS 工具与项目布局 28/28 PASS；
- 构建运行时 21/21 PASS，用时 409.905 秒；
- Boot/内核/正式 QEMU 33/33 PASS，用时 96.854 秒；
- 正式 WSL 聚合入口 `./environment/with-env.sh make test` 完成环境验证、镜像检查和 248/248 PASS，用时 615.2 秒；真实 QEMU 覆盖退格、Delete、左右/Home/End、命令历史、Ctrl+C 与标点输入。

本轮未引入外部代码或新依赖。`cp` 只复制普通文件；MiniFS 仍没有 rename，因此未伪装实现非原子的 `mv`。复杂 Shell 展开、管道、重定向、递归删除和完整 POSIX 继续属于明确边界。

## 2026-07-17 文件内容查看与行式编辑

目标：在不扩展 syscall ABI、不引入依赖的前提下，完善文件内容查看和修改能力。开发分支为 `feature/file-content-tools`。

本轮在既有 VFS/fd 能力上增加三组用户功能：

- `cat -n` 为一个或多个文件连续显示行号，并用 `--` 结束选项解析；跨文件且前一文件没有结尾换行时，下一文件内容保持在同一逻辑行；
- `write -a` 通过既有 `lseek(..., SEEK_END)` 实现追加写，支持与 `-n` 组合和 `--`，默认覆盖语义保持不变；
- 新增 32 KiB 行式 ASCII 文本编辑器 `edit`，提供范围打印、追加、插入、替换、删除、显式保存、未保存退出保护和 `q!` 明确丢弃；文件按 syscall 的 4 KiB 上限分块加载。

`edit --self-test` 在正式 Shell 启动自检中依次执行插入、替换、删除、追加、写盘、重读逐字节比对和临时文件清理；`cat -n` 与 `write -a` 也进入同一条 Ring 3 文件命令链。用户程序由 16 个增至 17 个，Make、MiniFS 导入、最终产物、depfile、宿主合同和 QEMU 断言同步更新。

验证：

- `MiniOrangeOS-Dev` 环境身份、固定 i686 工具链、NASM、QEMU、GDB、Python 和污染边界全部 PASS；
- 17 个用户 ELF 在正式 `i686-elf-gcc` 的 freestanding `-Werror` 规则下编译、链接和生成符号成功；
- `make check` 报告 MiniFS `files=17`，完整镜像 `fsck` 报告 `allocated_inodes=19 files=17 directories=2`；
- 构建合同与 MiniFS 工具专项 17/17 PASS；真实产品镜像专项 1/1 PASS，并观察到 `[USER] edit command PASS`；
- 无特殊字符的临时 DrvFS 副本中，公开聚合入口 `make test` 完成环境、镜像和 249/249 宿主/QEMU 测试，测试用时 584.212 秒，完整命令用时 592.2 秒。

本轮未修改 MiniFS 磁盘格式或 syscall 编号。`edit` 面向小型文本文件，不承诺二进制编辑或掉电原子保存；这些边界在项目总文档和用户说明中明确记录。

## 2026-07-18 特殊字符工作树隔离

目标：让唯一 Windows 工作树位于包含空格、`&`、`#`、`%`、`$`、引号、括号等合法字符的任意本地路径时，WSL 构建和测试仍保持稳定 argv、Make 与 Shell 语义。开发提交直接落在 `main`。

- `enter.ps1` 以 root 进入一次性私有 mount namespace，将自动推导的 DrvFS 源路径作为原始 argv 绑定到 `/run/miniorangeos-workspace`，随后通过 `runuser` 降权为 `minios`；源路径、runner 和用户命令不拼接成 root Shell 文本；
- PowerShell 生命周期脚本改用 `[IO.Path]::Combine` 和显式脚本文本加载，避免宿主路径字符被命令解析层重新解释；
- 构建守卫通过 `MINIOS_REPO_SOURCE/MINIOS_REPO_MOUNT` 将安全挂载路径映射回真实 DrvFS 身份，并要求两条路径指向同一目录，marker 因此继续约束真实仓库和构建目录；
- 文档、构建运行时合同和 WSL 生命周期测试覆盖重复调用、argv 边界及 Windows 合法特殊字符路径全集。

验证：

- 正式 `MiniOrangeOS-Dev` 聚合入口 `./environment/with-env.sh make test` 完成环境验证、交叉编译、镜像检查和 252/252 测试 PASS，测试用时 716.568 秒，完整命令用时 723.7 秒；
- Windows PowerShell WSL 生命周期回归 32/32 PASS，用时 14.4 秒，包含真实特殊字符工作树、稳定安全挂载路径和正式发行版 identity 验收。

本轮未创建第二份活动源码、未修改 Windows/Linux 全局配置，也未引入外部代码或新依赖。

## 2026-07-18 Shell 主动关机

目标：让交互 Shell 可主动结束官方 QEMU 运行实例，替代正常流程中从 Windows 侧执行 `wsl.exe --terminate MiniOrangeOS-Dev`。开发分支为 `codex/shutdown-command`。

- 共享 ABI 增加编号 20 的不返回 `shutdown` 系统调用，用户 libc 暴露 `minios_shutdown()`，Shell 增加无参数内建命令 `shutdown`；
- 内核 Power 驱动关闭中断、记录关机日志并向 QEMU `isa-debug-exit` 端口写入专用值 `0x2A`；缺少该设备时停在 `hlt`，不继续执行不确定状态；
- 交互 QEMU runner 挂载受限端口设备，并只把专用退出状态 85 归一化为成功，其他 QEMU 退出码保持失败；
- Shell 帮助、README、项目 ABI/限制说明、静态合同、runner 夹具和真实 PS/2 键盘 QEMU 验收同步更新。

验证：

- WSL 合同、QEMU 配置与项目布局专项 29/29 PASS；
- QEMU runner 状态隔离与正式镜像键盘关机专项 3/3 PASS，用时 19.482 秒；
- 正式 `MiniOrangeOS-Dev` 聚合入口 `./environment/with-env.sh make test` 完成环境验证、交叉编译、镜像检查和 252/252 测试 PASS，测试用时 716.568 秒，完整命令用时 723.7 秒。

本轮未引入外部代码或新依赖，未修改 MiniFS 磁盘格式。主动退出合同面向项目官方 QEMU runner；真实裸机 ACPI/APM 关机仍属于明确边界。

## 问题与经验

### 安全清理是产品能力

可配置输出目录、WSL、容器和下载缓存都可能造成越界删除。项目统一采用授权根、精确名称、preview + confirm、不可复制 identity、nofollow、稳定 inode/dirfd 和失败关闭；拒绝用全局 prune 或宽泛递归删除代替。

### 原子替换不是完整 TOCTOU 防护

原子 rename 只保护提交瞬间。输入组件、父目录、临时文件、最终 inode 和失败清理仍要绑定同一可信目录 FD，并在关键阶段复核 identity。

### 测试成功需要进程和协议双闭环

串口 PASS 文本不是充分条件。runner 还必须验证协议顺序、真实 debug-exit、超时、leader/PGID 身份和后代清理。持久化测试还需在用户完成标记后退出，并在每轮写入后运行宿主 fsck。

### x86 边界必须由真实 CPU 路径证明

分页、段切换、TSS、IRQ 栈、Ring 3 `iret`、`int 0x80` 和 page fault 很难只靠静态检查证明。项目用真实 QEMU fixture 和正式镜像同时覆盖成功/失败路径，并让 kernel fault 与 user fault 保持不同结果。

### 共享磁盘与用户 ABI 只能有一个来源

镜像几何、MiniFS 字段和 syscall/dirent 编号由机器可读配置或共享头定义。宿主工具、内核、用户程序和测试消费同一合同，防止两套手写常量漂移。

### 环境身份不能由调用者自证

WSL 身份绑定 Windows Lxss 注册事实与 Linux root-owned 文件；OCI 身份联合真实 procfs、overlay/cgroup 和 root-owned marker。可覆盖环境变量只可作为测试输入，不能成为生产信任根。

## 来源与自主实现登记

核心 OS、构建/安全工具、测试与 CI 编排由项目自主实现。允许参考公开规范和硬件/工具官方文档；没有复制教学 OS 源码。

| 模块 | 参考类别 | 外部代码 | 历史审查结果 |
|---|---|---|---|
| Boot/Loader | BIOS INT 13h、x86 实模式/保护模式、ATA、ELF32 | 否 | 真实成功/失败启动与 fixture 验收 |
| GDT/IDT/TSS/Paging | Intel 架构手册 | 否 | 真实异常、IRQ、Ring 3、kernel/user #PF 验收 |
| PIC/PIT/PS2/UART/VGA | 8259、8254、PS/2、16550、VGA 接口资料 | 否 | QEMU tick、按键与 panic 路径验收 |
| PMM/VMM/Heap/Scheduler | 教材算法概念与 x86 ABI | 否 | 自检、负面路径和资源回收验收 |
| Syscall/User ELF/libc | x86 interrupt、ELF、C ABI 概念 | 否 | Ring 3 正常/恶意参数验收 |
| MiniFS | 文件系统教材概念、CRC32 | 否 | 自主格式，mkfs/fsck/内核/双启动联合验收 |
| QEMU/GDB harness | QEMU/GDB CLI 官方接口 | 否 | 严格协议、进程清理和真实回环验收 |
| 工具链 | GNU Binutils/GCC 官方源码 | 是，仅固定上游源码 | 来源树 manifest 与目标工具深度自检 |
| Linux CI | GitHub Actions 与 Docker CLI | 是，仅固定官方 action/基础镜像 | 原生 Ubuntu runner 实际通过 |

固定外部输入：

| 资源 | URL / 镜像 | SHA-256 / digest |
|---|---|---|
| Ubuntu WSL 24.04.4 | `https://releases.ubuntu.com/24.04/ubuntu-24.04.4-wsl-amd64.wsl` | `9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5` |
| Binutils 2.42 | `https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz` | `f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800` |
| GCC 13.2.0 | `https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz` | `e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da` |
| OCI base | `ubuntu:noble-20260509.1` | `sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54` |
| `actions/checkout` | GitHub official action | commit `de0fac2e4500dabe0009e67214ff5f5447ce83dd` |
| `actions/upload-artifact` | GitHub official action | commit `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |

机器可读权威来源始终是 `environment/versions.env` 和 `.github/workflows/ci.yml`；本表用于历史解释，版本升级时应同步更新。

## 当前已知限制与后续方向

- QEMU/容器/CI 已验证，但尚无真实裸机验收；
- BIOS Legacy、i686、single CPU、primary master LBA28 PIO；
- MiniFS 无 journal 和掉电事务，不支持 rename、链接、权限；
- Shell 已支持 cwd；console/keyboard 尚未统一为 VFS object；
- 普通 fd 不跨 spawn 继承，进程表固定 16 项，用户栈固定一页；
- 不支持 x86_64、UEFI、SMP、网络、USB、GUI、动态链接和完整 POSIX；
- CI 首次构建固定工具链约需 20 分钟，当前为保持来源边界简单，没有引入额外缓存 action。

如继续开发，优先保持现有闭环与负面测试，再考虑真实硬件、目录回收、rename、VFS console、更多进程资源或更强文件系统一致性；不得以扩展功能为由削弱自写启动、Ring 3、分页、用户隔离、持久化和可审计测试这些核心链路。
