# MiniOrangeOS

MiniOrangeOS 是一个 x86 32 位 BIOS 演示操作系统。项目包含两级启动链、高半 ELF32 内核、分页与内存管理、Ring 3 用户态、抢占式调度、`int 0x80` 系统调用、ATA PIO、可写 MiniFS、Shell、17 个静态用户程序，以及宿主/QEMU/CI 自动化测试。

## 已实现能力

- BIOS Legacy 启动，512-byte Stage 1 与 Stage 2，不依赖 GRUB；
- A20、E820、保护模式、ATA LBA28 PIO 与严格 ELF32 Loader；
- `0xC0000000` 高半内核、4 KiB 两级分页、PMM、VMM、first-fit Heap；
- GDT、IDT、TSS、异常、8259 PIC、100 Hz PIT、PS/2 键盘、COM1/VGA；
- Ring 3、独立地址空间、PIT 抢占式轮转、进程生命周期与用户故障隔离；
- 20 个 `int 0x80` 系统调用、VFS、每进程 fd 表与工作目录；
- 64 MiB 磁盘镜像、4 KiB block、可写 MiniFS、宿主 `mkfs`/`fsck`；
- `/bin/init`、`sh`、`echo`、`ps`、`memtest`、`fault`、`ls`、`cat`、`touch`、`write`、`edit`、`mkdir`、`rm`、`cp`、`stat`、`sleep`、`uptime`；
- 全量构建、测试、双启动持久化演示、代码量统计和 Linux CI。

项目未实现 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接、Swap、完整 POSIX、权限系统和文件系统日志。MiniFS 不保证任意掉电点的事务原子性；ATA 仅支持 primary master LBA28 PIO。

## 运行前提

推荐环境是 Windows 11 + WSL2。Windows 只保存唯一工作树并执行 Git；编译、QEMU、GDB 和测试全部在专用的 Ubuntu 24.04 WSL2 发行版 `MiniOrangeOS-Dev` 中完成。

需要满足：

- Windows 已启用 WSL2 和硬件虚拟化，可运行 `wsl.exe --status`；
- 使用 64 位 Windows PowerShell 5.1 或 PowerShell 7；
- 网络可访问 Ubuntu 与 GNU 官方下载源，首次安装会下载并构建固定版本工具链；
- 为 WSL rootfs、下载缓存和工具链预留至少约 15 GiB 空间；
- WSL 可通过 `/mnt/<drive>` 访问的 Windows 本地盘；仓库目录本身无需固定位置，并支持空格、`&`、`#`、`%`、`$`、单引号、括号等全部 Windows 合法路径字符。

`environment/wsl/create.ps1` 会从脚本位置找到仓库根目录，并自动推导对应的 WSL 路径。`environment/wsl/enter.ps1` 把该路径作为原始 argv 传入临时 mount namespace，在 `/run/miniorangeos-workspace` 安全短路径完成绑定后降权到 `minios` 执行；挂载随命令退出自动销毁，因此 GNU Make 和 Shell 不会重新解释原路径中的特殊字符，也不会产生第二份源码。WSL 发行版、下载缓存和备份仍需使用绝对路径以维持安全边界，该路径集中配置在 `config/wsl.psd1` 的 `AuthorizedRoot`；迁移环境时只需修改这一处并重新创建发行版。

## 首次安装

在 Windows PowerShell 中执行：

```powershell
git clone https://github.com/Double-Cloth/MiniOrangeOS.git
Set-Location .\MiniOrangeOS
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\environment\wsl\create.ps1 -Bootstrap
```

最后一条命令会：

1. 校验固定来源和 SHA-256；
2. 创建 WSL2 发行版 `MiniOrangeOS-Dev`；
3. 将发行版安装到 `config/wsl.psd1` 中 `AuthorizedRoot` 下的 `rootfs`；
4. 在发行版内安装系统依赖；
5. 在用户私有目录构建固定的 `i686-elf` Binutils 2.42、GCC 13.2.0 和 libgcc；
6. 写入并验证项目实例身份，不会修改 Windows PATH 或全局 Git 配置。

