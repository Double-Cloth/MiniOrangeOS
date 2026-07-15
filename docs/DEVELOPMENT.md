# MiniOrangeOS 开发指南

本文汇总原贡献规范、编码规范、开发流程、环境设计、测试策略和发布清单。项目架构见 `docs/PROJECT.md`，运行与卸载见根目录 `README.md`，历史过程见 `docs/HISTORY.md`。

## 工作树与执行边界

唯一工作树是 Windows 仓库根目录，不要求固定盘符或父目录，即：

```text
<任意本地目录>\MiniOrangeOS
```

WSL 中通过脚本自动推导的 `/mnt/<drive>/.../MiniOrangeOS` 访问同一工作树。不要在代码或文档中写死仓库绝对路径。

固定规则：

- 文件编辑和 Git 只在 Windows 工作树执行，Git 只由 Windows 执行；
- `MiniOrangeOS-Dev` 只负责 Linux 构建、QEMU、GDB 和测试；
- 禁止在 WSL 中运行 Git，也不维护第二份活动工作树；
- Windows 不需要安装项目专用 GCC、NASM、Make、QEMU、GDB、MSYS2、Cygwin 或 MinGW；
- 项目环境不修改 Windows PATH、注册表、全局 Git 配置和 Linux 全局 Shell 配置；
- `/mnt/d` 的性能、大小写、权限和 inode 语义通过 `.gitattributes`、WSL metadata 和运行时测试持续约束。

项目环境载荷需要绝对路径以校验 WSL ownership，唯一配置入口为 `config/wsl.psd1`：

```powershell
@{ AuthorizedRoot = '<WSL 环境绝对路径>' }
```

Linux 用户私有工具根默认为：

```text
${XDG_DATA_HOME:-$HOME/.local/share}/miniorangeos-dev
```

不得把项目载荷写入 Windows PATH、Linux `/usr/local`、全局 Shell 配置、系统 Python site-packages 或与项目无关的容器资源。

路径规则按用途区分：仓库内文件一律由仓库根拼接相对路径；宿主仓库位置由脚本动态推导；可迁移但必须绝对的 WSL 授权根只写入 `config/wsl.psd1`。`/proc`、`/etc`、`/usr/bin`、`HKCU:\Software\...` 等操作系统 ABI、安全校验入口，以及 MiniOrangeOS 自身的 `/bin` 路径不属于宿主机器安装位置，继续使用其规范绝对路径，不放入项目路径配置。

## 环境公开接口

| 文件 | 职责 |
|---|---|
| `config/wsl.psd1` | 集中配置必须保持绝对形式的 WSL 授权根 |
| `environment/wsl/common.ps1` | 从脚本位置解析仓库根、加载路径配置并推导 WSL 路径 |
| `environment/wsl/create.ps1` | 定向创建/复用 `MiniOrangeOS-Dev`，可执行 bootstrap 或身份迁移 |
| `environment/wsl/enter.ps1` | 校验 ownership 后进入发行版或执行单个 `bash -lc` 命令 |
| `environment/wsl/backup.ps1` | 终止并导出专用发行版到授权根 `exports` |
| `environment/wsl/destroy.ps1` | 默认预览；精确确认后只注销专用发行版 |
| `environment/Containerfile` | 固定 Ubuntu 24.04 OCI 开发镜像 |
| `environment/ubuntu/create.sh` | 创建并记录 rootless OCI 项目资源 |
| `environment/ubuntu/run.sh` | 只读挂载源码，在临时可写副本运行命令 |
| `environment/ubuntu/run-inside.sh` | 容器内部复制与 argv 边界入口，不直接从宿主调用 |
| `environment/ubuntu/destroy.sh` | 默认预览；`--all` 定向清理已验证项目资源 |
| `environment/ubuntu/ci-run.sh` | CI 聚合执行并导出失败证据 |
| `environment/bootstrap-inside.sh` | 两阶段安装系统依赖与固定工具链 |
| `environment/with-env.sh` | 仅为当前子进程注入工具链和 venv PATH |
| `environment/verify.sh` | 验证发行版/容器身份、版本、路径和污染边界 |
| `environment/versions.env` | 固定外部来源、版本、digest 与 SHA-256 |
| `tools/build_toolchain.sh` | 构建 `i686-elf` Binutils/GCC/libgcc |

