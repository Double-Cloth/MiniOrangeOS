# T10：512 字节 Boot Sector

任务：T10

分支：`feature/T10-boot-sector`

状态：**完成并合并**

Merge SHA：`789f18fcfbaafcc13691d8d170f90115eaa958b4`

## 实现摘要

- `boot/stage1/boot.asm` 首指令关闭中断，远跳规范化 `CS`，初始化段寄存器、栈与方向标志并保存 BIOS `DL`。
- COM1 使用有界轮询输出 `[S1] boot`、`[S1] loader loaded` 或磁盘错误，失败最终进入 `cli/hlt` 循环。
- 完整检查 EDD `AH=41`，再用两个独立 DAP 执行 `AH=42`：64 扇区到物理 `0x8000`，剩余 63 扇区到 `0x10000`；每次检查 CF 与 AH。
- `tools/generate_boot_layout.py` 从 `config/image-layout.json` 生成 NASM 常量，并以 T02 marker、严格 JSON、nofollow 目录 FD 和原子提交保护输入输出。
- 成功交接为 `CS:IP=0000:8000`、`DS=ES=SS=0`、`SP=7C00`、原始 `DL`、`DF=IF=0`。

## 验收证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 执行：

| 检查 | 结果 |
|---|---|
| T10 Stage 1 contract/runtime | 9/9 PASS |
| 全量 host unittest | 194/194 PASS |
| T03 QEMU contract/runtime | 35/35 PASS |
| Boot Sector | 512 bytes、末尾 `55 AA` |
| 真实 IDE handoff | 两条 S1 日志、寄存器 PASS、debug-exit 33 |
| 真实 floppy error | `[S1] disk error`、无 loader loaded、无残留进程 |

## 审查闭环

独立复审最终 Approved，Critical 0、Important 0。审查推动关闭了 `cli` 前中断窗口、64 KiB DMA 边界、E820 地址冲突、Stage 1 自报假绿、错误路径进程残留，以及布局生成器特殊文件、严格 JSON、路径竞态和源码副作用问题。

## 边界

T10 只保证 Stage 1 与交接合同。仓库中的正式 Stage 2 仍是占位代码，T11 才实现其 16 位实模式入口、日志和磁盘接口。
