Exit code: 0
Wall time: 1.3 seconds
Output:
# 测试策略与验收协议

> 覆盖任务：T03、T70-T72，并约束所有功能任务。

## 测试分层

| 层级 | 目标 | 运行方式 |
|---|---|---|
| 环境层 | 工具路径、版本、宿主污染、可删除性 | `environment/verify.sh` |
| 编译期 | 静态断言、结构大小、链接地址、未定义符号 | `make check` |
| 宿主单元测试 | 纯算法、解析器、bitmap、路径、mkfs/fsck | `make test-host` |
| QEMU 内核测试 | 中断、分页、堆、调度、Ring 3、syscall | `make test-qemu` |
| QEMU 用户测试 | ELF、usercopy、Shell、文件命令 | `make test-qemu` |
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
