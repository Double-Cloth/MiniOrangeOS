# environment 目录

本目录只管理 MiniOrangeOS 的隔离测试环境，不保存源码副本。

## 固定边界

- 发行版：MiniOrangeOS-Dev。
- Windows 环境根：D:\ApplicationData\MiniOrangeOS。
- 权威工作树：D:\DC\program-projects\OTHER\MiniOrangeOS。
- WSL 测试路径：/mnt/d/DC/program-projects/OTHER/MiniOrangeOS。

## 子目录职责

- wsl：创建、进入、备份和定向销毁专用 WSL2 发行版。
- ubuntu：真实 Ubuntu 上的 rootless OCI 复验入口。
- 仓库根层脚本：版本清单、临时环境注入、依赖引导和环境验证。

生命周期脚本由 T01 实现并验收。任何清理命令都必须先预览，只能删除带 MiniOrangeOS 明确名称或路径边界的资源。
