# P5 ELF 用户态与 Shell 阶段报告

阶段：P5 ELF 用户态与 Shell

分支：`feature/P5-user-shell`

提交：

- `3ba9d8a`：`feat(p5): establish user ELF build contract`
- `43b2cc5`：`feat(p5): load embedded ELF user process`
- `70ecdfe`：`feat(p5): add spawn and echo user process`
- `f7d1264`：`feat(p5): add shell command execution`
- `ae44349`：`feat(p5): add user diagnostics and fault isolation`
- `d9eeba7`：`fix(build): stabilize new DrvFS build identity`

合并提交：待阶段分支合并后补记。

## 修改文件

- `include/minios/abi/`：内核/用户共享 syscall、errno 与进程快照 ABI
- `kernel/proc/elf.c`、`program_registry.c`、`scheduler.c`：严格用户 ELF 装载、只读程序注册表、argc/argv 栈与进程创建
- `kernel/core/syscall.c`：`read`、`spawn`、`ps` 及既有调用分发
- `user/`：crt0、最小 libc、linker script、init、sh、echo、ps、memtest、fault
- `Makefile`、构建目录 guard 与宿主/QEMU 测试
- 进程、系统调用、文件系统过渡方案及阶段状态文档

## 关键实现

- 只接受 little-endian i386 `ET_EXEC`；验证 program header 范围、地址溢出、段重叠、`filesz <= memsz`、入口所在可执行段和 `KERNEL_BASE` 边界，再逐页分配、清零、复制并应用 R/W 权限。
- 构建期把完整用户 ELF 作为只读 blob 链入内核；P6 只需用 VFS 文件读取替换注册表来源，loader/spawn ABI 不变。
- 初始栈按 `argc, argv[], NULL, strings` 构造并保留未映射保护页；crt0 调用 C `main` 后进入 `SYS_exit`。
- `spawn` 限制 path 256 bytes、argc 16、单参数 64 bytes、总参数 1024 bytes；子进程建立父子关系，Shell 前台命令统一 spawn/waitpid。
- Shell 支持逐字符输入、退格、空格/Tab 分词、`help/clear/cd/pwd/exit` 内建与 `/bin/` 路径补全；自动模式走同一命令路径执行 echo、ps、memtest。
- `ps` 使用固定共享结构取得最多 16 项关中断 PCB 快照；`fault` 的用户 #PF 转为 `-EFAULT`，由 init 验证内核继续运行。
- 修复 DrvFS 新建 BUILD_DIR 暂报 inode 0 导致 clean 后并行构建偶发 marker 失效的问题，同时保留 parent dirfd 与替换检测边界。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/verify.sh
bash environment/with-env.sh make clean
bash environment/with-env.sh make -j4 image
python3 -m unittest tests.host.test_boot_stage2 -v
python3 -m unittest discover -s tests/host -v
```

结果：

- 环境验证：PASS；
- 干净交叉编译与镜像构建：PASS；
- 启动专项：28/28 PASS；
- 完整宿主回归：225/225 PASS，用时 463.969 秒；
- QEMU 串口依次出现 echo、Shell command、ps、memtest、Shell self-test、fault isolation、init 与 ELF user process PASS；
- `kernel.elf`：113,984 bytes，SHA-256 `19a3a72d575ba65a4d2a65143ddf42f6de3cd5f7fc49191a31037441faf97dd0`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `aa63d1cacdfa00ecfb3d023113d34e7b345e9ca0409ecb6d4c4bf779d8d1be06`。

## 未解决问题

- P5 注册表是 MiniFS 前的只读过渡来源；P6 必须以 VFS 文件读取替换，但保持 loader 和 spawn ABI。
- 文件系统尚未实现，因此 Shell 的 `cd/pwd` 只支持根目录，ls/cat/touch/write/mkdir/rm 属于 P6。
- 进程表仍固定 16 项，用户栈固定一页；动态堆 `sbrk` 与普通文件 fd 属于后续阶段。
- 聚合 `make test` 仍按 P7 路线统一；本阶段使用上述现行入口提供完整证据。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、`README.md`、`docs/process.md`、`docs/syscall.md`、`docs/filesystem.md`、`docs/testing.md`、`docs/progress.md`、`docs/provenance.md` 和 `docs/review-notes.md`。
