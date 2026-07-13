# 开发者审查与心得

本文档在每个里程碑结束时记录实际阅读、理解、问题修正和尚需学习的内容。任务级事实记录在 docs/task-reports，来源记录在 docs/provenance.md。

## M0 完成

已确认的工程原则：

- Windows 目录是唯一工作树，Windows Git 是唯一 Git。
- WSL 只提供 Linux 构建和测试语义。
- 每个 TXX 独立分支、先测试、同步文档、验收后 no-ff 合并。
- 未运行的测试不能写成 PASS。

M0 已完成并验证以下能力：

- WSL 发行版创建、验证、备份和定向删除边界；
- i686-elf 工具链的组成和隔离路径；
- GNU Make 依赖、并行和增量构建行为；
- QEMU 串口、debug-exit、超时和 GDB 回环调试链。

## T01 心得

- 真实 Ubuntu 的 `/etc/os-release` 是受信相对 symlink，安全校验应绑定精确目标，而不是一律拒绝 symlink。
- T00 由 root 创建的只读中间目录可以安全存在，但最终环境根必须属于目标用户；路径逐级 ownership 比笼统 `chown` 更可审计。
- 可恢复容器生命周期需要同时绑定锁、intent、state、镜像 ID 与标签，单靠镜像名称不足以证明 ownership。
- rootless Podman 的 runroot 长度和 overlay subuid 清理只有真实集成会暴露；fake backend 必须模拟这些失败边界。
- WSL2 验收证明用户态与 Microsoft 内核组合，不等于原生 Linux CI 证据。
- 可恢复清理不能假设 `--rm`、image 或 builder 始终与 state 同步；必须在每个 mutation 阶段重新枚举并复核 ownership，把“可信且已缺失”与“同名 foreign replacement”明确区分。
- 固定归档哈希只证明下载来源，不能证明复用的解压树未漂移；可复现缓存还需绑定目录 mode、symlink、文件内容和 hardlink 拓扑，并在执行源码前复核。
- 安全的实例身份不能来自调用者可覆盖的环境变量；Windows Lxss 注册事实需要落为 Linux 内 root-owned、不可由普通用户改写的最小身份记录。
- 仅在 pathname 上重复 `stat` 不能封闭 target-owned 目录的 TOCTOU；敏感写入应锚定 nofollow 目录 FD，FD 必须 CLOEXEC，并为不可捕获终止设计严格、可审计的下一次恢复协议。

## T02 心得

- `clean` 也是高风险产品功能：可配置输出目录必须有不可复制的归属证明，并在校验、隔离和递归删除全过程绑定同一 inode。
- 原子 `replace` 只保护提交瞬间；输入组件、输出父目录和临时文件还需要 dirfd/nofollow、前后身份复核与失败清理共同封闭竞态。
- 固定镜像上限不能替代流式实现；稀疏文件测试能同时验证内存上限、零区语义和确定性。

## T03 心得

- 串口 PASS 只是协议输入，成功还必须同时满足完整有序状态机、无 FAIL、QEMU 真实退出和精确 debug-exit 状态。
- 进程清理要绑定本次 leader/PGID，并在回收前保留 leader 身份；subreaper 才能覆盖容器中双重 fork 的孤儿后代。
- 路径安全需要把镜像、构建根和日志目录绑定到已验证 FD；原子 rename 后仍要核对最终 inode，且 DrvFS 的可见性语义必须由真实工作树测试验证。

## T10 心得

- DAP 的 segment:offset 不回绕不等于物理 DMA 边界安全；跨 `0x10000` 的连续区域需要拆成两个 BIOS 请求。
- Stage 1 自己打印 `loader loaded` 不能证明交接成功；最小 Stage 2 探针应真实核验寄存器、标志和退出握手。
- 由单一布局生成汇编常量仍属于构建产品功能，必须继承 marker、nofollow、严格 schema、原子提交和源码零副作用边界。
