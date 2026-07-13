# 开发流程与任务执行规范

> 来源：计划书第 1、16、17、19 节。本文档约束后续代码任务的执行方式。

## 基本流程

每个任务都按以下顺序执行：

1. 阅读计划书对应任务。
2. 阅读本目录对应专题文档。
3. 检查当前分支和工作树。
4. 创建任务分支。
5. 先写或补测试，再写最小实现。
6. 运行任务要求的测试。
7. 更新文档和来源登记。
8. 提交 Git。
9. 按报告模板总结。

不得直接在 `main` 上实现功能。不得跳过测试后声明完成。

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

