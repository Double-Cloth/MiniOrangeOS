# 启动链设计

> 覆盖阶段：P1 启动链。本文档定义 BIOS 到内核入口之前的实现细节。

## 启动链目标

启动链必须由项目自写，不使用 GRUB。最终流程：

```text
BIOS -> Stage 1 Boot Sector -> Stage 2 Loader -> ELF32 Kernel Entry
```

Stage 1 负责在 512 字节内把 Stage 2 读入内存并跳转；Stage 2 负责收集硬件信息、进入保护模式、读取并解析 ELF32 内核、准备 Boot Info、跳转到内核。

## Stage 1 契约

建议文件：

```text
boot/stage1/boot.asm
```

加载位置和限制：

- BIOS 加载到 `0x0000:0x7C00`。
- 代码、数据、分区兼容填充和签名总计 512 字节。
- 末尾必须为 `0x55 0xAA`。
- 必须保存 BIOS 传入的启动盘号 `DL`。
- 必须设置可预测的 `CS`、`DS`、`ES`、`SS` 和栈。

Stage 1 只做最低工作：

1. 关中断。
2. 建立实模式栈。
3. 保存启动盘号。
4. 使用 INT 13h 扩展读读取 Stage 2。
5. 检查 carry flag 和返回码。
6. 打印短错误码或停机。
7. 跳转到 Stage 2 入口。

禁止在 Stage 1 中实现复杂文件系统、ELF 解析或分页逻辑。

## Stage 2 内存约定

建议加载位置：

| 区域 | 地址 |
|---|---|
| Stage 2 镜像保留区 | `0x00008000–0x00017FFF` |
| Stage 2 实模式栈 | `SS=0x0000`、`SP=0x7000`，向下增长 |
| E820 缓冲 | `0x00018000–0x00018BFF`，128 项 × 24 字节 |
| Boot Info | `0x00019000–0x0001903F` |
| ATA 单扇区缓冲 | `0x00020000–0x000201FF` |
| ELF Header/Program Header 暂存 | `0x00020200` 起 |
| 内核物理加载 | `0x00100000` 起 |

Stage 1 按镜像布局最多读取 127 个 Stage 2 扇区，实际数据范围可到
`0x00017DFF`；统一把 `0x00008000–0x00017FFF` 作为 Loader 保留区。该范围
以及 E820/临时缓冲都必须写入 Boot Info，后续 PMM 不得把这些页当作空闲页。

## Stage 2 当前实现边界

历史 T11 将入口固定为物理地址 `0x8000`，首先保存 Stage 1 通过 `DL` 交付的启动盘号，再初始化独立栈、`DS=ES=0` 和方向标志。公开 BIOS 接口为：

- `bios_write_char`：输入 `AL`，通过 `INT 10h/AH=0Eh` 输出字符；恢复所有通用寄存器和段寄存器，flags 未定义；
- `bios_disk_read_edd`：输入 `DS:SI` 指向 16-byte DAP，内部使用保存的启动盘号和 `INT 13h/AH=42h`；返回 BIOS 的 `CF/AH`，恢复 `BX/CX/DX/SI/DI/BP/DS/ES`。

当前 P1 实现已经在上述实模式运行时之上完成 A20、E820、临时 GDT、保护模式、ATA PIO、ELF32 高半内核加载和 Boot Info 交接。内核入口在分页开启前以物理地址执行，使用位置无关的早期汇编校验 Boot Info 并输出 `[KERN] boot info valid`；正式高半分页入口属于 P2。

## A20 与保护模式

Stage 2 必须开启 A20，并验证 1 MiB 回绕不再发生。当前实现顺序：

1. 先用 `0x00000500` 与 `0x00100500` 别名测试确认是否已开启。
2. 尝试 BIOS `INT 15h/AX=2401h`，再次验证。
3. 尝试 Fast A20 端口 `0x92`，再次验证；仍失败则输出错误并停机。

保护模式切换步骤：

1. 构造临时 GDT，至少包含 null、32 位代码段、32 位数据段。
2. `lgdt` 加载 GDTR。
3. 设置 `CR0.PE`。
4. 远跳转刷新流水线。
5. 设置数据段寄存器。
6. 建立保护模式栈。

切换失败时无法可靠返回 BIOS，应通过串口或屏幕输出最近阶段码后停机。

## E820 Boot Info

