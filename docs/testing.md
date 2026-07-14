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
