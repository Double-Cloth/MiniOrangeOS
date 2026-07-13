# ADR-0001：Windows 权威工作树与 WSL 测试环境

## 状态

已接受，2026-07-13。

## 背景

原计划要求工作树位于 WSL ext4。用户明确要求代码保留在当前 Windows 项目目录，只在 WSL 中进行 Linux 构建和测试。用户当前指令优先于前置项目文档。

## 决策

- 唯一权威工作树为 D:\DC\program-projects\OTHER\MiniOrangeOS。
- 文件修改和 Git 由 Windows 执行。
- MiniOrangeOS-Dev 通过 /mnt/d 挂载同一工作树，仅执行 Linux 构建、QEMU、GDB 和测试。
- 不在 WSL 中运行 Git，不维护第二份活动工作树。
- 使用 .gitattributes、WSL automount metadata 和契约测试约束行尾、可执行位和文件布局。

## 影响

优点：代码保持在用户指定项目目录，不产生同步分叉；Git 所有权单一。

代价：/mnt/d 的构建性能、大小写和 Linux 权限语义弱于 ext4。后续任务必须持续验证并行构建、增量构建、Shell 可执行位和 LF；若出现无法规避的正确性问题，需要新的 ADR 和用户确认，不能静默迁移工作树。
