# P4 进程与系统调用阶段报告

阶段：P4 进程与系统调用

分支：`feature/P4-process-syscall`

提交：

- `99b490e`：`feat(proc): install ring3 segments and tss`
- `24743ba`：`feat(proc): switch cooperative kernel threads`
- `ef5af0e`：`feat(proc): preempt threads on pit ticks`
- `33bca13`：`docs(p4): record preemption regression`
- `a8f9f3d`：`feat(mm): activate user address spaces`
- `ed5a0f4`：`feat(proc): enter ring3 through int80`
- `3c03146`：`feat(proc): isolate user page faults`
- `12d1393`：`feat(proc): complete basic process lifecycle`
- `a9c2059`：`fix(mm): serialize heap operations against preemption`
- `8f6c678`：`test(proc): preempt three runnable threads`

合并提交：待完成。

## 修改文件

- `kernel/arch/x86/`：Ring 3/TSS、上下文切换、用户 `iret`、syscall/异常/IRQ 公共入口
- `kernel/proc/scheduler.c` 与公开头文件：PCB、PID、内核栈、抢占调度、sleep/waitpid、退出/回收与用户 #PF
- `kernel/mm/address_space.c`、`vmm.c`、`heap.c`：主内核 PDE 刷新、CR3 激活、权限收紧与 IRQ-safe Heap
- `kernel/core/syscall.c`、`kernel/include/minios/syscall.h`：`int 0x80` 约定和 7 个最小系统调用
- `kernel/core/kernel.c`：P4 初始化、自检与正式串口里程碑
- `Makefile`、`tests/host/test_boot_stage2.py`
- `PROJECT_PLAN.md`、`README.md` 与进程/内存/syscall/测试/进度/来源文档

## 关键实现

- GDT 增加 Ring 3 code/data 与 32-bit available TSS；TSS 提供 `ss0/esp0`，每次 PCB 切换同步目标内核栈顶。
- 16 项静态 PCB 表接管 PID 0 启动线程，其他进程使用 16 KiB Heap 内核栈；汇编保存 EBP/EBX/ESI/EDI/ESP，PIT 每 5 ticks 执行 round-robin。
- PID 在 1 到 `INT32_MAX` 单调分配，耗尽后扫描复用；状态机覆盖 READY/RUNNING/BLOCKED/ZOMBIE/REAPED，sleep 由 PIT deadline 唤醒，waitpid 负责父子阻塞、exit code 和资源回收。
- 保存主内核页目录物理地址；用户页目录创建/激活时刷新共享高半 PDE、保留自身递归项并排除工作窗口。调度切换同步 CR3，活动页权限变化重载 CR3 刷新 TLB。
- 原始内嵌测试程序使用只读代码页、单页用户栈和未映射保护页，通过 `iret` 进入 CPL3；P5 再由 ELF32 loader 替换此机制夹具。
- IDT vector `0x80` 使用 DPL3 interrupt gate，保存通用/段寄存器并向 C 暴露可修改 trap frame；实现 `exit/write/waitpid/getpid/yield/sleep/getticks`。
- usercopy 在 syscall 前逐页验证 U/S 与 R/W；Ring 3 负面自检覆盖未知调用号、非法 fd、内核边界指针、超长 write 和无子进程 wait。
- user #PF 仅在 U/S、CS CPL 与当前用户 PCB 一致时接管，以 `-EFAULT` 终止故障进程；kernel #PF 继续 panic。
- Heap 公开操作在单 CPU 下保存 EFLAGS 并关中断，完整保护 first-fit、拆分/合并和 PMM/VMM 扩展事务，再按原 IF 状态恢复。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/verify.sh
bash environment/with-env.sh make clean
bash environment/with-env.sh make -j4 image
python3 -m unittest tests.host.test_boot_stage2 -v
python3 -m unittest discover -s tests/host -v
```

结果：

- 环境验证：PASS；
- 干净交叉编译与镜像构建：PASS；
- P4 最终启动专项：28/28 PASS；
- 完整宿主回归：222/222 PASS，用时 393.027 秒；
- 三个无-yield 内核线程由真实 PIT 时间片依次运行，完整 `0b111` 标志后全部退出并回收栈；
- Ring 3 程序验证 syscall 正常/负面路径、sleep 跨越两个 ticks、用户页目录切换及退出回收；
- 真实 user #PF 读取 `0x0BADF000`，仅终止当前进程；独立 kernel #PF 仍输出 panic；
- 真实 `int3` panic 与 HMP `sendkey a` 回归继续 PASS；
- `kernel.elf`：47,600 bytes，SHA-256 `30be9c52a4a1d0bfa14a42b836bb236407946b352887aec722c7743be96a2aa4`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `515022f94036467060ccd2734e1d041ba95ad0292111aa94c4c061965bf079c7`。

## 未解决问题

- 当前用户程序是 P4 机制自检用的内嵌原始代码；静态 ELF32 用户 loader、crt0/libc、`/bin/init` 与 Shell 属于 P5。
- 进程表固定 16 项，未实现 `fork`；`spawn`、普通文件 fd 和 VFS 引用计数依赖 P5/P6 的 ELF/VFS。
- 当前 Heap 临界区适用于单 CPU 抢占；SMP 自旋锁和 Heap 收缩不在当前范围。
- `read/open/close/lseek/create/unlink/mkdir/readdir/spawn/sbrk/stat` 等 syscall 随 P5/P6 实现。
- 聚合入口 `make test` 仍按 P7 路线统一；本阶段使用上述现行入口提供完整证据。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、`README.md`、`docs/process.md`、`docs/memory.md`、`docs/syscall.md`、`docs/testing.md`、`docs/provenance.md`、`docs/progress.md` 和 `docs/review-notes.md`。
