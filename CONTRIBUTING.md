# MiniOrangeOS 贡献规范

## 开始阶段

1. 阅读 `PROJECT_PLAN.md`、`docs/README.md`、`docs/development-workflow.md` 和当前阶段专题文档。
2. 确认 Windows Git 工作区干净。
3. 从 `main` 创建阶段分支，例如 `feature/P1-boot-chain`。
4. 先补关键测试或可执行验收约束，再写最小实现。

## 工作树边界

- 文件修改和 Git：`D:\DC\program-projects\OTHER\MiniOrangeOS`。
- Linux 构建和测试：`MiniOrangeOS-Dev` 中的 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS`。
- 禁止在 WSL 中运行 Git。
- 禁止修改 Windows PATH、注册表、全局 Git 配置和 Linux 全局 Shell 配置。

## 提交

格式：

```text
type(scope): summary

说明变更原因、关键设计和测试范围。
```

允许类型：`feat`、`fix`、`test`、`refactor`、`docs`、`build`、`chore`。

## 合并

只有阶段测试和已有回归测试真实通过、文档已同步、工作区无未解释文件时，才推送分支并使用 `--no-ff` 合并到 `main`。失败或未运行的测试必须记录，且禁止合并。

## 文档同步

阶段完成时按需更新：

- `docs/progress.md`；
- `docs/task-reports/P*-*.md`；
- 当前阶段对应专题文档；
- `docs/provenance.md`；
- 有问题时更新 `docs/problems.md`；
- 里程碑或答辩前更新 `docs/review-notes.md`。
