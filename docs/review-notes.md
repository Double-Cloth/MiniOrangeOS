# 开发者审查与心得

本文档在每个里程碑结束时记录实际阅读、理解、问题修正和尚需学习的内容。任务级事实记录在 docs/task-reports，来源记录在 docs/provenance.md。

## M0 进行中

已确认的工程原则：

- Windows 目录是唯一工作树，Windows Git 是唯一 Git。
- WSL 只提供 Linux 构建和测试语义。
- 每个 TXX 独立分支、先测试、同步文档、验收后 no-ff 合并。
- 未运行的测试不能写成 PASS。

当前需要在 M0 结束前掌握：

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
