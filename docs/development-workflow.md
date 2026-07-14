# 开发流程

本文档约束日常实现方式。详细设计看对应专题文档，阶段顺序看根目录 `PROJECT_PLAN.md`。

## 基本流程

每个阶段按 6 步推进：

1. 检查当前分支、工作树和相关专题文档。
2. 创建阶段分支，例如 `feature/P1-boot-chain`。
3. 先补关键测试，再做最小可验收实现。
4. 通过 `MiniOrangeOS-Dev` 运行阶段测试和已有回归。
5. 更新专题文档、来源记录、进度和阶段报告。
6. 提交；测试通过后再合并。

不得直接在 `main` 上实现功能。不得跳过测试后声明完成。

## 工作树与命令边界

- 唯一权威工作树：`D:\DC\program-projects\OTHER\MiniOrangeOS`。
- 文件修改和 Git 由 Windows 侧执行。
- WSL 不运行 Git，不维护第二份活动工作树。
- Linux 构建、QEMU、GDB 和测试通过 `MiniOrangeOS-Dev` 执行。

常用测试命令：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
./environment/verify.sh
make test
'
```

阶段内可以运行更小的局部测试；阶段完成前必须说明完整测试是否已跑、覆盖了什么、还缺什么。

## 分支与提交

默认按阶段建分支：

```text
feature/P1-boot-chain
feature/P2-kernel-interrupts
feature/P3-memory-management
feature/P4-process-syscall
feature/P5-user-shell
feature/P6-minifs
feature/P7-release-ci-docs
```

如果某阶段风险过高，可以拆成少量子分支，但不要把每个微步骤拆成独立任务。

提交信息采用：

```text
type(scope): summary
```

常用类型：`feat`、`fix`、`test`、`refactor`、`docs`、`build`、`chore`。

示例：

```text
feat(boot): enter protected mode from stage2
test(mm): cover usercopy boundary failures
docs(plan): simplify implementation phases
```

## 阶段报告

每个阶段完成时写一份简短报告。历史 T00-T11 任务报告保留，不要求补改成新格式。

```text
阶段：
分支：
提交：

修改文件：
- ...

关键实现：
- ...

执行命令：
- ...

测试结果：
- PASS/FAIL ...

未解决问题：
- 无 / ...

文档同步：
- 更新 / 无需更新，原因：...
```

报告只记录真实执行结果，不写推测、口号或重复的计划内容。

## 文档同步

按阶段检查相关文档：

| 阶段 | 必须检查 |
|---|---|
| P1 启动链 | `boot.md`、`architecture.md`、`testing.md` |
| P2 内核基础 | `architecture.md`、`memory.md`、`testing.md` |
| P3 内存管理 | `memory.md`、`syscall.md`、`testing.md` |
| P4 进程与系统调用 | `process.md`、`syscall.md`、`testing.md` |
| P5 用户态 | `process.md`、`syscall.md`、`filesystem.md` |
| P6 文件系统 | `filesystem.md`、`syscall.md`、`testing.md` |
| P7 收尾 | `testing.md`、`provenance.md`、`problems.md`、`progress.md` |

实现与文档冲突时，先改文档并说明原因，再改代码。

## 禁止事项

- 禁止复制教学 OS 源码后宣称从零实现。
- 禁止用 GRUB 替代自写启动链。
- 禁止把宿主 libc、Linux ABI 或动态链接器引入最低实现。
- 禁止为适配 Windows 建立 Windows 原生构建链。
- 禁止用大延时、关闭断言或跳过测试掩盖缺陷。
- 禁止用“后续补充”替代当前阶段完成定义。
