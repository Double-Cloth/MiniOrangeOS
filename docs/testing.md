# 测试策略与验收协议

> 覆盖阶段：P0 工程基础、P7 收尾，并约束所有功能阶段。

## 测试分层

| 层级 | 目标 | 运行方式 |
|---|---|---|
| 环境层 | 工具路径、版本、宿主污染、可删除性 | `environment/verify.sh` |
| 编译期 | 静态断言、结构大小、链接地址、未定义符号 | `make check` |
| 宿主单元测试 | 纯算法、解析器、bitmap、路径、mkfs/fsck | `make test-host` |
| QEMU 内核测试 | 中断、分页、堆、调度、Ring 3、syscall | `make test-qemu` |
| QEMU 用户测试 | ELF、usercopy、Shell、文件命令 | `make test-qemu` |
| QEMU 启动链测试 | A20、E820、保护模式、ATA、Kernel ELF、Boot Info | `make test-boot-qemu` |
| 镜像测试 | mkfs、fsck、持久化、损坏防护 | `make test-image` 或并入 `test-qemu` |
| CI | 干净 Linux 环境完整验证 | GitHub Actions |

最低总入口：

```text
make test
```

应依次执行环境检查、构建检查、宿主测试、QEMU 测试和镜像测试。

## 有效证据边界

只有以下 Linux 环境产生的构建和测试日志可作为 PASS 证据：

- 专用 `MiniOrangeOS-Dev` WSL2 发行版；
- 真实 Ubuntu 24.04 主机上的项目隔离容器；
- Linux CI runner。

T01 的容器集成在 `MiniOrangeOS-Dev-Test-ContainerHost`（**Ubuntu 24.04 WSL2**）使用 **rootless Podman** 4.9.3 实测固定镜像 create/run/destroy。内核为 `6.6.87.2-microsoft-standard-WSL2`，因此不是**原生 Linux 内核**证据；后续 **Linux CI** 必须补齐 namespace、cgroup、overlay 和 OCI runtime 差异。

Windows 原生命令只承担 Windows Git 和静态文件检查，不得作为 Linux 构建、QEMU、GDB 或测试通过的证据。Windows 发起 WSL 测试时使用固定工作树映射：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
<linux-test-command>
'
```

T01 回归入口还包括：

```powershell
powershell -NoProfile -File tests/host/test_wsl_lifecycle.ps1
```

```bash
python3 -m unittest discover -s tests/host -v
./environment/verify.sh
./environment/with-env.sh i686-elf-gcc --version
./environment/with-env.sh i686-elf-ld --version
./environment/ubuntu/run.sh ./environment/verify.sh
```

## T01 最终回归证据

2026-07-14 在 Windows 权威工作树对应的正式 `MiniOrangeOS-Dev` WSL2 中执行：

- `python3 -m unittest discover -s tests/host -v`：124/124 PASS；
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\host\test_wsl_lifecycle.ps1`：29/29 PASS；
- `./environment/verify.sh`：PASS，GCC 13.2.0、GNU ld 2.42、ELF32 freestanding compile、Windows/Linux 全局污染检查均通过。

身份加固合入后、identity-only 迁移前，正式发行版 `verify.sh` 按预期 FAIL；执行 `create.ps1 -DistroName MiniOrangeOS-Dev -AuthorizedRoot D:\ApplicationData\MiniOrangeOS -SkipBootstrap` 后恢复 PASS。该入口仍 provision/validate root-owned identity，但不运行 apt 或工具链；回归同时覆盖缺失/伪造 identity 拒绝，以及正式 identity 与精确 Lxss 注册事实绑定。

## T02 最终回归证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 中执行：

- T02 构建合同与运行时测试：25/25 PASS；
- 全量宿主测试：149/149 PASS；PowerShell 生命周期：29/29 PASS；
- `environment/verify.sh`、`make clean`、`make -j4 all`、第二次增量 `make -j4 all` 和 `make image`：PASS；
- 镜像为 67,108,864 bytes、mode `0644`，SHA-256 为 `6cf4f04e738ca014720b04b3ed192e0f526cc8162c9f19785cbdac9475923da2`；Kernel 为 ELF32 i386 EXEC。

## T03 最终回归证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 中执行：

