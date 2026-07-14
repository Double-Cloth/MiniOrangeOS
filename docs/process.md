# 进程、调度与用户态设计

> 覆盖阶段：P4 进程与系统调用、P5 用户态，并依赖 `memory.md` 和 `syscall.md`。

## 进程模型

最低支持：

- 内核线程；
- Ring 3 用户进程；
- 抢占式时间片轮转；
- `yield`；
- `sleep`；
- `exit`；
- `waitpid`；
- 父子关系；
- 僵尸回收；
- 用户进程异常退出。

最低不实现 `fork`。进程创建使用 `spawn(path, argv)`，避免引入写时复制或完整地址空间复制。

## PCB 契约

PCB 至少包含：

```text
pid
state
name[32]
cpu_context
kernel_stack_top
user_stack_top
page_directory
exit_code
parent_pid
wake_tick
time_slice
fd_table[MAX_FDS]
run_node
wait_node
```

实现要求：

- PID 单调分配，耗尽后可扫描复用已回收 PID；
- `name` 必须 NUL 结尾；
- 每个进程拥有独立内核栈；
- 用户进程拥有独立页目录；
- `fd_table` 由 VFS 引用计数管理；
- PCB 状态转换必须在关中断或调度锁保护下完成。

## 状态机

```mermaid
stateDiagram-v2
    [*] --> NEW
    NEW --> READY
    READY --> RUNNING
    RUNNING --> READY: yield / timeslice
    RUNNING --> BLOCKED: wait / sleep / I/O
    BLOCKED --> READY: event / tick
    RUNNING --> ZOMBIE: exit / fault
    ZOMBIE --> REAPED: parent waitpid
    REAPED --> [*]
```

禁止状态：

- `RUNNING` 进程同时在 run queue 中；
- `REAPED` 进程仍持有用户页；
- `ZOMBIE` 进程仍占用文件描述符引用；
- `BLOCKED` 进程没有唤醒条件。

## 上下文切换

内核线程切换保存通用寄存器、栈指针和返回地址。用户进程从中断或系统调用返回时，依赖中断帧恢复用户态寄存器。

当前 P4 协作式内核线程实现使用 16 项静态 PCB 表，slot 0 接管启动线程，其他线程从 Heap 获得 16 KiB 独立内核栈。汇编 `context_switch` 保存 EBP/EBX/ESI/EDI 与 ESP；首次栈返回到 C trampoline，既有线程则返回原 `scheduler_yield` 调用点。状态选择与切换在保存 EFLAGS 后关中断执行，每次切换同步 TSS `esp0`。三线程自检严格验证 `1,2,3,1,2,3` round-robin 轨迹、ZOMBIE 退出和所有栈块回收。

PIT IRQ0 在设备处理和 EOI 完成后调用调度 tick；时间片耗尽时把当前 RUNNING 线程转回 READY，并可在仍保留完整 IRQ 栈的情况下切到下一线程。抢占自检让线程 1 在不调用 `yield` 的忙等中等待线程 2，只有真实 PIT 抢占能运行线程 2 并解除忙等。PID 在有符号 syscall 返回范围内从 1 单调分配到 `INT32_MAX`，耗尽后扫描当前 PCB 表并复用已回收 PID；自检覆盖最大 PID 到扫描模式的转换。

`sleep(ticks)` 把当前进程置为 BLOCKED，并由 PIT 使用无符号回绕安全的 deadline 比较唤醒；0 ticks 退化为 yield，超过 `INT32_MAX` 的距离被拒绝。`waitpid(pid)` 只匹配直接子进程，支持正 PID 与 -1；活跃子进程使父进程 BLOCKED，子进程退出时唤醒匹配父进程，随后父进程读取 exit code 并把 ZOMBIE 的用户地址空间/内核栈回收到 REAPED/UNUSED。内核生命周期自检验证阻塞 wait、exit code、重复 wait 的 `-ECHILD` 和 PID 耗尽复用；Ring 3 自检以 `getticks` 验证 sleep 至少跨越两个真实 PIT tick，并验证无子进程 wait 返回 `-ECHILD`。

