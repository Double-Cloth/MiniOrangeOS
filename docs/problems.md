# 风险、问题与降级记录

> 状态：前置风险清单。后续调试、降级和环境清理演练必须追加到本文件。

## 风险处理原则

降级只允许减少扩展能力，不得删除 A 类核心链路。以下能力不可降级删除：

- 自写 Boot/Loader；
- Ring 3；
- 分页；
- 独立地址空间；
- ELF 用户程序加载；
- 抢占式调度；
- 控制台；
- 持久化文件读写；
- 测试和文档闭环。

## 当前风险清单

| 风险 | 早期信号 | 定位手段 | 允许降级 |
|---|---|---|---|
| Stage 1 空间不足 | 512 字节溢出 | `ndisasm`、map 文件、最小日志 | 减少日志，不能改用 GRUB |
| Loader 读盘不稳定 | 随机加载失败 | 串口阶段码、QEMU `-d int` | 内核连续扇区加载，仍自写 Loader |
| E820 解析错误 | PMM 释放保留页 | dump E820、页分配边界测试 | 限制最大内存，不跳过 E820 |
| 高半切换三重故障 | QEMU 重启 | GDB 看 CR3/PDE/EIP | 临时保留低端映射，最终恢复高半 |
| Ring 3 进入失败 | `iret` fault | 检查 GDT/TSS/栈帧/段选择子 | 先单用户程序，再接调度 |
| 抢占竞态 | 随机死锁 | 关中断区域审计、串口 tick | 不实现优先级，保留抢占 |
| usercopy 漏洞 | 用户指针击穿内核 | 恶意 syscall 测试 | 缩小 syscall 集，不取消校验 |
| MiniFS 元数据损坏 | 重启后文件丢失 | fsck、写入顺序日志 | 不做日志，保留持久化 |
| ATA 超时 | QEMU 卡死 | 超时计数、状态寄存器日志 | 降低多扇区复杂度 |
| CI 与本地漂移 | 本地过 CI 挂 | 环境指纹 diff | 固定容器，不手工修 CI |
| `/mnt/d` 构建性能和权限语义差异 | 并行或增量构建异常、Shell 不可执行、大小写冲突 | 行尾、可执行位、大小写和增量构建测试 | 使用 metadata 挂载和严格 `.gitattributes`；不允许维护第二份工作树 |
| 清理误删资源 | 容器/WSL 消失 | 标签白名单、dry-run | 禁止全局 prune |
| `/mnt/d` 构建较慢或语义漂移 | 大型 context/增量构建慢，大小写、symlink 或权限异常 | 与 ext4/Linux CI 对比，持续运行 LF/权限/增量测试 | 构建缓存放 WSL ext4；不复制权威工作树 |
| WSL 与原生 Linux 内核差异 | WSL2 通过但 Linux CI/runtime 失败 | 记录内核与 runtime 指纹，在原生 Linux CI 重跑 | 不把 WSL 结果表述为原生内核证据 |
| Windows 预存工具造成误判 | `Get-Command gdb` 命中外部 MinGW | 校验来源路径，只拒绝项目载荷或项目 PATH 污染 | 不删除用户既有工具；项目命令只经 `with-env.sh` 注入 |

## 功能收缩顺序

进度落后时按以下顺序收缩：

1. Bochs 和真实硬件验证；
2. 块缓存；
3. Shell 历史和高级编辑；
4. 文件系统截断增强；
5. 多级目录中的复杂边界增强；
6. `fork`；
7. 管道；
8. 扩展系统调用。

## 问题记录模板

```text
## YYYY-MM-DD / 标题

任务：
环境：
现象：
复现命令：
关键日志：
初步判断：
已尝试：
结论：
后续：
```

## 环境清理演练记录模板

```text
## YYYY-MM-DD / 环境清理演练

环境：
将删除资源：
- ...

保留资源验证：
- ...

执行命令：
- ...

结果：
- PASS/FAIL

问题：
- ...
```

## 2026-07-13 / T01 真实集成问题

任务：T01

- Podman 拒绝超过 50 字符的 runroot；修复为经 owner/mode/symlink 校验的 `$XDG_RUNTIME_DIR/miniorangeos-t01`。
- fake backend 曾放过不存在的 `image rmi`；收紧测试并改为 Podman/Docker 均支持的 `image rm`。
- rootless overlay 含 subuid-owned 文件，宿主 `rm -rf` 无权清理；改为仅对已验证专用 `--root/--runroot` 执行一次 `podman system reset --force`，不使用全局 prune。

最终 create/run/destroy 通过，默认 Podman images/containers/volumes 未变化，测试发行版已定向清理。

## 2026-07-14 / T01 最终安全审查闭环

任务：T01

最终全分支独立审查发现 6 个 Important：stale 容器未清理、`ready` 资源漂移无法收敛、`enter.ps1 -Command` 未实现 `bash -lc`、source stamp 未绑定完整解压树、WSL/容器身份可由环境变量伪造，以及 package-state 路径存在 symlink/TOCTOU 风险。修复后的复审进一步暴露并闭环了容器 stop 后 auto-remove、hardlink 拓扑与源码根 mode、package-state FD 继承，以及 helper 在 `SIGKILL` 后留下 root-only residue 的恢复问题。

最终实现以全量 ownership 复核和可重试 state machine 清理容器；以 manifest v2 绑定完整源码树；以 WSL2 Lxss 注册事实和 root-owned identity 绑定实例；以 `openat`、`O_NOFOLLOW`、`O_CLOEXEC`、进程内锁、原子替换和严格 residue schema 保护 package-state。各修复分支独立复审均为 Approved，未遗留 Critical 或 Important。

正式发行版的 identity-only 迁移只调用 `create.ps1 -DistroName MiniOrangeOS-Dev -AuthorizedRoot D:\ApplicationData\MiniOrangeOS -SkipBootstrap`。迁移前 `verify.sh` 按预期 FAIL；迁移后 PASS。`-SkipBootstrap` 仍 provision/validate identity，但未运行 apt 或工具链；destroy 默认 preview 与精确 apply/confirm 语义未改变。