- QEMU 合同与运行时测试：35/35 PASS；全量宿主测试：185/185 PASS；PowerShell 生命周期：29/29 PASS；
- `environment/verify.sh`、`make clean`、`make -j4 image`、公开 `make test-qemu QEMU_TIMEOUT=5`：PASS；
- 真实 QEMU debug-exit 返回 33，串口完整输出 suite/case/all PASS；真实 batch GDB 只连接 `127.0.0.1`；
- PASS、FAIL、协议乱序、超时、SIGINT/SIGTERM/SIGHUP、孤儿后代回收、日志/镜像替换竞态和 DrvFS 日志提交均有回归覆盖。

T03 使用专用固定 fixture 验证自动化框架，不把该结果表述为 T10 正式 Boot Sector 已完成。

## T10 最终回归证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 中执行：

- T10 Stage 1 合同与运行时测试：9/9 PASS；全量宿主测试：194/194 PASS；T03 QEMU 回归：35/35 PASS；
- Boot Sector 严格 512 bytes、末尾 `55 AA`，EDD 读取按 64+63 扇区拆分且不跨物理 64 KiB DMA 边界；
- 真实 IDE 镜像由 16 位 Stage 2 fixture 验证 `CS/DS/ES/SS/SP/DL/DF/IF` 后输出完整测试协议并以 debug-exit 33 退出；
- 真实 floppy 缺失 Loader 时输出 `[S1] disk error`、不输出 `loader loaded`，并由 T03 runner 超时清理；
- 布局生成器的严格 JSON、特殊文件、失败保留旧输出和增量依赖均有回归覆盖。

## T11 最终回归证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 中执行：

- T11 Stage 2 合同与运行时测试：8/8 PASS；全量宿主测试：202/202 PASS；PowerShell 生命周期：29/29 PASS；
- `environment/verify.sh`、干净 `make -j4 image` 与公开 `make test-qemu QEMU_TIMEOUT=5`：PASS；
- 正式镜像按顺序输出两条 S1 与两条 S2 日志，并保留 BIOS 启动盘号 `0x80`；
- 动态 QEMU fixture 直接链接正式 BIOS wrapper，验证字符接口寄存器/栈合同、EDD `CF/AH`、保留寄存器及 LBA0 `55 AA`；
- `stage2.bin` 为 283 bytes，SHA-256 为 `db4cfa3c59e3a1ef624b1774f98f7be5f0c7f26214ddf48f128b03c8c668cfe4`。

该节只保留历史 T11 边界；P1 完成证据记录在 `docs/task-reports/P1-boot-chain.md`，不回写覆盖历史产物指纹。

## P2 进行中证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 中完成首个 P2 增量验证：

- 早期分页源码合同覆盖页目录、页表、CR3、CR0.PG、高半入口与 `.bss` 清零；
- Kernel ELF 保持两个 `PT_LOAD` 段，虚拟地址与物理地址差为 `0xC0000000`；`.boot.paging`、`.boot.stack` 和 `.bss` 均为 NOBITS；
- `environment/verify.sh`：PASS；全量宿主测试：206/206 PASS；
- 干净 `make image` 与 `make test-boot-qemu QEMU_TIMEOUT=5`：PASS，启动专项 12/12；真实镜像按序输出 `[KERN] boot info valid`、`[KERN] paging enabled`、`[KERN] bss cleared`，P1 损坏 ELF 负面路径无回退；
- Kernel ELF 为 10,000 bytes，SHA-256 为 `ad04e3ef94ce989740c7adaeb4c08bdafc51c25db183557b71890d5e746b775a`；镜像为 67,108,864 bytes，SHA-256 为 `28c141a60e252110a735603d650773bc306cc686dd3db785523914fcc4050aa5`。

同日完成第二个 P2 增量的定向验证：

- COM1、VGA、最小格式化器与 panic 源码合同 PASS；构建合同及内核精确增量依赖专项 5/5 PASS；
- `make test-boot-qemu QEMU_TIMEOUT=5`：13/13 PASS，正式镜像新增输出 `[KERN] console ready hex=c0ffee dec=42 str=ok`，同时证明 `%x`、`%u` 和 `%s` 的运行时路径；
- 全量宿主测试：207/207 PASS；Kernel ELF 为 10,876 bytes，SHA-256 为 `9e44778414b87db5526abacdde2ecc6f14f27c36047b839acd2959cad6621d34`；镜像为 67,108,864 bytes，SHA-256 为 `c663296fce89f01d3b6d61403815d893be9dc571f5912364647ecef7840a1aff`；
- panic 的实际触发与 `[PANIC]` 串口可见性将在 CPU 异常负面测试中一并验收，当前只完成编译与源码合同，不将未触发路径记录为运行时 PASS。