Stage 2 使用 BIOS E820 获取内存布局。当前原始缓冲固定为 `0x00018000`，每项 24 字节，最多保留 128 项；零长度、ACPI 扩展属性无效的条目被忽略，地址加长度溢出会失败停机。Loader 不把 E820 当作通用分配器；装载内核段时要求目标完整包含在 type 1 可用区内，并拒绝与任何非 type 1 区域重叠，从而让保留区在重叠描述中优先。

- BIOS 不支持 E820；
- 条目数量超过缓冲；
- 条目长度小于 20 字节；
- 可用区域重叠；
- 地址加长度溢出；
- 低端保留区不能视为空闲。

Boot Info 固定为 64 字节，定义在 `boot/include/boot_info.inc`：

| 偏移 | 字段 | 含义 |
|---:|---|---|
| `0x00` | `magic` | `0x534F494D` |
| `0x04` | `version` | 当前为 1 |
| `0x08` | `size` | 当前为 64 |
| `0x0C` | `checksum` | 16 个 little-endian dword 相加为 0 |
| `0x10` | `boot_drive` | BIOS 启动盘号 |
| `0x14` | `kernel_entry` | ELF 高半虚拟入口 |
| `0x18` | `kernel_physical_entry` | 分页前物理入口 |
| `0x1C` | `kernel_physical_start` | 页对齐后的内核物理起点 |
| `0x20` | `kernel_physical_end` | 页对齐后的 exclusive 终点 |
| `0x24` | `e820_entry_count` | 有效原始条目数 |
| `0x28` | `e820_entries_physical` | 当前为 `0x00018000` |
| `0x2C` | `loader_reserved_start` | 当前为 `0x00008000` |
| `0x30` | `loader_reserved_end` | 当前为 `0x00018000` |
| `0x34` | `kernel_lba` | 生成布局中的 Kernel LBA |
| `0x38` | `kernel_max_sectors` | 生成布局中的 Kernel 区域上限 |
| `0x3C` | `reserved` | 必须为 0 |

跳转内核物理入口时，`EAX=BOOT_INFO_MAGIC`，`EBX=0x00019000`。内核早期入口在使用其他字段前校验 magic、version、size 和 checksum。

## ATA PIO 读取

Stage 2 当前只支持 BIOS `DL=0x80` 对应的 primary master IDE 盘，使用 ATA PIO LBA28、一次读取一个 512 字节扇区。状态轮询有固定上限，`BSY` 清除后要求 `DRQ`，并把 `ERR`/`DF` 或超时统一报告为 `[S2] ATA failure`。

Kernel 的 LBA 和最大扇区数由 `tools/generate_boot_layout.py` 从 `config/image-layout.json` 生成到唯一的 `image-layout.inc`，Stage 1 和 Stage 2 共同引用。任意 ELF 文件范围必须落在该最大区域内。

## ELF32 内核加载

Stage 2 只支持：

- ELF32；
- little-endian；
- `EM_386`；
- `ET_EXEC`；
- `PT_LOAD`；
- 固定物理加载；
- `p_vaddr - p_paddr = 0xC0000000` 的高半映射；
- 不处理动态链接和重定位。

必须拒绝：

- 魔数错误；
- class/data/machine/type 不匹配；
- Program Header 越界；
- `filesz > memsz`；
- 段地址或大小溢出；
- 段落加载目标覆盖 Loader、Boot Info 或 BIOS 保留区；
- 非空 `PT_LOAD` 物理范围乱序或互相重叠；
- 物理范围未完整落在 E820 type 1 区域，或与保留类型重叠；
- 文件长度不足。

加载段时：

1. 读取 `filesz` 字节到目标物理地址。
2. 清零 `memsz - filesz`。
3. 对齐到页边界记录内核占用范围。
4. 保留入口地址。

`e_entry` 必须位于唯一的可执行 `PT_LOAD` 中。Loader 将其翻译为物理入口，构造 Boot Info 后以 `EAX/EBX` 合同跳转。空的 `PT_LOAD` 被忽略。

## 镜像布局统一来源

Boot、Loader、Kernel、MiniFS 的 LBA 必须来自单一布局配置。当前 Stage 1/Stage 2 常量由 `tools/generate_boot_layout.py` 生成，不得在以下位置重复写死不同常量：

- Stage 1 读 Stage 2 的 LBA；
- Stage 2 读 Kernel 的 LBA；
- mkfs 写入文件系统的 LBA；
- QEMU 测试脚本验证镜像布局。

文档约定：布局变更必须同步 `filesystem.md` 的磁盘布局章节。