用户地址空间已具备主内核页目录刷新、CR3 激活、内核页目录恢复及页级 R/W 权限收紧 API。调度切换现在根据 PCB `page_directory` 激活目标用户页目录或主内核页目录，再更新 TSS `esp0` 和内核栈。首个内嵌 Ring 3 测试进程拥有只读代码页、单页用户栈与未映射保护页，通过首次内核 trampoline 构造 `iret` 帧；退出后由启动进程销毁用户页目录并回收独立内核栈。

切换进程时必须：

1. 选择下一个 READY 进程。
2. 保存当前上下文。
3. 如目标页目录不同，切换 CR3。
4. 更新 TSS `esp0` 为目标进程内核栈顶。
5. 切换内核栈。
6. 恢复目标上下文或中断帧。

## 抢占式调度

PIT 产生时钟 tick。每个 tick：

- 全局 tick 递增；
- 唤醒 `wake_tick <= current_tick` 的睡眠进程；
- 当前进程时间片递减；
- 时间片耗尽时标记需要调度；
- 中断返回前执行调度。

中断处理必须避免在不可重入区域直接切换。最低方案可使用 `need_resched` 标志，在中断尾部统一调度。

## Ring 3 进入路径

首次进入用户程序通过构造中断返回帧并执行 `iret`：

```text
SS=user_data_selector
ESP=user_stack_top
EFLAGS=IF=1
CS=user_code_selector
EIP=elf_entry
```

GDT 必须包含 Ring 3 code/data 描述符。TSS 必须提供 Ring 3 -> Ring 0 时使用的 `ss0` 和 `esp0`。

当前 P4 已由 `enter_user_mode` 构造 `SS:ESP/EFLAGS/CS:EIP` 并真实执行 `iret`；用户代码在 IF=1 的 Ring 3 中运行，系统调用或硬件中断依靠 TSS 切到该进程 16 KiB 内核栈。内嵌程序仅用于 P4 机制自检，P5 仍将以 ELF32 loader 替换原始代码页复制。

调度器在初始化时注册用户 page-fault handler。只有 error code U/S=1、trap frame CS 为 CPL3 且当前 PCB 拥有用户页目录时才接管；处理器记录 PID、CR2、error code 和 EIP，把退出码设为 `-EFAULT` 并将当前进程转为 ZOMBIE 后调度父进程。内核 #PF、无当前用户进程或来源不一致仍由异常层 panic。真实 Ring 3 自检读取未映射 `0x0BADF000`，确认仅回收故障进程且内核继续运行。

## ELF 用户程序加载

只支持静态 ELF32 `ET_EXEC`。加载器必须：

- 验证 ELF Header；
- 验证 Program Header 范围；
- 拒绝段覆盖内核空间；
- 拒绝 `filesz > memsz`；
- 为 `PT_LOAD` 段分配用户页；
- 复制文件内容并清零 BSS；
- 根据段权限设置页表位；
- 分配用户栈和保护页；
- 构造 `argc/argv`；
- 创建初始中断帧。

用户程序从 `/bin/init` 开始，`init` 拉起 `/bin/sh`。Shell 负责前台命令 spawn 和 waitpid。

## 用户程序最低集合

| 程序 | 功能 |
|---|---|
| `/bin/init` | 启动 Shell，必要时重启 Shell |
| `/bin/sh` | 命令输入、分词、内建命令、执行外部程序 |
| `/bin/echo` | 输出参数 |
| `/bin/ls` | 列目录 |
| `/bin/cat` | 输出文件 |
| `/bin/touch` | 创建空文件 |
| `/bin/write` | 写入或覆盖文件 |
| `/bin/mkdir` | 创建目录 |
| `/bin/rm` | 删除文件 |
| `/bin/ps` | 显示进程 |
| `/bin/memtest` | 验证地址空间隔离 |
| `/bin/fault` | 触发非法访问，验证异常隔离 |

Shell 最低内建：`help`、`clear`、`cd`、`pwd`。