同日完成正式 Ring 0 GDT 验证：3 个描述符分别为 null、4 GiB code、4 GiB data，`lgdt` 后重载数据段、`SS` 与 `CS`；正式镜像在既有控制台日志后输出 `[KERN] gdt ready`。启动专项 14/14 PASS，全量宿主测试 208/208 PASS。Kernel ELF 为 11,112 bytes，SHA-256 为 `4587bf4ec6b2edc35e670f1efe7d9f6ba49b955ee5fb62e7a31d388f9519e0e4`；镜像为 67,108,864 bytes，SHA-256 为 `d8fa8fb764c23212e4181907daf80d50f84c56bf378d555285f6e9dd81317b56`。Ring 3 描述符和 TSS 明确保留到 P4，不提前扩大 P2 范围。

同日完成 IDT/CPU 异常验证：正式镜像安装 256 项 IDT 的前 32 个异常门并输出 `[KERN] idt ready`；独立测试镜像执行 `int3`，真实串口输出 `[PANIC] exception vector=3 error=0 eip=0x...`，证明 stub、trap frame、C 分发和 panic 全链路。`KERNEL_TEST_BREAKPOINT` 非 `0/1` 或包含 Make 函数时在产生副作用前拒绝。启动专项 17/17 PASS，全量宿主测试 211/211 PASS。Kernel ELF 为 12,716 bytes，SHA-256 为 `8cbccb08ca50187f6b5c4ad5bb02ecf8e78b68b86c1e9cd841cd29cf115e39df`；镜像为 67,108,864 bytes，SHA-256 为 `e779a2013f3e1066f96930682bd20de46501c3b802a683e45408ebad156d3221`。

同日完成 PIC/PIT 验证：正式镜像将 PIC 重映射到 `0x20/0x28`，安装 16 个 IRQ 门，只放开 IRQ0，并在开启中断后由真实 PIT 依次输出 `[KERN] interrupts enabled` 与 `[KERN] pit tick=5`。启动专项 18/18 PASS，全量宿主测试 212/212 PASS。Kernel ELF 为 13,880 bytes，SHA-256 为 `8a5603dcc5e5728b4e4e8a640276408646dff31ed629f6b0ffc78ac26e53280c`；镜像为 67,108,864 bytes，SHA-256 为 `360e68b8c255ba794a08c4fa5e0afb82b5317717db91babdf9d23c84df81c31c`。

P2 最终键盘验收在正式 `MiniOrangeOS-Dev` 中完成：PS/2 控制器和第一端口自检、set-1 translation、`F4/FA` 扫描启用、IRQ1、Shift/Caps/extended/break 状态与 64-byte 环形缓冲源码合同 PASS；独立真实 QEMU 通过 HMP `sendkey a` 注入按键，串口观察到 `[KERN] keyboard input=a`。环境自检 PASS，启动专项 20/20 PASS，全量宿主测试 214/214 PASS；干净默认构建再次通过。Kernel ELF 为 19,076 bytes，SHA-256 为 `e441273b3035d73940620ab3de666694818437d4f0e20fe5adef6c3f2d151548`；镜像为 67,108,864 bytes，SHA-256 为 `8b5d2726cc6ee0275bc62af4b5f435b5bf2b1b106e88af174b2add58474596ee`。

## P3 进行中证据

Boot Info/PMM 首个增量在正式 `MiniOrangeOS-Dev` 中完成验证：64-byte Boot Info 与 24-byte E820 C 布局使用静态断言；入口把 Loader 的 EBX 指针按 cdecl 交给 C。真实 QEMU 输出非零 PMM total/free/reserved 统计并通过分配、页对齐、释放、最低页复用和计数恢复自检；启动专项 21/21 PASS，全量宿主测试 215/215 PASS。Kernel ELF 为 19,688 bytes，SHA-256 为 `cfede0a1092c0870fdc1ca1e9f84a5b1d5cebfda9f4f1b471168176b1dd1b3b6`；镜像为 67,108,864 bytes，SHA-256 为 `80e9ec59a1f3669bff5cb8f20f966469db267f7fc229600f81d7b9750ea27e84`。

