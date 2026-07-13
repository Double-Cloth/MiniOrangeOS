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

Linux/WSL：

```bash
./environment/bootstrap-inside.sh
./environment/with-env.sh i686-elf-gcc --version
./environment/verify.sh
./environment/ubuntu/create.sh
./environment/ubuntu/run.sh ./environment/verify.sh
./environment/ubuntu/destroy.sh --all
```

`destroy.ps1` 默认只预览，只有 `-Apply` 与精确确认名同时提供才会注销；`ubuntu/destroy.sh` 默认保留镜像，`--all` 才删除经 state、ID 和标签共同证明属于本项目的镜像与专用存储。禁止用全局 prune 代替这些入口。