常用 Windows 入口：

```powershell
environment/wsl/create.ps1 -Bootstrap
environment/wsl/enter.ps1
environment/wsl/enter.ps1 -Command './environment/verify.sh'
environment/wsl/backup.ps1
environment/wsl/destroy.ps1
environment/wsl/destroy.ps1 -Apply -ConfirmName MiniOrangeOS-Dev
```

常用 Linux/WSL 入口：

```bash
./environment/bootstrap-inside.sh
./environment/with-env.sh i686-elf-gcc --version
./environment/verify.sh
./environment/ubuntu/create.sh
./environment/ubuntu/run.sh ./environment/verify.sh
./environment/ubuntu/destroy.sh
./environment/ubuntu/destroy.sh --all
```

容器销毁无参数只预览且不删除任何资源；只有 `--all` 才执行定向清理。WSL 销毁同样默认只预览，必须同时提供 `-Apply` 和大小写精确的 `-ConfirmName MiniOrangeOS-Dev`。禁止使用无范围的 `system prune` 或删除整个 `$HOME/.local/share`。

`environment/wsl/enter.ps1 -Command` 会先切换到自动推导的仓库根目录，再执行单个 `bash -lc` 命令，因此公开命令和文档都应使用仓库相对路径。

## 开发流程

每项变更按以下流程推进：

1. 阅读根目录规范、`docs/PROJECT.md` 中相关实现和本指南；
2. 检查 Windows Git 分支与工作树；
3. 从 `main` 创建有意义的功能分支；
4. 先建立可执行验收或补充关键测试，再做最小实现；
5. 在 `MiniOrangeOS-Dev` 运行受影响测试和必要回归；
6. 同步项目、开发或历史文档；
7. 检查 diff、文本策略、未解释文件和构建产物；
8. 提交，验证通过后再合并。

不得直接在 `main` 上开发，不得用大延时、关闭断言、跳过测试或伪造串口标记掩盖缺陷。

### 分支与提交

建议分支名表达目标，例如：

```text
feature/virtual-memory
fix/minifs-truncate
docs/runtime-guide
```

提交格式：

```text
type(scope): summary
```

允许的常用 type：`feat`、`fix`、`test`、`refactor`、`docs`、`build`、`chore`。

提交正文应说明变更原因、关键设计和真实测试范围。只有测试通过、文档同步且工作区无未解释内容时，才可推送并合并；失败或未运行项必须如实记录。

### 变更记录模板

```text
目标：
分支：
提交：

修改文件：
- ...

关键实现：
- ...

执行命令：
- ...

测试结果：
- PASS/FAIL/未运行：...

未解决问题：
- 无 / ...

文档同步：
- ...
```

不再为每个函数或微步骤建立独立长报告；稳定历史集中维护在 `docs/HISTORY.md`。

## 编码规范

### 通用

- 全部文本使用 UTF-8 与 LF，包括 PowerShell；
- 文档和代码注释使用中文；标识符、文件名、命令、配置项和第三方 API 保持英文；
- 单个模块承担单一职责，跨模块依赖通过公开头文件；
- 优先简单、直接、可维护的实现，不擅自引入框架、依赖或复杂抽象；
- 更改磁盘 ABI、用户 ABI、启动合同或公开 Make 目标时，必须同步测试与文档。

### C11 Freestanding

- 文件名、函数名使用 `snake_case`；类型名带模块前缀；宏和常量使用 `UPPER_SNAKE_CASE`；
- 公开函数有原型，内部函数声明为 `static`；
- 使用 `<stdint.h>`、`<stddef.h>` 定宽类型，不用普通 `int` 序列化磁盘地址和结构字段；
- 指针、长度、LBA、block、页号和 `offset + size` 运算必须检查溢出；
- 不依赖宿主 libc、Linux ABI、动态链接器或 hosted C 行为；
- 内核 API 失败返回负错误码；panic 仅用于不可恢复的内核不变量。

