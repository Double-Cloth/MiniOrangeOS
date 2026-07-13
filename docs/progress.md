# 项目进度

> 只记录有提交和真实测试证据的状态；计划不等于完成。

| 任务 | 状态 | 分支 | 测试证据 | 合并 |
|---|---|---|---|---|
| T00 | 完成 | feature/T00-project-bootstrap | ProjectLayoutTests 11/11 PASS | `def1657`：`merge: complete T00 project bootstrap` |
| T01 | 完成 | feature/T01-environment-toolchain | 正式 WSL 工具链/幂等、rootless Podman 生命周期、host 124/124 与 PowerShell 29/29 PASS | `c07fe81`：`merge: complete T01 environment toolchain` |
| T02 | 完成 | feature/T02-minimal-build-system | build 25/25、host 149/149、PowerShell 29/29、真实 clean/all/image PASS | `83323db`：`merge: complete T02 minimal build system` |
| T03 | 完成 | feature/T03-qemu-test-framework | qemu 35/35、host 185/185、PowerShell 29/29、真实 image/test-qemu/GDB PASS | `5577dc4`：`merge: complete T03 qemu test framework` |
| T10 | 完成 | feature/T10-boot-sector | stage1 9/9、host 194/194、T03 qemu 35/35、真实 IDE handoff/floppy error PASS | `789f18f`：`merge: complete T10 BIOS boot sector` |
| T11 | 实现完成，待合并 | feature/T11-stage2-real-mode | stage2 8/8、host 202/202、PowerShell 29/29、真实 S1→S2/BIOS API PASS | 待回填 |
| T12–T74 | 未开始 | — | — | — |

## 里程碑

| 里程碑 | 状态 | 验收摘要 |
|---|---|---|
| M0 | 完成 | T00–T03 工程基础、隔离工具链、构建镜像、QEMU/GDB 自动化均通过验收 |
| M1 | 实施中 | T10–T11 完成实现验收，T12–T15 待实现 |
| M2–M8 | 未开始 | 无 |