正式 VMM 增量同日在 `MiniOrangeOS-Dev` 中完成验证：复用启动页目录建立 PDE 1023 递归映射，动态页表通过 PMM 与 scratch 映射清零；内核 text/rodata 按链接符号只读、data/bss 可写，启用 CR0.WP 后移除 PDE 0。运行时自检覆盖物理页分配、动态页表建立、映射查询、重复映射拒绝、真实虚拟地址读写、解除映射、空页表回收与 PMM 空闲计数恢复。`environment/verify.sh` PASS，启动专项 22/22 PASS，全量宿主测试 216/216 PASS；真实断点异常与 HMP `sendkey a` 回归继续通过。Kernel ELF 为 24,616 bytes，SHA-256 为 `c8d1b6f2f373af19ae0e9d12eda50a62432b3df0d26ecf52db8b4b56af3c9db6`；镜像为 67,108,864 bytes，SHA-256 为 `ad9ffa9c1e63b3fced10ecd8535313223ce1ee77d6fd2368a5b573d3bf1005e2`。

first-fit Heap 增量同日在 `MiniOrangeOS-Dev` 中完成验证：16 MiB 高半堆窗口从一页开始按需扩展，跨 PMM/VMM 的部分失败具有回滚路径；块头边界、magic 与双向链接在遍历时校验。运行时自检覆盖 8 字节对齐、first-fit 原地址复用、前后合并、64 块交错碎片压力、跨页增长、真实 payload 写入、double free 拒绝及超上限耗尽返回。启动专项 23/23 PASS，全量宿主测试 217/217 PASS；真实断点异常与 HMP 键盘回归继续通过。Kernel ELF 为 29,780 bytes，SHA-256 为 `27a4fdc9b80e2d24ed96b5efdc66f0c4aef0db44b4aff457361dedaac71ea862`；镜像为 67,108,864 bytes，SHA-256 为 `0e983f66b0134d1293324635aa414ea8cddb0d5d1a9ee9bdfca32923a1c75508`。

P3 最终用户内存增量同日在 `MiniOrangeOS-Dev` 中完成验证：离线用户页目录自检覆盖高半共享、递归项、用户映射冲突/高半越界、解除映射、销毁与 PMM 计数恢复；usercopy 覆盖有效 PDE/PTE 权限、真实跨页读写、页尾 NUL、未映射页、只读页和越界 `-EFAULT`。独立默认关闭且失败关闭的测试镜像读取未映射 `0x00400000`，真实 CPU #PF 输出 `[PANIC] kernel page fault address=0x00400000 error=0 eip=0x...`。最终 `environment/verify.sh` PASS，启动专项 25/25 PASS，全量宿主测试 219/219 PASS（365.108 秒），真实断点与 HMP 键盘回归继续通过。Kernel ELF 为 35,296 bytes，SHA-256 为 `10777c62c06713692a8dabad98ee91edcbe061bdc7278d4e95d5a0d495ca5161`；镜像为 67,108,864 bytes，SHA-256 为 `49fdcbfc812ee0268e9181bccf1f1f5849e6218ed87bb9d4f6c64603fed081f6`。

## P4 进行中证据

Ring 3 GDT/TSS 首个增量在正式 `MiniOrangeOS-Dev` 中完成验证：GDT 扩为 null、Ring 0 code/data、Ring 3 code/data 与 available 32-bit TSS 共 6 项；TSS 设置 `ss0`、启动 `esp0` 与越过 descriptor limit 的 I/O bitmap offset，`lgdt` 后执行 `ltr`。正式产品输出 `[KERN] tss ready` 并继续完成全部内存/中断初始化；启动专项 26/26 PASS，真实 kernel #PF、断点与 HMP 键盘回归继续通过。Kernel ELF 为 35,408 bytes，SHA-256 为 `03a1df54dcaf1e3f67ccc0308b17c353629e580be8b0abeb7a228034d0a28f0f`；镜像为 67,108,864 bytes，SHA-256 为 `3f4f74c81284cd957f9c78ef0e64b6833bc04c5ac36e88f5a770b8c4928eade3`。

