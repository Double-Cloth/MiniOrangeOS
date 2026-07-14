# 风险、问题与降级记录

> 状态：持续维护。下表保留风险模型，后文记录已发生问题、修复证据和仍需外部验证的边界。

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

## 2026-07-14 / T02 构建产物安全边界

任务：T02

- 初版 `make clean BUILD_DIR=boot` 可能删除源码，镜像生成也存在路径校验后再次按名称打开的竞态和大组件全量入内存问题。
- 复审还验证了 Make 变量中的命令替换字符以及可覆盖的门禁辅助变量；最终门禁使用不可覆盖定义，并以命令行和 `make -e` 两类零副作用测试封闭绕过。
- 最终使用带仓库/目录身份的 marker、nofollow 目录 FD、原子隔离后删除和测试模式 race hook 约束清理；未知、复制 marker、symlink 或被替换目录均 fail closed。
- 镜像生成器逐级打开路径并持有组件 FD，采用稀疏感知的分块 `pread`/`pwrite`，输出经同目录临时文件原子替换；写失败、信号、hardlink、FIFO 和目录替换不会覆盖已有镜像。
- 新守卫按设计拒绝旧版本遗留且无 marker 的 `build/`；验收时确认它是仓库内无重解析点的生成目录后进行了一次迁移清理。

## 2026-07-14 / T01 最终安全审查闭环

任务：T01

最终全分支独立审查发现 6 个 Important：stale 容器未清理、`ready` 资源漂移无法收敛、`enter.ps1 -Command` 未实现 `bash -lc`、source stamp 未绑定完整解压树、WSL/容器身份可由环境变量伪造，以及 package-state 路径存在 symlink/TOCTOU 风险。修复后的复审进一步暴露并闭环了容器 stop 后 auto-remove、hardlink 拓扑与源码根 mode、package-state FD 继承，以及 helper 在 `SIGKILL` 后留下 root-only residue 的恢复问题。

最终实现以全量 ownership 复核和可重试 state machine 清理容器；以 manifest v2 绑定完整源码树；以 WSL2 Lxss 注册事实和 root-owned identity 绑定实例；以 `openat`、`O_NOFOLLOW`、`O_CLOEXEC`、进程内锁、原子替换和严格 residue schema 保护 package-state。各修复分支独立复审均为 Approved，未遗留 Critical 或 Important。

正式发行版的 identity-only 迁移只调用 `create.ps1 -DistroName MiniOrangeOS-Dev -AuthorizedRoot D:\ApplicationData\MiniOrangeOS -SkipBootstrap`。迁移前 `verify.sh` 按预期 FAIL；迁移后 PASS。`-SkipBootstrap` 仍 provision/validate identity，但未运行 apt 或工具链；destroy 默认 preview 与精确 apply/confirm 语义未改变。

## 2026-07-14 / T03 QEMU 自动化真实入口

任务：T03

- 初版协议解析可能在看到局部 PASS 后提前成功，且信号、孤儿后代、PGID 复用和日志/镜像路径替换存在边界缺口；最终改为严格状态机、精确 debug-exit 退出码、subreaper 与已验证 FD 路径。
- WSL 重挂载会同步改变 DrvFS `st_dev`；构建 marker 仅在路径、inode、schema 不变且 repo/build 设备号成对变化时接受重基，复制 marker 和单边变化仍拒绝。
- 公开 `make test-qemu` 暴露 DrvFS 在 rename 后写 FD 未关闭时目标名暂不可见；提交逻辑关闭已 rename 的 FD 后，从重新验证的同一目录核对最终完整身份。真实 v9fs 用例已覆盖。

## 2026-07-14 / T10 BIOS Stage 1 边界

任务：T10

- 单次从物理 `0x8000` 读取 127 扇区会跨 64 KiB DMA 边界；最终拆成 64+63 两个 DAP，并把 Loader 保留区统一为 `0x8000–0x17FFF`、E820 缓冲移至 `0x18000`。
- 初版真实测试只看到 Stage 1 自报成功，无法证明跳转；最终用 16 位 fixture 核验交接寄存器和 debug-exit，同时用 floppy 路径验证错误停机与进程清理。
- 布局生成器最终绑定 T02 marker/目录 FD，拒绝特殊文件、重复键、非有限数和含歧义路径，失败不覆盖已有 include，也不在源码树生成 bytecode。

## 2026-07-14 / P7 聚合测试与容器工作副本

任务：P7

- 首版 `make test BUILD_DIR=.p7-aggregate` 把命令行 `BUILD_DIR` 经 GNU Make 环境传播到 Python 测试内部的独立工作区，导致 build marker 身份不匹配。最终 `test-host` 在启动 Python 前清除 Make 递归状态、`BUILD_DIR` 和内核故障注入变量，并以伪造 `MAKEFLAGS/BUILD_DIR` 的真实构建专项验证隔离。
- 全量顺序还暴露 DrvFS 公开 QEMU 用例隐式依赖默认 `build` 父目录：前序构建用例会在清理后删除空父目录。用例现显式创建、验证并只在自己创建时回收该父目录，单项及最终全量均 PASS。
- OCI `run.sh` 原先只读挂载仓库却直接在 `/workspace` 执行，使文档中的 `run.sh make test` 无法生成产物。P7 改为 `/source:ro` 挂载，由受保守 Shell 策略检查的 `run-inside.sh` 复制到容器临时可写目录并保持 argv 边界执行，容器退出时随 `--rm` 回收。
- 首版 CI 只把测试输出写入 Actions 控制台，容器中的串口日志和镜像诊断会随 `--rm` 丢失，不满足失败证据合同。现由 `ci-run.sh` 把完整输出、QEMU 实际参数、残留日志、布局和镜像摘要导出到宿主挂载目录，workflow 失败时用固定提交的官方 action 上传。
- 最终 WSL 聚合入口 243/243 PASS（898.861 秒）。GitHub workflow 已固定 runner、容器输入、两个官方 action SHA、失败证据边界和最小权限，但分支尚未推送，不能把本地 WSL/合同测试表述为原生 Linux CI PASS。