首次构建工具链耗时较长。脚本可重复执行；已有且可信的发行版会复用当前状态。

安装后验证：

```powershell
.\environment\wsl\enter.ps1 -Command './environment/verify.sh'
```

成功时结尾包含：

```text
result=PASS
```

如果已有旧版 `MiniOrangeOS-Dev`，只是缺少可信实例身份，并且明确不希望运行 apt 或重建工具链，可执行：

```powershell
.\environment\wsl\create.ps1 -DistroName MiniOrangeOS-Dev -SkipBootstrap
```

`-SkipBootstrap` 不是全新安装方式，只用于既有发行版的身份补建与校验。

## 启动和使用系统

### 交互运行

在 Windows PowerShell 中运行 VGA/键盘交互模式：

```powershell
.\environment\wsl\enter.ps1 -Command './environment/with-env.sh make run-curses'
```

该命令会在需要时构建 `build/miniorangeos.img`，然后用 QEMU 启动。系统完成自检后进入 MiniOrangeOS Shell。Shell 支持单引号、双引号、反斜杠转义、相对路径和最长 255 字节的输入行；可用退格、Delete、左右方向键、Home/End 编辑，使用上下方向键浏览最近 8 条命令，并支持 `Ctrl+A/E/C/D/K/L/U`。在首个命令词中按 `Tab` 会从内建命令和实时 `/bin` 目录补全；唯一候选自动追加空格，多个候选先扩展公共前缀，再次无法扩展时列出所有匹配项。可用命令：

| 命令 | 用途 | 示例 |
|---|---|---|
| `help` | 显示 Shell 帮助 | `help` |
| `clear` | 清屏 | `clear` |
| `pwd` | 显示当前工作目录 | `pwd` |
| `cd` | 切换工作目录，支持相对路径 | `cd /demo` |
| `echo` | 输出参数；`-n` 省略换行 | `echo "hello MiniOrangeOS"` |
| `ps` | 显示进程快照 | `ps` |
| `memtest` | 验证用户地址空间 | `memtest` |
| `ls` | 列出文件或目录；支持 `-a`、`-l` 和多路径 | `ls -l /bin` |
| `cat` | 顺序读取一个或多个文件；`-n` 显示连续行号 | `cat -n first second` |
| `touch` | 创建一个或多个空文件 | `touch first second` |
| `write` | 创建或覆盖文件；`-a` 追加，`-n` 省略末尾换行 | `write -a hello "more data"` |
| `edit` | 行式编辑文本，支持打印、追加、插入、替换、删除和保存 | `edit hello` |
| `mkdir` | 创建一个或多个目录 | `mkdir demo logs` |
| `rm` | 删除文件或空目录；`-f` 忽略不存在项 | `rm -f empty` |
| `cp` | 复制普通文件 | `cp hello backup` |
| `stat` | 显示类型、inode、链接数和大小 | `stat hello` |
| `sleep` | 按秒休眠当前命令 | `sleep 1` |
| `uptime` | 显示启动后的秒数与 tick | `uptime` |
| `fault` | 故意触发用户 page fault，验证进程隔离 | `fault` |
| `exit` | 退出当前 Shell | `exit` |
| `shutdown` | 关闭 MiniOrangeOS 并退出当前 QEMU | `shutdown` |

`edit` 启动后先显示带行号的当前内容。可使用 `p [first [last]]` 查看范围、`a [text]` 追加、`i line [text]` 插入、`r line [text]` 替换、`d line` 删除、`w` 保存、`q` 退出；存在未保存修改时，`q` 会拒绝退出，只有 `q!` 会明确丢弃。编辑器面向 ASCII 文本，接受换行和制表符，单个文件上限为 32 KiB。

验证持久化时，在第一次启动中执行：

```text
write /hello MiniOrangeOS persists
cat /hello
```

