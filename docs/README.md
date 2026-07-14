# MiniOrangeOS 文档索引

根目录 `PROJECT_PLAN.md` 是当前实施入口，定义阶段路线和完成标准。本目录保存专题设计、测试规则、来源记录、问题记录、进度和历史任务报告。

## 快速阅读

日常实现只需要先读：

1. `PROJECT_PLAN.md`：确认当前阶段、范围和验收。
2. `development-workflow.md`：确认分支、测试、报告和提交方式。
3. 当前阶段对应的专题文档。

阶段对应文档：

| 阶段 | 需要读 |
|---|---|
| P1 启动链 | `boot.md`、`architecture.md`、`testing.md` |
| P2 内核基础 | `architecture.md`、`memory.md`、`testing.md` |
| P3 内存管理 | `memory.md`、`syscall.md`、`testing.md` |
| P4 进程与系统调用 | `process.md`、`syscall.md`、`testing.md` |
| P5 用户态 | `process.md`、`syscall.md`、`filesystem.md` |
| P6 文件系统 | `filesystem.md`、`syscall.md`、`testing.md` |
| P7 收尾 | `testing.md`、`provenance.md`、`problems.md`、`progress.md` |

## 文档职责

| 文档 | 职责 |
|---|---|
| `architecture.md` | 总体分层、目录职责、初始化顺序、错误模型 |
| `boot.md` | Stage 1、Stage 2、A20、E820、保护模式、内核加载 |
| `memory.md` | PMM、VMM、高半映射、堆、用户地址空间、usercopy |
| `process.md` | PCB、调度、Ring 3、TSS、ELF 用户程序、Shell |
| `syscall.md` | `int 0x80` ABI、系统调用表、用户指针安全、fd 语义 |
| `filesystem.md` | ATA、块设备、MiniFS、VFS、mkfs、fsck |
| `testing.md` | 测试层级、串口协议、负面测试、CI 要求 |
| `environment.md` | WSL、工具链隔离、真实 Ubuntu 复验和清理方式 |
| `provenance.md` | 来源登记和自主实现证明 |
| `problems.md` | 风险、问题、降级和环境清理记录 |
| `progress.md` | 只记录有提交和真实测试证据的进度 |
| `release-checklist.md` | P7 最终环境、构建、演示、文档与限制核对清单 |
| `task-reports/` | 历史 T00-T11 任务报告和后续阶段报告 |
| `decisions/` | 已接受的重要工程决策 |

## 维护规则

- 代码必须遵守已确认的专题文档。
- 实现证明文档不合理时，先更新文档并说明原因。
- 不得把未实现、未测试或未复验的能力写成已完成。
- 阶段结束时只更新相关文档，不做全目录机械同步。
- 答辩前清理“前置设计”“待实现”等与真实状态冲突的表述。
