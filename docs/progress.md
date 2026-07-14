# 项目进度

> 只记录有提交和真实测试证据的状态；计划不等于完成。

## 已完成历史任务

| 任务 | 状态 | 分支 | 测试证据 | 合并 |
|---|---|---|---|---|
| T00 | 完成 | `feature/T00-project-bootstrap` | ProjectLayoutTests 11/11 PASS | `def1657`：`merge: complete T00 project bootstrap` |
| T01 | 完成 | `feature/T01-environment-toolchain` | 正式 WSL 工具链/幂等、rootless Podman 生命周期、host 124/124 与 PowerShell 29/29 PASS | `c07fe81`：`merge: complete T01 environment toolchain` |
| T02 | 完成 | `feature/T02-minimal-build-system` | build 25/25、host 149/149、PowerShell 29/29、真实 clean/all/image PASS | `83323db`：`merge: complete T02 minimal build system` |
| T03 | 完成 | `feature/T03-qemu-test-framework` | qemu 35/35、host 185/185、PowerShell 29/29、真实 image/test-qemu/GDB PASS | `5577dc4`：`merge: complete T03 qemu test framework` |
| T10 | 完成 | `feature/T10-boot-sector` | stage1 9/9、host 194/194、T03 qemu 35/35、真实 IDE handoff/floppy error PASS | `789f18f`：`merge: complete T10 BIOS boot sector` |
| T11 | 完成 | `feature/T11-stage2-real-mode` | stage2 8/8、host 202/202、PowerShell 29/29、真实 S1->S2/BIOS API PASS | `e02acfb`：`merge: complete T11 stage2 real-mode runtime` |

## 当前阶段路线

| 阶段 | 状态 | 验收摘要 |
|---|---|---|
| P0 工程基础 | 完成 | 历史 T00-T03 已完成：工程骨架、隔离环境、构建镜像、QEMU/GDB 自动化 |
| P1 启动链 | 完成 | `d8fab7b` 合并；环境 PASS、启动专项 11/11、完整宿主 205/205、真实 QEMU 到达 `[KERN] boot info valid` |
| P2 内核基础与中断 | 完成 | `6a307e8` 合并；分页、控制台/panic、GDT/IDT、异常、PIC/PIT、PS/2 键盘；环境 PASS、启动专项 20/20、全量宿主 214/214、真实按键注入 PASS |
| P3 内存管理 | 完成 | `54d7cf3` 合并；E820 PMM、正式 VMM、first-fit heap、用户页目录、usercopy/page fault；环境 PASS、启动专项 25/25、全量宿主 219/219、真实 kernel #PF/断点/按键回归 PASS |
| P4 进程与系统调用 | 完成 | `29a2c7d` 合并；Ring 3/TSS、PCB/16 KiB 内核栈、三线程 PIT 抢占、用户页目录、用户 #PF 隔离、sleep/waitpid、PID 复用、IRQ-safe Heap 与 7 个 `int 0x80` 调用；环境/干净构建 PASS、启动专项 28/28、全量宿主 222/222 |
| P5 ELF 用户态与 Shell | 完成 | `f4363cb` 合并；静态 ELF32 loader、共享 ABI、crt0/最小 libc、init/Shell、echo/ps/memtest/fault；环境/干净构建 PASS、启动专项 28/28、全量宿主 225/225 |
| P6 磁盘与 MiniFS | 进行中 | 已完成 ATA/block、磁盘 ABI、mkfs/fsck/装配、内核只读挂载、inode/direct/indirect 读取与绝对路径解析；真实 QEMU 逐字节核对 6 个磁盘 ELF，坏 magic/CRC 失败关闭；启动专项 31/31、MiniFS 工具 6/6、构建契约 10/10、运行时构建回归 21/21；可变 MiniFS、VFS、fd、文件命令与持久化待完成 |
| P7 CI、文档和答辩版本 | 未开始 | `make test` 收敛、Linux CI、文档校准、演示脚本、release checklist |

## 记录规则

- T00-T11 是历史验收记录，不再改写成阶段报告。
- 后续每个阶段完成后，在 `docs/task-reports/` 新增阶段报告，例如 `P1-boot-chain.md`。
- 只记录真实命令和真实 PASS/FAIL，不写预计完成状态。
