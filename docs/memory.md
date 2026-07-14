# 内存管理设计

> 覆盖阶段：P2 内核基础、P3 内存管理，并与 P1 启动链相关。

## 地址空间目标

内核使用高半映射，起始虚拟地址：

```text
KERNEL_BASE = 0xC0000000
```

用户空间范围：

```text
0x00000000 - 0xBFFFFFFF
```

内核空间范围：

```text
0xC0000000 - 0xFFFFFFFF
```

用户页必须设置 `U/S=1`，内核页必须设置 `U/S=0`。系统调用、异常处理和中断入口不得直接信任用户地址。

## P2 早期分页

早期入口使用一个 4 KiB 页目录和一个 4 KiB 页表。PDE 0 与 PDE 768 指向同一页表，因此切换瞬间同时具备：

- `0x00000000-0x003FFFFF` 到同值物理地址的恒等映射，供现有指令流、Boot Info 和 Loader 栈短暂使用；
- `0xC0000000-0xC03FFFFF` 到物理 `0x00000000-0x003FFFFF` 的高半别名，覆盖位于物理 `0x00100000` 的内核。

页目录、页表和 16 KiB 启动栈分别放在 `.boot.paging` 与 `.boot.stack` NOBITS 区段，均不参与 `.bss` 清零。分页开启后必须跳到 `kernel_high_entry`，清零 `__bss_start` 到 `__bss_end`，切换高半启动栈，并验证预先污染的 `.bss` 探针已归零。早期映射全部为 supervisor 可读写；text/rodata 权限收紧及低端恒等映射回收属于 P3 正式 VMM 范围。

## 物理内存管理

PMM 只从 E820 type=usable 且不与保留区重叠的范围分配页。页大小固定为 4 KiB。

必须排除：

- `0x00000000-0x00000FFF`；
- BIOS 数据区；
- Boot Sector；
- Stage 2；
- E820 缓冲；
- Boot Info；
- 内核镜像；
- 初始页目录、页表和 PMM bitmap 本身；
- MMIO 和 BIOS 保留区；
- 超出 32 位物理寻址能力的区域。

PMM bitmap 不变量：

- bit=1 表示已占用，bit=0 表示可分配；
- 分配返回页对齐物理地址；
- 释放必须拒绝未分配页、非页对齐地址和保留页；
- 耗尽时返回 `-ENOMEM` 或空指针，不能 panic；
- 启动完成后输出总页数、可用页数、保留页数。

## 虚拟内存管理

x86 两级页表：

- PDE 覆盖 4 MiB；
- PTE 覆盖 4 KiB；
- 不使用 4 MiB 大页作为最低实现；
- 递归页表映射建议放在 `0xFFC00000`。

最低映射：

| 虚拟范围 | 映射 |
|---|---|
| 早期低端 identity | 启动和切换临时使用，最终按需保留最小范围 |
| `0xC0000000+kernel_phys` | 内核代码、数据、只读段 |
| 内核堆范围 | PMM 动态分配页 |
| 设备临时映射 | 按驱动需要显式建立 |
| 用户程序段 | 每进程独立页目录 |
| 用户栈 | 每进程独立，含保护页 |

权限规则：

- 内核 text 可读可执行，不可写；
- 内核 rodata 只读；
- 内核 data/bss 可读写；
- 用户 text 可读可执行，不可写；
- 用户 data/heap/stack 可读写，不可执行作为扩展，最低可不实现 NX；
- 页表修改必须刷新对应 TLB 或重载 CR3。

## 内核堆

最低使用 first-fit 空闲链表，并支持相邻空闲块合并。堆块头建议包含：

```text
size
is_free
prev
next
magic
```

堆实现要求：

- 分配结果至少按 8 字节对齐；
- `free(NULL)` 可直接返回；
- double free 必须被检测；
- 越界写导致 magic 损坏时 panic 或返回明确错误；
- 扩展堆时按页向 VMM 申请；
- 压力测试覆盖大量小块、碎片合并和耗尽路径。

## 用户地址空间

每个用户进程拥有独立页目录，高半内核映射共享。创建地址空间时：

1. 分配新页目录。
2. 复制或引用内核高半 PDE。
3. 建立用户 text/data/heap/stack。
4. 为用户栈下方保留不可访问保护页。
5. 记录用户堆起点和 break。

销毁进程时：

- 释放所有用户物理页；
- 释放用户页表页；
- 不释放共享内核页表；
- 清理文件描述符和内核栈；
- 输出资源回收调试计数。

## Usercopy 契约

系统调用只能通过 usercopy 访问用户内存。最低接口可设计为：

```text
copy_from_user(kernel_dst, user_src, len)
copy_to_user(user_dst, kernel_src, len)
copy_user_string(kernel_dst, user_src, max_len)
validate_user_range(user_ptr, len, access)
```

校验必须覆盖：

- 起始地址在用户空间；
- `ptr + len` 不溢出；
- 范围不跨越 `0xC0000000`；
- 每一页存在；
- 写入时页可写；
- 字符串必须在 `max_len` 内遇到 `NUL`。

非法用户指针返回 `-EFAULT`；若发生在用户态异常路径，可终止当前进程，不得导致内核 panic。