协作式内核线程增量同日在 `MiniOrangeOS-Dev` 中完成验证：启动线程作为 PID 0，测试线程各有静态 PCB 与 16 KiB Heap 栈；汇编上下文切换保存 callee-saved 寄存器/ESP，调度选择在关中断区间完成并更新 TSS `esp0`。三个线程两轮 yield 严格产生 `1,2,3,1,2,3`，随后进入 ZOMBIE 并由启动线程回收全部栈块。启动专项 27/27 PASS，正式产品输出 scheduler ready/self-test PASS 后继续到达 PIT tick，真实 kernel #PF、断点和 HMP 键盘回归继续通过。Kernel ELF 为 36,472 bytes，SHA-256 为 `62af2e9ff2e1578e54058cc1e87d5b89cace216a042d106e2608b007f57d2ace`；镜像为 67,108,864 bytes，SHA-256 为 `f7c8f2b4092a5812fdd3be272bbda2519489acafcf6f6f36014ee26ae5dc1768`。

PIT 抢占增量同日在 `MiniOrangeOS-Dev` 中完成验证：IRQ0 完成 tick 与 EOI 后递减当前线程时间片，耗尽时在中断尾部保存整条 IRQ 栈并切换。两个测试线程均不调用 `yield`；线程 1 忙等线程 2 标志，真实 PIT 抢占使线程 2 获得 CPU 后两者退出并回收栈，正式串口输出 `[KERN] scheduler preemption PASS`。启动专项 27/27 PASS；随后环境验证 PASS、全量宿主回归 221/221 PASS（370.430 秒），真实 kernel #PF、断点和 HMP 键盘回归继续通过。Kernel ELF 为 40,888 bytes，SHA-256 为 `c4357169b6df4afc471c825a0c3182b5d5450604747a64ea522d275cd3f2340a`；镜像为 67,108,864 bytes，SHA-256 为 `b536158b5dea0d368302b8d9159da339c89f5335aa527c102066b63d75bb00ab`。

用户地址空间激活增量同日在 `MiniOrangeOS-Dev` 中完成验证：VMM 保存主内核页目录物理地址，创建和激活用户页目录时从主目录刷新共享高半 PDE，并在关中断区间清理临时工作窗口后重载 CR3。用户内存自检真实切入独立页目录，验证用户页读写、R/W 权限收紧与恢复、活动页目录销毁拒绝，再恢复主内核页目录并确认 PMM 计数完整回收。严格交叉编译 PASS，环境验证 PASS，启动专项 27/27 PASS，全量宿主回归 221/221 PASS（392.749 秒）。Kernel ELF 为 41,324 bytes，SHA-256 为 `5a70443ae8c2b7d51afd94b78ff298887364708de9c32d7e886262ffed6fb8f6`；镜像为 67,108,864 bytes，SHA-256 为 `e39ef2d236e0fa0ebf937230bcbaeafc5928e5fb39a1218ac3dac6ccc1401ddb`。

Ring 3/系统调用增量同日在 `MiniOrangeOS-Dev` 中完成验证：调度器在 PCB 切换时同步 CR3 与 TSS `esp0`，内嵌用户代码页只读、栈下方保留未映射保护页，并由 `iret` 首次进入 CPL3。DPL3 `int 0x80` 保存完整用户返回帧；Ring 3 程序依次验证未知调用号 `-ENOSYS`、非法 fd `-EBADF`、内核边界指针 `-EFAULT`、超长写入 `-EINVAL`，再通过 `getpid/write/yield/exit` 输出 `[USER] ring3 syscall PASS` 并由启动进程回收地址空间和内核栈。严格交叉编译 PASS，启动专项 28/28 PASS。Kernel ELF 为 46,596 bytes，SHA-256 为 `fb64f785451eddf339a8cb16a106865c8c87235a83a5bc5d8ba52f4f59bf760b`；镜像为 67,108,864 bytes，SHA-256 为 `89977310544493f3f504b5bf47f842e1aa7d99049bbef6deadd4489aea4fbba6`。

