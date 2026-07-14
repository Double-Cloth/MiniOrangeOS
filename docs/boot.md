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
| E820 缓冲 | `0x00018000` 起 |
| 临时读盘缓冲 | `0x00020000` 起 |
| 内核物理加载 | `0x00100000` 起 |

Stage 1 按镜像布局最多读取 127 个 Stage 2 扇区，实际数据范围可到
`0x00017DFF`；统一把 `0x00008000–0x00017FFF` 作为 Loader 保留区。该范围
以及 E820/临时缓冲都必须写入 Boot Info，后续 PMM 不得把这些页当作空闲页。

## Stage 2 实模式接口

T11 的入口固定为物理地址 `0x8000`，首先保存 Stage 1 通过 `DL` 交付的启动盘号，再初始化独立栈、`DS=ES=0` 和方向标志。当前公开接口为：

- `bios_write_char`：输入 `AL`，通过 `INT 10h/AH=0Eh` 输出字符；恢复所有通用寄存器和段寄存器，flags 未定义；
- `bios_disk_read_edd`：输入 `DS:SI` 指向 16-byte DAP，内部使用保存的启动盘号和 `INT 13h/AH=42h`；返回 BIOS 的 `CF/AH`，恢复 `BX/CX/DX/SI/DI/BP/DS/ES`。

T11 只建立实模式运行时和单次 BIOS 读盘边界，不提前实现 A20、E820、保护模式或内核 ELF 加载。

## A20 与保护模式

Stage 2 必须开启 A20，并验证 1 MiB 回绕不再发生。推荐顺序：

1. BIOS 快速 A20 方法。
2. 键盘控制器方法作为 fallback。
3. 内存别名测试确认开启成功。

保护模式切换步骤：

1. 构造临时 GDT，至少包含 null、32 位代码段、32 位数据段。
2. `lgdt` 加载 GDTR。
3. 设置 `CR0.PE`。
4. 远跳转刷新流水线。
5. 设置数据段寄存器。
6. 建立保护模式栈。

切换失败时无法可靠返回 BIOS，应通过串口或屏幕输出最近阶段码后停机。

## E820 Boot Info

Stage 2 使用 BIOS E820 获取内存布局。必须处理：

- BIOS 不支持 E820；
- 条目数量超过缓冲；
- 条目长度小于 20 字节；
- 可用区域重叠；
- 地址加长度溢出；
- 低端保留区不能视为空闲。

Boot Info 至少包含：

```text
magic
version
boot_drive
kernel_entry
kernel_physical_start
kernel_physical_end
e820_entry_count
e820_entries_physical
loader_reserved_start
loader_reserved_end
image_layout
checksum
```

Boot Info 必须放在内核能够 identity map 访问的位置，并在进入高半前完成校验。

## ELF32 内核加载

Stage 2 只支持：

- ELF32；
- little-endian；
- `EM_386`；
- `ET_EXEC`；
- `PT_LOAD`；
- 固定物理加载；
- 不处理动态链接和重定位。

必须拒绝：

- 魔数错误；
- class/data/machine/type 不匹配；
- Program Header 越界；
- `filesz > memsz`；
- 段地址或大小溢出；
- 段落加载目标覆盖 Loader、Boot Info 或 BIOS 保留区；
- 文件长度不足。

加载段时：

1. 读取 `filesz` 字节到目标物理地址。
2. 清零 `memsz - filesz`。
3. 对齐到页边界记录内核占用范围。
4. 保留入口地址。

## 镜像布局统一来源

Boot、Loader、Kernel、MiniFS 的 LBA 必须来自单一布局配置。后续可由 `tools/image_layout.*` 或生成头文件提供，但不得在以下位置重复写死不同常量：

- Stage 1 读 Stage 2 的 LBA；
- Stage 2 读 Kernel 的 LBA；
- mkfs 写入文件系统的 LBA；
- QEMU 测试脚本验证镜像布局。

文档约定：布局变更必须同步 `filesystem.md` 的磁盘布局章节。
