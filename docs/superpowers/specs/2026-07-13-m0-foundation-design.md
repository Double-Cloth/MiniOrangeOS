# M0 工程基础设计规格

> 日期：2026-07-13
> 状态：已确认设计
> 覆盖范围：T00、T01、T02、T03
> 对应里程碑：M0

## 1. 背景与目标

当前仓库只有项目计划书和前置专题文档，尚无工程骨架、环境脚本、构建系统或可执行代码。M0 的目标是建立后续所有功能任务共同依赖的工程基础：

- 建立可审计的仓库结构和工程规范；
- 创建集中、可验证、可定向删除的 Ubuntu 24.04 WSL2 测试环境；
- 构建隔离的 i686-elf 交叉工具链；
- 建立最小 GNU Make 构建链和原始磁盘镜像；
- 建立 QEMU 串口、测试超时、PASS/FAIL 和 GDB 调试框架；
- 建立任务分支、提交、测试、文档、心得和合并闭环。

M0 不实现 Boot Sector、Loader、内核子系统或用户程序功能。启动链功能从 T10 开始。

## 2. 权威工作树与环境决策

用户明确要求保留 Windows 项目目录作为唯一权威工作树，只在 WSL 中执行 Linux 构建、QEMU、GDB 和测试。该要求覆盖计划书中“工作树必须位于 WSL ext4”的原约束。

权威工作树：

    D:\DC\program-projects\OTHER\MiniOrangeOS

WSL 内映射路径：

    /mnt/d/DC/program-projects/OTHER/MiniOrangeOS

环境集中目录：

    D:\ApplicationData\MiniOrangeOS

目录布局：

    D:\ApplicationData\MiniOrangeOS\
    ├── rootfs\
    ├── downloads\
    ├── exports\
    └── logs\

执行边界：

- Codex 在 Windows 权威工作树中编辑源码和文档；
- Git 只由 Windows Git 操作，不使用 WSL Git 操作同一工作树；
- Linux 构建、QEMU、GDB 和测试只在 MiniOrangeOS-Dev 中执行；
- WSL 中不克隆第二份活动仓库；
- .gitattributes 强制源码、脚本和配置文件使用 LF；
- Shell 脚本的 Git 可执行位显式维护；
- 构建性能和 Linux 权限语义受 /mnt/d 限制，该限制作为已接受的工程取舍记录。

## 3. M0 组件

### 3.1 T00：仓库与工程规范

T00 建立后续任务需要的顶层目录和基础文件，但不加入功能实现。

主要产物：

- boot、kernel、user、tools、tests、environment 等目录骨架；
- .gitignore、.gitattributes、LICENSE、README.md、CONTRIBUTING.md；
- C11 freestanding、NASM Intel 语法、命名、错误码和类型约定；
- docs/progress.md、docs/review-notes.md、docs/task-reports；
- Windows 工作树与 WSL 测试模式的正式决策记录。

### 3.2 T01：隔离环境生命周期

T01 提供以下能力：

- 创建和注册 MiniOrangeOS-Dev；
- 从 Ubuntu 官方来源获取 Ubuntu 24.04 rootfs 并校验 SHA-256；
- 创建普通用户 minios；
- 安装或构建项目隔离依赖；
- 将 i686-elf 工具链安装到项目专用工具根目录；
- 临时注入 PATH 和构建变量，不修改全局 Shell 配置；
- 输出环境指纹；
- 备份、预览清理、确认后定向删除和删除后验证。

WSL 首次创建属于仓库脚本尚不存在时的一次性引导。T01 完成后必须使用已实现脚本演练环境删除和重建，从而证明生命周期脚本可以接管后续操作。

### 3.3 T02：最小构建系统

T02 创建 GNU Make 构建系统，产出最小 Boot、Loader、Kernel 占位二进制和原始磁盘镜像，但不要求能够完成正式启动。

构建必须：

- 只在 build 目录生成对象和产物；
- 支持并行构建；
- 生成正确依赖文件；
- 支持 clean 和 distclean；
- 第二次增量构建不重编译无关目标；
- 使用统一镜像布局配置；
- 失败时返回非零状态并保留可定位日志。

### 3.4 T03：QEMU 自动化与调试框架

T03 提供：

- run-serial、run-curses、debug 和 gdb 入口；
- 无界面 QEMU 测试入口；
- 串口日志捕获；
- 固定的 TEST PASS/FAIL 协议；
- 成功、失败、超时和子进程清理处理；
- 只绑定隔离环境回环地址的 GDB 端口。

T03 先验证测试框架本身，不提前实现 T10 的正式 Boot Sector 功能。

## 4. 数据流

日常执行链：

    Windows 权威工作树
      → wsl.exe -d MiniOrangeOS-Dev
      → /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
      → environment/with-env.sh
      → GNU Make
      → build/
      → QEMU / GDB / 宿主测试
      → build/test-logs/
      → 任务报告与测试摘要

环境创建链：

    官方 Ubuntu 24.04 rootfs
      → downloads/
      → SHA-256 校验
      → WSL2 注册 MiniOrangeOS-Dev
      → rootfs/
      → 普通用户 minios
      → 项目隔离工具根目录
      → environment/verify.sh