### NASM

- 使用 Intel 语法，标签使用 `snake_case`；
- 入口、调用约定、寄存器所有权、段状态和栈布局在相邻中文注释中说明；
- 魔数、选择子、端口号、向量号和结构偏移使用命名常量；
- 16 位实模式、32 位保护模式和用户返回路径必须显式标明位宽与边界。

### Python、Shell 与 PowerShell

- Python 磁盘工具显式使用 little-endian 编解码，不依赖对象内存布局；
- Shell 脚本使用 `set -euo pipefail`，保留 argv 边界，对路径和外部输入加引号；
- PowerShell 删除/移动前使用 `-LiteralPath`、解析绝对路径并检查授权根；
- 安全敏感路径优先使用 dirfd/nofollow、稳定 identity 和原子替换；
- 测试 hook 只能在明确测试模式下使用，生产入口拒绝调用者伪造身份变量。

## 构建系统

所有 Linux 命令应通过环境注入执行：

```bash
./environment/with-env.sh make -j4 image
```

公共目标：

| 目标 | 说明 |
|---|---|
| `all` | 构建 Boot、Loader、Kernel、用户 ELF、MiniFS 与镜像相关产物 |
| `image` | 构建 `miniorangeos.img` |
| `user` | 构建 16 个用户 ELF、map 和 symbol |
| `run-serial` | 无显示窗口运行，串口连接当前终端 |
| `run-curses` | curses VGA/PS2 键盘交互运行 |
| `debug` | QEMU 在启动入口暂停并开启 GDB remote |
| `gdb` | 用 `kernel.elf` 连接本地 GDB endpoint |
| `check` | 构建完整镜像并运行只读 fsck |
| `test-host` | 运行宿主 unittest discovery |
| `test` | 环境验证 + `check` + `test-host` |
| `test-qemu` | 测试通用串口/debug-exit runner |
| `test-boot-qemu` | 测试真实启动成功与故障路径 |
| `test-image` | fsck + MiniFS 工具测试 |
| `demo-persistence` | 两次真实启动和逐轮 fsck |
| `loc` | 按来源类别统计物理行 |
| `clean` / `distclean` | 删除通过 marker 验证的指定构建目录 |

`config/image-layout.json` 是磁盘布局唯一机器可读来源。Stage 1/2 include、MiniFS C header 和镜像工具输入都从该文件产生，不允许在多个模块手写漂移常量。

`BUILD_DIR` 可以覆盖，但必须在仓库内且不能指向源码目录。构建守卫会拒绝未知目录、复制 marker、symlink、特殊文件、hardlink、越界路径或校验后替换。

## 测试策略

### 分层

1. 静态/合同测试：文件布局、ABI、Make 目标、脚本安全边界；
2. 宿主运行时测试：构建增量、清理、镜像、MiniFS、环境生命周期；
3. QEMU 框架测试：串口协议、debug-exit、超时、进程清理；
4. 正式镜像测试：BIOS 到用户态、异常与损坏输入；
5. 持久化测试：临时镜像双启动，每次写入后宿主 fsck；
6. Linux CI：固定 Ubuntu 24.04 容器复跑聚合入口并保留失败证据。

阶段内可先运行局部测试，但交付前至少执行：

```powershell
.\environment\wsl\enter.ps1 -Command './environment/with-env.sh make test'
```

### 串口协议

自动化只依赖串口，不依赖 VGA 截图。协议固定为：

```text
[TEST] suite=test_name begin
[TEST] case=case_name PASS
[TEST] case=case_name FAIL code=...
[TEST] suite=test_name PASS
[TEST] all PASS
```

成功必须同时满足：状态顺序完整、没有 FAIL、QEMU 真实退出、debug-exit 状态正确、没有超时和残留进程。看到局部 PASS 不代表整体成功。

