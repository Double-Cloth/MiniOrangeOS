# T11：二级 Loader 实模式框架

任务：T11

分支：`feature/T11-stage2-real-mode`

状态：**完成并合并**

Merge SHA：`e02acfbfba3d610f4849e91ad6f4502ce34c9272`

## 实现摘要

- `boot/stage2/entry.asm` 改为 16 位实模式入口，固定加载/入口地址 `0x8000`，首先保存 BIOS `DL`，再建立 `SS=0`、`SP=0x7000` 的独立栈。
- Stage 2 独立初始化 COM1 并输出 `[S2] loader entered` 与 `[S2] boot drive=0x80`，随后停在 T11 边界。
- 导出 `stage2_boot_drive`、`bios_write_char` 和 `bios_disk_read_edd`；两个 BIOS wrapper 明确并保护调用约定，EDD 返回 `CF/AH`。
- `boot/stage2/linker.ld` 保证入口排序，并断言实模式代码和数据不越过 16 位绝对地址范围。
- 动态 QEMU fixture 直接链接正式 Stage 2 对象，实际调用两个 BIOS 接口并读取 LBA0，不复制产品 wrapper。

## 验收证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 执行：

| 检查 | 结果 |
|---|---|
| T11 Stage 2 contract/runtime | 8/8 PASS |
| 全量 host unittest | 202/202 PASS |
| PowerShell WSL lifecycle | 29/29 PASS |
| 环境、干净镜像、公开 QEMU 回归 | PASS |
| 正式启动链 | S1 两行后按序输出 S2 两行，启动盘号 `0x80` |
| BIOS API 动态 fixture | 寄存器/SP、CF/AH、LBA0 `55 AA` PASS |
| Stage 2 artifact | ELF32 i386 EXEC、entry `0x8000`、283 bytes |

独立复审最终 Approved，Critical 0、Important 0。

## 边界

T11 不实现 A20、E820、GDT、保护模式或内核加载；这些能力从 T12 开始按任务依赖继续实现。
