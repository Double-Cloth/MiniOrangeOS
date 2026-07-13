# T01 隔离环境生命周期和交叉工具链设计

日期：2026-07-13
状态：已批准。用户已授权在既定项目计划、Windows 权威工作树和 WSL 测试边界内自主决定后续步骤。

## 1. 目标

T01 把 T00 的一次性手工环境转换为可重复、可验证、可备份和可定向删除的项目能力：

- Windows 只负责权威工作树、Windows Git 和 WSL 生命周期入口；
- `MiniOrangeOS-Dev` 负责日常 Linux 构建、QEMU、GDB 和测试；
- 真实 Ubuntu 复验使用 rootless Podman，或用户已经安装的 Docker；
- `i686-elf` Binutils/GCC 从固定源码构建，安装到 `$MINIOS_ENV_ROOT/toolchain`；
- 不修改 Windows PATH、注册表、全局 Git、Linux Shell 启动文件或宿主 `/usr/local`；
- 所有删除操作先预览，只能命中 MiniOrangeOS 明确命名和路径边界内的资源。

T01 不创建操作系统功能代码，不实现 Makefile、镜像构建或 QEMU 测试框架；这些属于 T02 及以后任务。

## 2. 方案选择

### 2.1 采用源码构建裸机交叉工具链

选择 Binutils 2.42 和 GCC 13.2.0，仅构建 `i686-elf` 裸机目标与 C 前端。

未采用以下方案：

- Ubuntu 的 `gcc-i686-linux-gnu`：目标是 Linux ABI，不是 `i686-elf` 裸机 ABI；
- 未经项目校验的预编译工具链：无法满足固定来源、SHA-256 和自主构建证据；
- Windows 原生工具链：违反已接受的 Windows/WSL 边界。

Binutils 和 GCC 共用 `tools/build_toolchain.sh`，WSL 与容器不得维护两份实现。

### 2.2 系统依赖留在隔离环境内部

`make`、宿主 GCC/G++、Bison、Flex、GMP/MPFR/MPC 开发库、NASM、QEMU、GDB、Python 等通过 Ubuntu 24.04 包管理器安装：

- 在 WSL 中，包只写入 `MiniOrangeOS-Dev` 的 VHDX；该 VHDX 位于 `D:\ApplicationData\MiniOrangeOS`；
- 在容器中，包只写入带项目标签的镜像层；
- 不在 Windows 或真实 Ubuntu 宿主直接安装这些包。

Ubuntu 包的实际版本写入 `$MINIOS_ENV_ROOT/state/apt-packages.lock` 和环境指纹。交叉工具链源码版本、URL 与 SHA-256 使用仓库内锁文件严格固定。

### 2.3 统一脚本，分离生命周期适配层

核心 Linux 脚本：

- `environment/bootstrap-inside.sh`：安装隔离环境系统依赖、创建目录并调用工具链构建；
- `tools/build_toolchain.sh`：下载、校验、构建和安装 `i686-elf` 工具链；
- `environment/with-env.sh`：只为单条命令临时注入 PATH；
- `environment/verify.sh`：输出稳定指纹并执行环境边界检查。

Windows WSL 适配层：

- `environment/wsl/create.ps1`：安全下载/校验/导入、配置用户和 metadata 挂载，并可重复 bootstrap；
- `enter.ps1`：只进入已存在发行版；
- `backup.ps1`：终止目标发行版后定向导出到授权 `exports`；
- `destroy.ps1`：默认只预览，要求显式 `-Apply` 和发行版名确认后才注销。

真实 Ubuntu 容器适配层：

- `environment/ubuntu/create.sh`：选择 rootless Podman 或已有 Docker，构建固定镜像；
- `run.sh`：用临时容器运行命令，挂载当前工作树；
- `destroy.sh --all`：只删除项目标签匹配的容器和固定镜像，不执行全局 prune。

## 3. 固定来源

锁文件使用纯 `KEY=VALUE` 格式，Shell 可直接 source，PowerShell 通过严格解析器读取。

| 资源 | 固定值 |
|---|---|
| WSL 根文件系统 | Ubuntu 24.04.4 `ubuntu-24.04.4-wsl-amd64.wsl` |
| WSL URL | `https://releases.ubuntu.com/24.04/ubuntu-24.04.4-wsl-amd64.wsl` |
| WSL SHA-256 | `9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5` |
| 容器基础镜像 | `ubuntu:noble-20260509.1` |
| 容器 manifest digest | `sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54` |
| Binutils | 2.42，`https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz` |
| Binutils SHA-256 | `f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800` |
| GCC | 13.2.0，`https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz` |
| GCC SHA-256 | `e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da` |

下载先写入同目录 `.partial` 文件，SHA-256 完全匹配后原子改名。任何哈希不匹配都必须停止，不能继续解包或构建。

## 4. 环境根和状态布局

WSL 默认：