执行 `shutdown` 正常关闭 MiniOrangeOS 后，再次执行 `make run-curses` 并运行 `cat /hello`。默认 `build/miniorangeos.img` 未被 `make clean` 删除前，文件内容会保留。

如果系统无响应，仍可在另一个 PowerShell 窗口强制终止 QEMU：

```powershell
wsl.exe --terminate MiniOrangeOS-Dev
```

`shutdown` 与该命令都会结束当前 QEMU 运行；后者会同时强制停止发行版中的其他当前进程，但不会注销或删除环境。

### 串口运行

只查看权威串口日志时：

```powershell
.\environment\wsl\enter.ps1 -Command './environment/with-env.sh make run-serial'
```

串口模式适合观察 `[BOOT]`、`[KERN]`、`[MM]`、`[PROC]`、`[FS]`、`[TEST]` 和 `[PANIC]` 日志；交互输入仍建议使用 `run-curses`。

### 仅构建镜像

```powershell
.\environment\wsl\enter.ps1 -Command './environment/with-env.sh make -j4 image'
```

主要产物位于 `build/`：

- `build/miniorangeos.img`：64 MiB 可启动原始磁盘镜像；
- `build/kernel/kernel.elf`：带符号 ELF32 高半内核；
- `build/fs/minifs.img`：独立 MiniFS 卷；
- `build/user/bin/*.elf`：17 个用户程序。

可以通过 `BUILD_DIR` 使用独立输出目录：

```bash
./environment/with-env.sh make BUILD_DIR=.local-build -j4 image
```

构建目录由安全 marker 约束；不要手工复制 marker，也不要把 `BUILD_DIR` 指向源码目录或仓库外目录。

## 调试

终端一启动暂停在入口并监听本机 `1234` 端口：

```bash
./environment/with-env.sh make debug
```

另一个 Windows PowerShell 连接 GDB：

```powershell
.\environment\wsl\enter.ps1 -Command './environment/with-env.sh make gdb'
```

可通过 `GDB_ENDPOINT=tcp:127.0.0.1:端口` 覆盖端口，但只允许本地回环地址。

## 测试和演示

进入项目目录后使用以下公开入口：

| 命令 | 作用 |
|---|---|
| `./environment/verify.sh` | 验证发行版、固定版本、工具来源和污染边界 |
| `./environment/with-env.sh make check` | 构建镜像并运行只读 MiniFS `fsck` |
| `./environment/with-env.sh make test-host` | 运行全部宿主和真实 QEMU unittest |
| `./environment/with-env.sh make test` | 聚合环境验证、镜像检查和全量测试 |
| `./environment/with-env.sh make test-qemu` | 验证通用串口/debug-exit runner |
| `./environment/with-env.sh make test-boot-qemu` | 验证正式启动链与故障注入路径 |
| `./environment/with-env.sh make test-image` | 检查镜像并运行 MiniFS 工具测试 |
| `./environment/with-env.sh make demo-persistence` | 用临时镜像完成两次启动和持久化闭环 |
| `./environment/with-env.sh make loc` | 按来源边界统计代码量 |

完整 `make test` 会构建工具链产物并多次启动 QEMU，耗时可能较长。只有命令真实返回 0 且输出 PASS，才能视为通过。

## 可选的 Ubuntu OCI 复验

项目还支持在具备 rootless Podman（优先）或 Docker 的 Ubuntu 24.04 环境中，用固定的 rootless OCI 路径复验：

```bash
./environment/ubuntu/create.sh
./environment/ubuntu/run.sh ./environment/verify.sh
./environment/ubuntu/run.sh ./environment/with-env.sh make test
```

源码以 `/source:ro` 只读挂载，容器会复制到临时可写工作区后构建，不会把容器构建产物写回工作树。

清理容器环境时先预览，再执行：

```bash
./environment/ubuntu/destroy.sh
./environment/ubuntu/destroy.sh --all
```

