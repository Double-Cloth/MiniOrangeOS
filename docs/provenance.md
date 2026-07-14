# 自主实现与来源登记

> 状态：持续登记；M0 外部来源与自主实现边界已核验。

## 原则

MiniOrangeOS 必须证明核心代码是自主实现。允许参考公开文档、CPU 手册、BIOS 资料、工具手册和教材概念；禁止复制教学操作系统源码后改名。

Codex 生成代码也必须被开发者审查和解释。答辩时需要说明：

- 参考了什么；
- 哪些代码由项目实现；
- 哪些行为通过测试证明；
- 哪些限制是有意取舍。

## 来源登记表

| 模块 | 实现方式 | 允许参考资料 | 是否包含外部代码 | 审查状态 |
|---|---|---|---|---|
| Project bootstrap | 自主建立工程规范与契约测试 | 项目计划、历史任务报告 | 否 | 规范与契约测试已建立，功能代码不适用 |
| T01 环境生命周期 | 自主实现路径、ownership、状态恢复和清理脚本 | PowerShell、WSL、Podman/Docker CLI 文档 | 否 | 真实 WSL2/Podman 与负面测试已验收 |
| i686-elf 工具链 | 自主实现下载校验、构建编排和深度自检；编译器本体为第三方 | GNU Binutils/GCC 官方源码与构建接口 | 是，仅固定上游源码 | Binutils/GCC/libgcc 版本、目标与 prefix 已实测 |
| Boot Sector | 从零实现实模式入口、串口、EDD 探测与双 DAP 读取 | BIOS/INT 13h 接口、x86 实模式规则 | 否 | T10 独立审查与真实 QEMU 成功/失败路径已验收 |
| Stage 2 Loader | 从零实现 16 位入口、A20/E820、临时 GDT、保护模式、ATA PIO、ELF32 装载和 Boot Info 交接 | BIOS、ATA、x86 实模式/保护模式与 ELF32 规范 | 否 | T11 已验收；P1 成功路径与损坏 ELF 负面路径已通过真实 QEMU |
| GDT/IDT/TSS | 从零实现 | Intel 手册 | 否 | Loader 临时 GDT、P2 Ring 0 GDT、256 项 IDT 与 32 个 CPU 异常入口已通过真实 QEMU；Ring 3 描述符与 TSS 待 P4 |
| Paging | 从零实现 | Intel 手册 | 否 | P2 早期分页及 P3 正式两级 VMM 已通过真实 QEMU；递归映射、4 KiB 动态页表、TLB 刷新、低端恒等映射回收与 CR0.WP 已验收 |
| Console/panic | 从零实现 | 16550 UART、VGA text mode 与 C varargs 接口 | 否 | P2 COM1/VGA 双输出、最小格式化和 panic 停机路径已构建；正式镜像格式化日志通过真实 QEMU |
| PIC/PIT/keyboard | 从零实现 | 8259、8254/PIT、PS/2 控制器接口 | 否 | P2 PIC/IRQ/PIT 与 PS/2 初始化、set-1 转换、环形输入缓冲均通过真实 QEMU；HMP `sendkey a` 验证 IRQ1/ASCII 全链路 |
| PMM/VMM/Heap | 从零实现 | E820 接口、x86 页表机制与分配算法概念 | 否 | P3 PMM 与正式 VMM 已完成真实分配、复用、映射冲突、读写、解除映射及空闲计数恢复自检；Heap 待完成 |
| Scheduler | 从零实现 | 操作系统教材概念 | 否 | 待实现 |
| Syscall | 从零实现 | x86 中断机制资料 | 否 | 待实现 |
| ELF Loader | 从零实现 ELF32 Header/Program Header 校验、分段读取、BSS 清零和入口翻译 | ELF 规范 | 否 | P1 Kernel ELF Loader 已通过高半成功路径及坏魔数、越界/重叠段负面测试 |
| ATA PIO | 从零实现有界轮询的 primary master LBA28 单扇区读取 | ATA 资料、QEMU 行为说明 | 否 | P1 Loader 通过真实 QEMU 读取 Kernel ELF；内核 ATA 驱动待 P6 |
| MiniFS | 自主设计 | 文件系统教材概念 | 否 | 待实现 |
| User libc | 从零实现最低封装 | C ABI 概念 | 否 | 待实现 |
| Test harness | 自主实现严格串口协议、QEMU/GDB 编排、超时与进程树清理 | QEMU/GDB 命令接口 | 否 | T03 独立审查和真实 WSL/QEMU/GDB 回归已验收 |

## 禁止计入自主核心代码

- 编译产物；
- 磁盘镜像；
- 自动生成表格；
- 第三方库；
- 复制的头文件；
- 大量重复测试数据；
- 由工具生成且未经审查的代码。

## 代码量报告要求

后续 `make loc` 必须至少区分：

- Boot/Loader 汇编；
- 内核 C；
- 内核汇编；
- 用户程序；
- 用户 libc；
- 工具；
- 测试；
- 文档；
- 自动生成文件；
- 第三方文件。

## 记录边界

`docs/provenance.md` 只登记参考来源、版本、用途和审查状态，用于证明自主实现边界。

每个里程碑的阅读、理解、问题修正和后续补课统一记录在 `docs/review-notes.md`，不在本文件重复追加，避免双写和内容漂移。

## T01 固定来源与实测指纹

| 资源 | 官方 URL / 镜像 | SHA-256 |
|---|---|---|
| Ubuntu WSL 24.04.4 | `https://releases.ubuntu.com/24.04/ubuntu-24.04.4-wsl-amd64.wsl` | `9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5` |
| Binutils 2.42 | `https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz` | `f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800` |
| GCC 13.2.0 | `https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz` | `e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da` |
| Ubuntu 容器基础镜像 | `ubuntu:noble-20260509.1` | `sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54` |

目标为 `i686-elf`，正式安装 prefix 为 `/home/minios/.local/share/miniorangeos-dev/toolchain`。实测 marker 的 `lock_fingerprint=07a384a549e114bdd2e990d042c9ac143fc1e9a0dbc60190e4acbd4be4c4cea5`；GCC 13.2.0、GNU ld 2.42 和 prefix 内 `libgcc.a` 均通过深度自检。锁的权威机器可读来源是 `environment/versions.env`，本文不替代该文件。
