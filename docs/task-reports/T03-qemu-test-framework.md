# T03：串口测试和 QEMU 自动化框架

任务：T03

分支：`feature/T03-qemu-test-framework`

状态：**完成并合并**

Merge SHA：`5577dc418442c23bc6f632a49b90b9739364ca9f`

## 实现摘要

- `Makefile` 提供 `run-serial`、`run-curses`、`debug`、`gdb` 和 `test-qemu`，工具、超时、日志上限与回环端点可安全覆盖。
- `tools/qemu_test.py` 严格解析 suite/case/all 协议，同时要求 QEMU 以 debug-exit 约定状态真实退出；失败、乱序、超时和信号均返回非零。
- runner 只清理本次进程组，以 subreaper 回收孤儿后代，并在清理完成前保留 leader 身份，避免 PGID 复用误杀。
- `tools/qemu_paths.py` 将镜像和日志绑定到经 T02 marker 验证的目录/文件 FD，拒绝 symlink、hardlink、FIFO 和目录替换；日志有界且原子提交。
- 固定 fixture 只验证 T03 框架，不提前实现 T10 正式 Boot Sector。

## 验收证据

2026-07-14 在正式 `MiniOrangeOS-Dev` 执行：

| 检查 | 结果 |
|---|---|
| T03 QEMU contract/runtime | 35/35 PASS |
| 全量 host unittest | 185/185 PASS |
| PowerShell WSL lifecycle | 29/29 PASS |
| `environment/verify.sh` | PASS |
| `make clean`、`make -j4 image`、`make test-qemu QEMU_TIMEOUT=5` | PASS |
| 真实 QEMU/GDB | debug-exit 33、完整串口协议、batch GDB 回环连接 PASS |
| raw image | 67,108,864 bytes、mode 0644、SHA-256 `6cf4f04e738ca014720b04b3ed192e0f526cc8162c9f19785cbdac9475923da2` |

## 审查闭环

独立审查最终为 Approved，Critical 0、Important 0。审查推动修复了局部 PASS 假成功、信号残留、PGID 复用、容器孤儿进程、debug-exit 状态、GDB 非回环、路径替换和日志临时文件竞态。真实公开入口又发现并闭环了 DrvFS 重挂载设备号与 rename 可见性差异；对应回归均已加入。

## 边界

当前可稳定验证 QEMU/GDB 自动化框架，但 Boot、Loader 和 Kernel 仍是 T02 占位产物；正式 BIOS 启动从 T10 开始。
