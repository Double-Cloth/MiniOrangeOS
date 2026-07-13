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

## 常用入口

Windows PowerShell：

```powershell
environment/wsl/create.ps1 -Bootstrap
environment/wsl/enter.ps1
environment/wsl/backup.ps1
environment/wsl/destroy.ps1
environment/wsl/destroy.ps1 -Apply -ConfirmName MiniOrangeOS-Dev
```

已有发行版只补建并校验可信实例身份、且明确跳过 apt 与工具链时使用：

```powershell
environment/wsl/create.ps1 -DistroName MiniOrangeOS-Dev -AuthorizedRoot D:\ApplicationData\MiniOrangeOS -SkipBootstrap
```

Linux/WSL：

```bash
./environment/bootstrap-inside.sh
./environment/with-env.sh i686-elf-gcc --version
./environment/verify.sh
./environment/ubuntu/create.sh
./environment/ubuntu/run.sh ./environment/verify.sh
./environment/ubuntu/destroy.sh --all
```

`create.ps1 -SkipBootstrap` 仍会校验 Lxss 名称、BasePath、reparse point 和 WSL2 注册版本，并 provision/validate root-owned 实例身份；它绝不运行 apt 或工具链 bootstrap。`enter.ps1 -Command '<command>'` 按单个 `bash -lc` 命令字符串执行，多值调用会被拒绝。

`destroy.ps1` 默认只预览，只有 `-Apply` 与精确确认名同时提供才会注销；`ubuntu/destroy.sh` 无参数只预览且不删除任何资源，只有 `--all` 才在 state、镜像 ID、标签、intent 与专用 storage 边界全部验证后执行定向删除。容器清理可恢复可信 `ready` 资源漂移及经 ownership 复核的 stale/auto-removed 项目容器，任何 foreign replacement 均 fail closed。禁止用全局 prune 代替这些入口。