失败日志应包含 suite、case、错误码、关键参数、tick、PID；异常相关项还应包含 CR2、EIP、vector/error code 或 fd/path。

### 关键负面测试

- 启动：读盘失败、LBA 越界、ELF 魔数/header/segment 越界、覆盖 Loader、E820 溢出；
- 内存：页耗尽、重复释放、映射冲突、跨越 `0xC0000000`、只读页写、未映射页、Heap double free；
- 进程：三进程抢占、sleep、非法 wait、用户 page fault 隔离、退出资源回收；
- syscall：未知编号、fd 越界、close 后使用、路径/argv 超限、用户缓冲跨页；
- 文件系统：磁盘/inode 耗尽、direct/indirect 边界、截断复用、非空目录删除、坏 CRC、bitmap 不一致、重启持久化；
- 工具：危险 `BUILD_DIR`、symlink/hardlink/FIFO、目录替换、失败原子性和进程树清理。

### 完成声明

只有实际执行且返回 PASS，才能写“通过”。无法运行时必须记录：

```text
未运行：原因
风险：该测试覆盖的缺陷可能未暴露
下一步：具体命令或任务
```

不得用“理论上可行”、“应当通过”等替代测试证据。

## CI 与失败证据

`.github/workflows/ci.yml` 使用 `ubuntu-24.04`，只授予 `contents: read`。`actions/checkout` 与 `actions/upload-artifact` 均固定完整提交 SHA，基础镜像固定 tag + digest。

CI 流程：

```text
build fixed environment image
  -> mount checkout as /source:ro
  -> copy to temporary writable workspace
  -> environment/verify.sh
  -> ./environment/with-env.sh make test
  -> export evidence on failure
```

失败证据包含完整构建/测试输出、QEMU 实际命令行、残留串口日志、镜像布局和镜像 SHA-256；失败时上传并保留 14 天，成功路径不生成失败 artifact。

WSL2 rootless OCI 集成曾在独立 `MiniOrangeOS-Dev-Test-ContainerHost`（Ubuntu 24.04 WSL2、rootless Podman）真实验证，但 Microsoft WSL2 内核不等于原生 Linux 内核。原生 Linux 内核差异由后续 GitHub Linux CI 补齐；两类证据必须明确区分。

## 来源与自主实现边界

允许参考 Intel/BIOS/ATA/ELF/工具官方文档和教材概念；禁止复制 Orange'S、xv6、Minix 或其他教学 OS 源码后改名。第三方工具和固定来源不计入自主核心代码。

变更涉及新外部输入时，应在 `docs/HISTORY.md` 的来源表登记版本、URL/digest、用途和是否包含外部代码。`make loc` 必须区分 Boot/Loader、内核 C/ASM、共享 ABI、用户程序/libc、工具、测试、文档、构建配置、自动生成和第三方文件。

## 发布检查

发布前逐项确认：

### 环境与来源

- [ ] `environment/verify.sh` 在正式 `MiniOrangeOS-Dev` 中 PASS；
- [ ] `environment/versions.env` 的 Ubuntu、Binutils、GCC、OCI 来源与哈希已复核；
- [ ] CI action 使用完整 SHA，权限仍为 `contents: read`；
- [ ] 新增外部来源已登记。

### 构建与测试

- [ ] `make clean` 后 `make -j4 image` PASS；
- [ ] `make test` PASS；
- [ ] `make test-image` PASS；
- [ ] `make demo-persistence` 两次启动和逐轮 fsck PASS；
- [ ] `make loc` 能生成完整分类；
- [ ] 关键产物大小/SHA-256 和 CI run 已记录。

### 文档与交付

- [ ] `README.md` 的安装、运行、命令和卸载步骤与脚本一致；
- [ ] `docs/PROJECT.md` 与代码/ABI/限制一致；
- [ ] `docs/HISTORY.md` 已记录真实提交、测试、问题和未解决边界；
- [ ] 工作树无构建产物、临时实验、审查缓存和无用途占位文件；
- [ ] 没有把 QEMU/WSL/容器结果表述为真实裸机证据。