无参数只预览且不删除任何资源；只有 `--all` 才会在 state、镜像 ID、标签、intent 和专用 storage 全部验证后定向删除。禁止用 `podman system prune -a` 或 `docker system prune -a` 代替。

## 清理构建产物

在 WSL 项目目录中执行：

```bash
./environment/with-env.sh make clean
```

指定过 `BUILD_DIR` 时必须使用同一个值：

```bash
./environment/with-env.sh make BUILD_DIR=.local-build clean
```

`clean` 和当前 `distclean` 都只删除通过仓库身份与 marker 校验的目标构建目录；未知目录、符号链接、复制 marker 或目录替换会被拒绝。

## 备份与卸载

卸载分成“项目环境”“构建产物”和“源码”三部分。下面的命令不会删除其他 WSL 发行版或全局容器资源。

### 1. 可选备份

在仓库根目录的 Windows PowerShell 中：

```powershell
.\environment\wsl\backup.ps1
```

备份默认写入 `${AuthorizedRoot}\exports\MiniOrangeOS-Dev-时间戳.tar`，其中 `AuthorizedRoot` 来自 `config/wsl.psd1`。脚本会终止当前发行版再导出，请先保存工作。

### 2. 清理可选 OCI 环境

如果曾执行 `environment/ubuntu/create.sh`，先在 WSL 中运行：

```bash
./environment/ubuntu/destroy.sh
./environment/ubuntu/destroy.sh --all
```

### 3. 清理仓库构建产物

```powershell
.\environment\wsl\enter.ps1 -Command './environment/with-env.sh make clean'
```

### 4. 注销专用 WSL 发行版

先预览；预览不会删除任何内容：

```powershell
.\environment\wsl\destroy.ps1
```

确认输出只指向 `MiniOrangeOS-Dev` 和 `${AuthorizedRoot}\rootfs` 后，再执行删除：

```powershell
.\environment\wsl\destroy.ps1 -Apply -ConfirmName MiniOrangeOS-Dev
```

验证发行版已删除、其他发行版仍存在：

```powershell
wsl.exe --list --verbose
```

该脚本会定向执行 `wsl.exe --unregister MiniOrangeOS-Dev`，并只在 rootfs 目录已经为空时删除该目录；它会保留下载缓存和 `exports` 备份。

### 5. 可选删除环境缓存和备份

仅在已经确认不再需要任何导出备份后执行。以下保护检查要求路径精确等于项目授权根：

```powershell
$Config = Import-PowerShellDataFile -LiteralPath .\config\wsl.psd1
$Root = [IO.Path]::GetFullPath($Config.AuthorizedRoot)
$VolumeRoot = [IO.Path]::GetPathRoot($Root)
if ($Root -cne $Config.AuthorizedRoot -or $Root.TrimEnd('\') -ceq $VolumeRoot.TrimEnd('\')) {
    throw "AuthorizedRoot 必须是规范绝对路径且不能是卷根目录：$Root"
}
Get-ChildItem -LiteralPath $Root -Force
Remove-Item -LiteralPath $Root -Recurse -Force
```

不要把此命令改成更上层目录，也不要在仍需恢复备份时执行。

### 6. 删除源码

先推送或备份需要保留的提交，并退出项目目录。然后从父目录精确删除工作树：

```powershell
Set-Location ..
Remove-Item -LiteralPath .\MiniOrangeOS -Recurse -Force
```

只卸载运行环境时不要执行这一步；源码本身不依赖注册表、Windows PATH 或系统服务，可以单独保留。

## 文档

- [`docs/PROJECT.md`](docs/PROJECT.md)：总体架构、启动链、内存、进程、系统调用和 MiniFS；
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)：开发边界、编码规范、构建测试、CI、贡献和发布流程；
- [`docs/HISTORY.md`](docs/HISTORY.md)：T00-P7 开发历程、问题修复、来源、验收证据和已知限制。

## License

[MIT](LICENSE)
