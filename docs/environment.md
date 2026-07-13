Exit code: 0
Wall time: 0.6 seconds
Output:
# 开发环境与可逆清理设计

> 来源：计划书第 14、15、22.7 节。本文档只描述环境和操作约束，不包含安装脚本实现。

## 环境原则

MiniOrangeOS 的开发环境必须可复现、可审计、可整体删除。Windows 主机承载唯一权威工作树、文件编辑、Windows Git 和 WSL2 入口；不安装项目专用原生编译、调试或虚拟化工具链，不修改 Windows PATH、注册表、文件关联或系统服务。

文件和执行边界固定为：

- 文件编辑与 Git：Windows 权威工作树 `D:\DC\program-projects\OTHER\MiniOrangeOS`，只使用 Windows Git。
- Linux 构建与测试：专用 WSL2 Ubuntu 24.04 发行版 `MiniOrangeOS-Dev`，通过 `/mnt/d/DC/program-projects/OTHER/MiniOrangeOS` 访问同一工作树，不运行 Git。
- T01 容器复验：独立 Ubuntu 24.04 WSL2 测试发行版中的 rootless Podman；不冒充原生 Linux 内核证据。
- CI：后续 Linux runner 补齐原生 Linux 内核差异。

## 路径与载荷边界

项目专用工具链根目录：

```text
${XDG_DATA_HOME:-$HOME/.local/share}/miniorangeos-dev
```

Windows 侧环境载荷集中目录：

```text
D:\ApplicationData\MiniOrangeOS
```

该目录负责承载：

- i686-elf 交叉编译器；
- NASM、QEMU、GDB 等可固定版本依赖的缓存或构建结果；
- Python venv；
- 环境指纹；
- 工具链构建日志。

禁止写入：

- Windows PATH；
- Windows 注册表；
- Linux `/usr/local`；
- Linux 全局 Shell 配置；
- 系统级 Python site-packages；
- 与项目无关的容器镜像、卷、网络。

## Windows 权威工作树与 WSL2 构建测试模型

从 Windows 侧调用 Linux 命令时，统一使用：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '<command>'
```

固定执行路径：

```powershell
wsl.exe -d MiniOrangeOS-Dev -- bash -lc '
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest tests.host.test_project_layout -v
'
```

Windows 权威工作树位于 NTFS，这是已接受的工程取舍。`/mnt/d` 的构建性能、大小写、符号链接和 Linux 权限语义可能弱于 WSL ext4。后续任务必须持续验证行尾、Shell 可执行位、大小写、并行构建和增量构建；使用 WSL automount metadata 和严格 `.gitattributes` 降低差异风险。不允许为规避这些风险而维护第二份活动工作树；如果出现无法规避的正确性问题，必须新建 ADR 并由用户确认。

## 真实 Ubuntu 复验模型

真实 Ubuntu 24.04 使用 rootless Podman 优先，已有 Docker 时可作为兼容后端。复验容器必须：

- 由 `environment/Containerfile` 定义；
- 通过项目标签标识；
- 不要求特权模式；
- 不向宿主 `/usr/local` 写入项目工具链；
- 复验结束后可按项目标签删除容器、镜像、卷和缓存。

禁止使用无范围命令，例如：

```text
podman system prune -a
docker system prune -a
rm -rf ~/.local/share
```

## 已实现公开接口

以下脚本和配置已由 T01 实现并通过契约与真实环境验收：

| 文件 | 职责 |
|---|---|
| `environment/wsl/create.ps1` | 定向创建 `MiniOrangeOS-Dev`，所有环境载荷写入授权根目录 |
| `environment/wsl/enter.ps1` | 进入既有 `MiniOrangeOS-Dev`，不创建第二份工作树 |
| `environment/wsl/backup.ps1` | 将专用发行版备份到项目授权的导出目录 |
| `environment/wsl/destroy.ps1` | 预览并定向注销 `MiniOrangeOS-Dev`，不影响其他发行版 |
| `environment/Containerfile` | 定义真实 Ubuntu 复验容器 |
| `environment/ubuntu/create.sh` | 创建带项目标签的真实 Ubuntu rootless OCI 复验环境 |
| `environment/ubuntu/run.sh` | 在已创建的复验环境中运行项目命令 |
| `environment/ubuntu/destroy.sh` | 只删除本项目标记的容器、镜像、卷和缓存 |
| `environment/bootstrap-inside.sh` | 在隔离 Linux 环境中安装固定版本依赖，不写入宿主 `/usr/local` |
| `environment/with-env.sh` | 临时注入项目工具链和 venv 后执行命令，不修改全局环境 |
| `environment/verify.sh` | 输出环境指纹，校验工具路径和版本，拒绝越界路径 |
| `tools/build_toolchain.sh` | 在 `$MINIOS_ENV_ROOT/toolchain` 可重复构建 i686-elf 工具链 |

常用命令：

```powershell
environment/wsl/create.ps1 -Bootstrap
environment/wsl/enter.ps1
environment/wsl/backup.ps1
environment/wsl/destroy.ps1
environment/wsl/destroy.ps1 -Apply -ConfirmName MiniOrangeOS-Dev
```

```bash
./environment/with-env.sh i686-elf-gcc --version
./environment/verify.sh
./environment/ubuntu/create.sh
./environment/ubuntu/run.sh ./environment/verify.sh
./environment/ubuntu/destroy.sh --all
```

`destroy.ps1` 默认只 preview，必须同时提供 `-Apply` 和精确确认名。`environment/ubuntu/destroy.sh` 默认保留镜像；`environment/ubuntu/destroy.sh --all` 只删除由 state、镜像 ID、标签、intent 和专用 storage 共同证明属于本项目的资源，不使用全局 prune。

## 环境验证最低输出

`environment/verify.sh` 后续必须至少输出：

```text
MiniOrangeOS environment verification
host_os=...
wsl_distro=MiniOrangeOS-Dev
ubuntu_version=24.04
tool_root=...
i686_elf_gcc=...
nasm=...
qemu_system_i386=...
gdb=...
python=...
git=...
windows_path_pollution=none
linux_global_pollution=none
result=PASS
```

如果在 Windows 原生环境、非目标 WSL 发行版、未隔离容器或工具链路径越界时运行，必须返回非零状态。

## T01 真实验收

- 正式 prefix：`/home/minios/.local/share/miniorangeos-dev/toolchain`；目标 `i686-elf`，GCC 13.2.0、GNU ld 2.42、libgcc 与 ELF32 freestanding 编译 PASS。
- 正式 WSL 首次成功 bootstrap 约 6 分 15 秒，紧接第二次约 5 秒并返回 `toolchain_status=up-to-date`。
- `MiniOrangeOS-Dev-Test-ContainerHost` 在 **Ubuntu 24.04 WSL2** 上使用 **rootless Podman** 4.9.3 完成 create、幂等 create、run 和 destroy；默认 Podman 资源未变化，测试发行版已定向注销。
- 运行内核为 Microsoft WSL2，不代表已覆盖**原生 Linux 内核**；该差异由后续 **Linux CI** 跟踪，见 `docs/decisions/0002-wsl-only-t01-container-host.md`。

## 删除验收

环境删除必须满足：

- 只删除 `MiniOrangeOS-Dev` 或项目明确创建的容器资源；
- 删除前列出将删除的资源；
- 删除命令包含二次确认；
- 删除后其他 WSL 发行版、容器、镜像和项目文件仍可访问；
- 删除日志写入 `docs/problems.md` 或任务报告。