用户故障隔离增量同日在 `MiniOrangeOS-Dev` 中完成验证：异常与 IRQ 公共入口保存 DS/ES/FS/GS 后统一加载 Ring 0 data selector，返回前恢复原段。调度器仅接管与当前用户 PCB/CPL3 一致的 user #PF；内嵌 Ring 3 程序读取未映射 `0x0BADF000`，真实 CPU 产生 error=`0x4`，处理器核对 CR2/EIP 后以 `-EFAULT` 将进程置为 ZOMBIE，启动进程随后回收地址空间和内核栈并继续输出 `[KERN] user fault isolation PASS`。启动专项 28/28 PASS，全量宿主回归 222/222 PASS（388.638 秒），独立 kernel #PF panic、断点和 HMP 键盘回归继续通过。Kernel ELF 为 46,996 bytes，SHA-256 为 `f66eb89194ec10244c8049ab93242945f0f56d9046577f11e1f68331d30aed05`；镜像为 67,108,864 bytes，SHA-256 为 `94853e8b986e76b2a752393921b42f99acd95be235acac8afcc8d2a4fdede1ed`。

进程生命周期增量同日在 `MiniOrangeOS-Dev` 中完成验证：父进程 `waitpid` 阻塞后由内核子线程 exit 唤醒，读取状态 37 并回收 ZOMBIE 栈；重复 wait 返回 `-ECHILD`。PID 自检把分配器推进到 `INT32_MAX` 后确认切换到已回收 PID 扫描。Ring 3 程序验证无子进程 `waitpid(-1)=-ECHILD`，读取 `getticks`、执行 `sleep(2)` 后确认至少跨过两个 PIT tick，再继续 syscall 输出/退出；正式串口输出 `[KERN] process lifecycle self-test PASS`。严格交叉编译与真实产品路径 PASS；启动专项与全量回归将在 Heap 并发边界收口后一并执行。Kernel ELF 为 47,584 bytes，SHA-256 为 `2ac30c86c7e29b20ea22d65742860bb5fdb2d29c15bc09c951e364f6330cb3b7`；镜像为 67,108,864 bytes，SHA-256 为 `497c825dfadbf368befb5800744f3007d5b845dd508f775c7f3c3e2a8971b1df`。

## 串口测试协议

自动化测试只解析串口输出。格式固定：

```text
[TEST] suite=test_name begin
[TEST] case=case_name PASS
[TEST] case=case_name FAIL code=...
[TEST] suite=test_name PASS
[TEST] all PASS
```

失败时必须输出：

- suite；
- case；
- 错误码；
- 关键参数；
- 当前 tick；
- 当前进程 pid；
- 如相关，CR2、EIP、错误码或 fd/path。

QEMU 必须设置超时，测试完成后通过 debug-exit 设备或约定 I/O 端口主动退出。

## 必须覆盖的负面测试

启动：

- Boot 读取失败；
- Stage 2 LBA 越界；
- ELF 魔数错误；
- ELF Header 越界；
- Program Header 段覆盖 Loader；
- E820 条目过多。

内存：

- 物理页耗尽；
- 重复释放；
- 页表映射冲突；
- 用户指针越过 `0xC0000000`；
- 用户写只读页；
- 用户访问未映射页；
- 内核堆 double free。

进程：

- 时间片轮转至少三个进程；
- `sleep` 唤醒；
- `waitpid` 等待不存在子进程；
- 用户进程 page fault 后 Shell 继续运行；
- 子进程退出后资源回收。

系统调用：

- 系统调用号越界；
- fd 越界；
- close 后使用；
- 路径过长；
- argv 过多；
- 用户缓冲跨页。

文件系统：

- 磁盘满；
- inode 耗尽；
- 文件跨 direct/indirect 边界；
- 截断后空间复用；
- 删除非空目录；
- 损坏 Superblock；
- bitmap 与 inode 不一致；
- 重启后读取先前写入文件。

## CI 要求

CI 只使用 Linux runner。基本流程：

```text
build environment image
run environment/verify.sh
make check
make test-host
make test-qemu
upload logs on failure
```

CI 不依赖 Windows runner，不使用 Windows 原生工具链。

失败产物：

- 构建日志；
- 串口日志；
- QEMU 命令行；
- 测试镜像布局摘要；
- fsck 输出。

## 完成声明规则

只有实际运行命令且结果为 PASS，才能在任务报告中写“通过”。如果因环境未完成无法运行，必须写：

```text
未运行：原因
风险：该测试覆盖的缺陷可能未暴露
下一步：具体任务编号或命令
```

不得用“理论上可行”“应当通过”代替测试结果。
