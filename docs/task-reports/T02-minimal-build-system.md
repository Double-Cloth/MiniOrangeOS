# T02：最小构建系统

任务：T02

分支：`feature/T02-minimal-build-system`

状态：**完成并合并**

Merge SHA：`83323db3cc5f39b4ed9daeed0337f687be712235`

## 实现摘要

- 顶层 GNU Make 构建 NASM Stage 1/Stage 2、C11 freestanding Kernel、ELF、map、symbol、binary 和 depfile，全部产物位于可配置 `BUILD_DIR`。
- 构建支持 `-j` 并行、精确增量依赖、工具覆盖，以及 `all`、`image`、`clean`、`distclean` 公共目标。
- `config/image-layout.json` 是唯一镜像布局来源：512-byte sector、64 MiB raw image，Stage 1/Stage 2/Kernel 使用固定且不重叠的 LBA 区域。
- `tools/build_dir_guard.py` 绑定仓库和构建目录身份，阻止清理源码、外部目录、symlink、复制 marker 或竞态替换目录。
- `tools/make_image.py` 使用 nofollow dirfd、普通文件/单硬链接约束、稀疏流式复制和同目录原子替换；失败不破坏已有输出。

## 验收证据

2026-07-14 在 Windows 权威工作树映射到正式 `MiniOrangeOS-Dev` 后执行：

| 检查 | 结果 |
|---|---|
| T02 build contract/runtime | 25/25 PASS |
| 全量 host unittest | 149/149 PASS |
| PowerShell WSL lifecycle | 29/29 PASS |
| `environment/verify.sh` | PASS |
| `make clean`、`make -j4 all`、`make image` | PASS |
| 第二次 `make -j4 all` | exit 0、无命令输出，未重建 |
| raw image | 67,108,864 bytes、mode 0644、SHA-256 `6cf4f04e738ca014720b04b3ed192e0f526cc8162c9f19785cbdac9475923da2` |
| Kernel | ELF32、Intel 80386、EXEC、entry `0x00100000` |

## 审查闭环

测试审查和最终产品复审均为 Approved，Critical 0、Important 0。初版产品审查发现危险 `BUILD_DIR` 清理、空格路径解析、镜像 TOCTOU、全量内存加载和缺少 `distclean`；复审继续发现 Make 变量命令注入、可覆盖门禁以及 DrvFS 临时文件清理的二次替换竞态。最终实现对 Make 输入在解析期 fail closed；DrvFS 绑定删除失败时保留不可预测临时文件，不再尝试可能误删外来路径的重定位清理。上述问题均有零副作用或 race 回归覆盖。

## 边界

T02 仅提供可链接、可布局的占位框架，不声明镜像已经能够启动。QEMU 串口、超时、PASS/FAIL 协议和 GDB 回环入口属于 T03；正式 BIOS 启动链从 T10 开始。