Git 不进入 WSL 数据流，避免 Windows Git 与 WSL Git 同时操作 NTFS 工作树。

## 5. Git 工作流

每个 TXX 任务使用独立分支：

    main
      └── feature/TXX-short-description

固定流程：

1. 确认 main 已同步且工作区干净；
2. 创建任务分支；
3. 先提交测试或验收约束，再提交最小实现；
4. 同步专题文档、来源登记、问题记录、任务报告和开发心得；
5. 在 WSL 中执行任务测试和已有回归测试；
6. 推送任务分支；
7. 通过验收后使用 --no-ff 合并到 main；
8. 推送 main 并删除已合并任务分支；
9. 里程碑完成后创建 annotated tag。

提交格式：

    type(scope): summary

    变更原因与关键设计说明

    Refs: TXX

测试未运行或失败时可以保存中间提交，但不得合并到 main。

## 6. 错误处理与安全边界

环境脚本必须遵守：

- 同名发行版已存在时不静默覆盖；
- 目标目录包含未知文件时停止并报告；
- 下载失败或校验失败时不注册发行版；
- 部分创建失败时只清理本次创建且明确归属的资源；
- destroy 默认只输出预览，显式确认后才执行；
- 删除前解析绝对路径并验证其位于 D:\ApplicationData\MiniOrangeOS；
- 不执行无范围的递归删除、WSL 注销或容器清理；
- 不修改 Windows PATH、注册表、全局 Git 配置或 Linux 全局 Shell 配置；
- 错误必须返回非零状态并写入集中日志。

构建和测试必须遵守：

- 不吞掉编译器、链接器或 QEMU 错误；
- 所有 QEMU 测试设置超时；
- 无论成功、失败或超时，都清理本次启动的子进程；
- GDB 只监听 WSL 回环地址；
- 任务报告只根据真实执行结果声明 PASS。

## 7. 测试与验收

### 7.1 T00

- 目录骨架符合计划；
- 文本文件行尾为 LF；
- 构建产物、工具链、venv 和镜像被忽略；
- README、贡献规范、文档索引和决策记录一致；
- Git 工作区在提交后干净。

### 7.2 T01

- MiniOrangeOS-Dev 名称和 Ubuntu 24.04 版本正确；
- 环境根目录和工具根目录未越界；
- i686-elf-gcc、i686-elf-ld、NASM、QEMU、GDB、Python 和 Git 版本可识别；
- verify.sh 输出完整环境指纹和 PASS；
- bootstrap 重复执行不破坏已有安装；
- 清理脚本预览、确认、定向删除和删除后验证通过；
- 删除不影响 docker-desktop 或其他 WSL 发行版。

### 7.3 T02

以下命令真实通过：

    make clean
    make all
    make image

并验证：

- 并行构建通过；
- 第二次增量构建不重新编译无关文件；
- 源码目录没有对象文件；
- 镜像大小和布局满足配置；
- 失败目标返回非零状态。

### 7.4 T03

- PASS 串口日志产生成功状态；
- FAIL 串口日志产生失败状态；
- 超时产生失败状态并终止 QEMU；
- 测试结束后无残留 QEMU 进程；
- GDB 端口未监听 0.0.0.0；
- WSL 中可以执行串口、curses 和无界面测试入口。

每个任务都必须执行当前任务测试和已有回归测试。测试原始日志写入 build/test-logs，不提交 Git；任务报告提交测试摘要、命令和结果。

## 8. 文档与心得闭环

新增并持续维护：

- docs/progress.md：任务、分支、提交、测试、合并和里程碑状态；
- docs/review-notes.md：关键路径理解、实现心得、发现并修正的问题和尚需学习内容；
- docs/decisions：重要工程决策及其背景和代价；
- docs/task-reports：每个 TXX 的实施报告。

每个任务完成时：

1. 更新对应专题文档；
2. 更新 docs/provenance.md；
3. 如有问题或降级，更新 docs/problems.md；
4. 写入任务报告和实际测试证据；
5. 更新进度状态；
6. 记录开发者需要审阅和理解的关键控制流。

不得把尚未实现或尚未运行的能力写成已完成。

## 9. M0 完成定义

只有同时满足以下条件，M0 才能标记完成：

- T00、T01、T02、T03 分别在独立分支完成并以 --no-ff 合并；
- MiniOrangeOS-Dev 可创建、验证、定向删除并重建；
- i686-elf 工具链和 Linux 构建依赖在隔离环境内工作；
- 最小构建、镜像、QEMU 测试和 GDB 入口真实可用；
- 所有任务测试和 M0 回归测试通过；
- 文档、来源登记、任务报告、进度和心得与实际状态一致；
- main 可构建且工作区干净；
- M0 annotated tag 已创建；
- 未修改 Windows PATH、注册表、全局 Git 配置或无关 WSL 资源。

## 10. 非 M0 范围

以下内容不在本规格中实现：

- 正式 512 字节 Boot Sector；
- Stage 2 Loader 功能；
- 保护模式、分页和高半内核；
- 中断、内存、进程、系统调用和文件系统；
- 用户态程序；
- 最终 CI、答辩和发布流程。

这些内容依次由 T10 至 T74 的后续子项目规格和实施计划覆盖。