```text
/home/minios/.local/share/miniorangeos-dev/
├── downloads/
├── sources/
├── build/
├── toolchain/
├── logs/
└── state/
```

容器使用 `/opt/miniorangeos-dev`。两个环境都通过显式 `MINIOS_ENV_ROOT` 覆盖，不允许环境根为空、为 `/`、`/usr`、`/usr/local`、用户 home 本身或仓库工作树。

工具链完成标记记录版本、哈希、target、prefix、配置参数和安装工具版本。只有标记与锁文件一致，且 `i686-elf-gcc`、`i686-elf-ld` 自检成功时才允许跳过重建。

## 5. 工具链构建契约

Binutils 配置：

```text
--target=i686-elf
--prefix=$MINIOS_ENV_ROOT/toolchain
--with-sysroot
--disable-nls
--disable-werror
```

GCC 配置：

```text
--target=i686-elf
--prefix=$MINIOS_ENV_ROOT/toolchain
--disable-nls
--enable-languages=c
--without-headers
--disable-multilib
--disable-shared
--disable-threads
```

只构建并安装 `all-gcc`、`all-target-libgcc`、`install-gcc` 和 `install-target-libgcc`。构建并行度默认为 `nproc`，允许 `MINIOS_BUILD_JOBS` 显式覆盖。

## 6. 验证契约

`environment/verify.sh` 必须：

1. 确认 Ubuntu 24.04；
2. 确认当前是 `MiniOrangeOS-Dev`，或 `MINIOS_CONTAINER=1` 的项目容器；
3. 确认工具链命令解析到 `$MINIOS_ENV_ROOT/toolchain/bin`；
4. 确认 GCC target 为 `i686-elf`，并实际编译一个 freestanding C 对象；
5. 确认 NASM、QEMU、GDB、Python 可识别；
6. 拒绝 `/usr/local/bin/i686-elf-*` 等全局污染；
7. 输出稳定的 `key=value` 环境指纹和 `result=PASS`。

`with-env.sh` 不修改调用者 Shell，只通过当前进程的 PATH 执行传入命令；无命令、工具链缺失或环境根越界时返回非零。

## 7. 生命周期安全

### 7.1 WSL

- 允许的正式发行版名只有 `MiniOrangeOS-Dev`；测试演练名必须以 `MiniOrangeOS-Dev-Test-` 开头；
- 安装目录必须解析到 `D:\ApplicationData\MiniOrangeOS` 内；
- 已存在正式发行版时，`create.ps1` 只验证和重复 bootstrap，不覆盖；
- `destroy.ps1` 默认只打印计划；执行要求 `-Apply -ConfirmName <exact-name>`；
- 禁止调用 `wsl --shutdown`，只允许 terminate/unregister 精确目标；
- 删除演练使用临时测试发行版，不注销正式 `MiniOrangeOS-Dev`。

### 7.2 容器

- 固定标签 `org.miniorangeos.project=MiniOrangeOS`；
- 固定镜像名 `miniorangeos-dev:ubuntu-24.04`；
- `destroy.sh` 只处理固定镜像和相同标签的容器；
- 默认只预览，只有 `--all` 才执行完整项目清理；
- 禁止 `podman system prune`、`docker system prune` 和无标签批量删除。

## 8. 测试策略

### 8.1 静态和主机契约测试

Python 标准库测试检查：

- 锁文件字段、URL、SHA-256 形状和脚本路径；
- Shell 严格模式、环境根边界和禁止命令；
- PowerShell 的精确发行版名、路径约束、预览/确认门；
- Containerfile 的固定 digest 和项目标签；
- 文档与实现路径一致。

### 8.2 WSL 集成测试

- 在现有 `MiniOrangeOS-Dev` 中执行 bootstrap；
- 首次构建与第二次幂等执行均成功；
- `verify.sh`、`with-env.sh i686-elf-gcc --version`、`with-env.sh i686-elf-ld --version` 成功；
- 实际备份到授权目录；
- 用 `MiniOrangeOS-Dev-Test-*` 临时发行版完成 destroy 演练，并证明 `docker-desktop` 与正式发行版仍存在。

### 8.3 容器集成测试

- 不自动安装容器运行时；
- 使用已有 rootless Podman，或显式选择已有 Docker；
- `create.sh` 构建固定镜像；
- `run.sh ./environment/verify.sh` 成功；
- `destroy.sh --all` 后项目容器和镜像消失，其他资源不变。

## 9. 文档与 Git

T01 使用 `feature/T01-environment-toolchain`，独立提交测试、锁文件/公共脚本、WSL 生命周期、容器适配、文档与报告。全部 WSL/容器验证和回归通过后，才允许推送并以 `--no-ff` 合并到 `main`。

需同步：`docs/environment.md`、`docs/testing.md`、`docs/provenance.md`、`docs/problems.md`、`docs/progress.md`、`docs/review-notes.md` 和 `docs/task-reports/T01-environment-toolchain.md`。
