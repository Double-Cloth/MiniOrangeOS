# 开发流程与任务执行规范

> 来源：计划书第 1、16、17、19 节。本文档约束后续代码任务的执行方式。

## 基本流程

每个任务都按以下顺序执行：

1. 阅读计划书对应任务。
2. 阅读本目录对应专题文档。
3. 在 Windows 权威工作树中使用 Windows Git 检查当前分支和工作树。
4. 使用 Windows Git 创建任务分支。
5. 先写或补测试，再写最小实现。
6. 通过 `wsl.exe` 在 `MiniOrangeOS-Dev` 中运行任务要求的 Linux 构建和测试。
7. 更新文档和来源登记。
8. 使用 Windows Git 提交。
9. 按报告模板总结。

不得直接在 `main` 上实现功能。不得跳过测试后声明完成。

## 工作树与命令边界

- 唯一权威工作树：`D:\DC\program-projects\OTHER\MiniOrangeOS`。
- 文件修改和 Git 由 Windows 侧执行；WSL 不运行 Git，不维护第二份活动工作树。
- Linux 构建、QEMU、GDB 和测试通过 `MiniOrangeOS-Dev` 执行，工作树路径为 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS`。

测试命令形式：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
<linux-test-command>
'
```

## 分支命名

推荐格式：

```text
feature/T00-project-bootstrap
feature/T10-boot-sector
feature/T31-virtual-memory
fix/T63-superblock-validation
docs/T73-architecture-sync
```

任务型分支必须能从名称看出任务编号和主题。

## 提交格式

提交信息采用：

```text
<type>: <summary>
```

常用类型：

| 类型 | 使用场景 |
|---|---|
| `docs` | 文档、计划、来源记录 |
| `build` | 构建系统、工具链、CI |
| `test` | 测试框架和测试用例 |
| `boot` | Stage 1、Stage 2、启动链 |
| `kernel` | 内核通用基础 |
| `mm` | 内存管理 |
| `proc` | 进程、调度、Ring 3 |
| `fs` | 磁盘、块设备、文件系统 |
| `user` | 用户态程序和 libc |
| `fix` | 缺陷修复 |

示例：

```text
boot: add stage1 disk read skeleton
mm: validate usercopy page ranges
fs: implement direct block read path
docs: sync filesystem layout contract
```

## 合并

只有当前任务测试和已有回归测试在有效 Linux 环境中真实通过、文档已同步且工作树无未解释文件时，才允许使用 Windows Git 推送任务分支并自动执行 `--no-ff` 合并。测试失败或未运行时不得合并。

## 任务报告模板

每个任务结束必须报告：

```text
任务：Txx - 标题
分支：
提交：

修改文件：
- ...

关键设计：
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

## 文档同步点

| 任务范围 | 必须检查文档 |
|---|---|
| T00-T03 | `environment.md`、`development-workflow.md`、`testing.md` |
| T10-T15 | `boot.md`、`architecture.md`、`testing.md` |
| T20-T24 | `architecture.md`、`memory.md`、`testing.md` |
| T30-T34 | `memory.md`、`syscall.md`、`testing.md` |
| T40-T44 | `process.md`、`syscall.md`、`testing.md` |
| T50-T53 | `process.md`、`syscall.md`、`filesystem.md` |
| T60-T68 | `filesystem.md`、`syscall.md`、`testing.md` |
| T70-T74 | `testing.md`、`provenance.md`、`problems.md` |

## 禁止事项

- 禁止复制 Orange'S、xv6、Minix 或其他教学操作系统源码。
- 禁止使用 GRUB 替代自写启动链。
- 禁止把宿主 libc、Linux ABI 或动态链接器引入内核或用户程序最低实现。
- 禁止为适配 Windows 建立 Windows 原生构建链。
- 禁止在未定位问题时用大延时、关闭优化或跳过断言掩盖缺陷。
- 禁止用“后续补充”替代当前任务完成定义。
