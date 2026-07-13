# MiniOrangeOS 贡献规范

## 开始任务

1. 阅读 PROJECT_PLAN.md、docs/README.md、docs/development-workflow.md 和对应专题文档。
2. 确认 Windows Git 工作区干净。
3. 从 main 创建 feature/TXX-short-description。
4. 先补测试或可执行验收约束，再写最小实现。

## 工作树边界

- 文件修改和 Git：D:\DC\program-projects\OTHER\MiniOrangeOS。
- Linux 构建和测试：MiniOrangeOS-Dev 中的 /mnt/d/DC/program-projects/OTHER/MiniOrangeOS。
- 禁止在 WSL 中运行 Git。
- 禁止修改 Windows PATH、注册表、全局 Git 配置和 Linux 全局 Shell 配置。

## 提交

格式：

    type(scope): summary

    说明变更原因、关键设计和测试范围。

    Refs: TXX

允许类型：feat、fix、test、refactor、docs、build、chore。

## 合并

只有当前任务测试和已有回归测试真实通过、文档已同步、工作区无未解释文件时，才推送任务分支并使用 --no-ff 合并到 main。失败或未运行的测试必须记录，且禁止合并。

## 文档同步

每个任务至少更新：

- docs/progress.md；
- docs/task-reports/TXX-*.md；
- 对应专题文档；
- docs/provenance.md；
- 有问题时更新 docs/problems.md；
- 里程碑结束时更新 docs/review-notes.md。
