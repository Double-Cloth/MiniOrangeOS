# P6 磁盘与 MiniFS 阶段报告

阶段：P6 磁盘与 MiniFS

分支：`feature/P6-minifs`

提交：

- `be6d134`：`feat(p6): add ATA and block device layers`
- `864eb2d`：`feat(p6): build deterministic MiniFS images`
- `19c87c5`：`feat(p6): mount and read MiniFS in kernel`
- `44f90b7`：`feat(p6): persist writable MiniFS files`
- `1f6617b`：`feat(p6): add VFS and file syscalls`
- `0552a8f`：`feat(p6): add mutable MiniFS directories`
- `64fb8b9`：`feat(p6): add user file commands`

合并提交：待本地合并；本报告提交后分支达到可合并状态，未执行远端推送。

## 修改文件

- `include/minios/abi/`、`include/minios/disk/`、`include/minios/fs/`：共享文件 syscall/dirent ABI、磁盘布局与内核存储接口
- `kernel/drivers/ata.c`、`kernel/storage/`：ATA PIO 与 4 KiB block device
- `kernel/fs/`：MiniFS 挂载、inode/bitmap、文件与目录修改、路径解析、VFS/file object
- `kernel/core/syscall.c`、`kernel/proc/`：文件 syscall、进程 fd 生命周期与从 VFS 加载用户 ELF
- `tools/minifs/`、镜像装配脚本：确定性 mkfs、只读 fsck 与磁盘 ABI 生成
- `user/`：文件 syscall wrapper 和 `ls/cat/touch/write/mkdir/rm`
- `Makefile`、宿主/QEMU 测试和文件系统、系统调用、进程及阶段状态文档

## 关键实现

- primary master LBA28 PIO 驱动执行 IDENTIFY、多扇区读写、BSY/DRQ/ERR/DF 有界轮询、容量检查与 cache flush；4 KiB block 层统一扇区换算和边界检查。
- MiniFS 固定从 LBA 2048 开始，使用 CRC32 Superblock、block/inode bitmap、1024 个 64-byte inode、64-byte 目录项、12 个 direct block 与一级 indirect block；宿主 mkfs 确定性导入 12 个用户 ELF，fsck 同时支持独立卷和整盘镜像。
- 内核挂载严格校验 CRC、几何、bitmap、root inode 和块范围；路径解析支持重复 `/`、`.`、`..`、尾随 `/` 以及中间组件类型检查。
- 普通文件支持创建、读取、覆盖、无稀疏扩展、direct/indirect 跨界、缩小截断、block/inode 分配回收和跨重启持久化。
- 目录支持空闲项复用、跨块扩容、`.`/`..`、link count、空目录删除、非空目录与已打开 inode 删除拒绝；`readdir` 通过共享 68-byte `minios_dirent` 迭代。
- VFS 提供 32 项全局 file object 池；每进程拥有 16 项 fd、独立 offset/flags/refcount/ops，close 和 exit 均完成引用清理。`spawn` 已从只读注册表切换为磁盘 VFS，注册表仅用于原始 6 个程序的迁移期字节比对。
- 用户态新增 `open/read/write/lseek/close/stat/create/mkdir/unlink/readdir` 封装及 6 个独立文件命令；Shell 经真实 `spawn/wait` 完成创建、读取、列举、删除和重启后读取闭环。
- 修复 `copy_user_string` 的用户空间顶端边界：逐字节验证到 NUL，不再因未实际访问的最大扫描区间跨越 `KERNEL_BASE` 而误拒绝。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/verify.sh
python3 -m unittest tests.host.test_build_contract tests.host.test_minifs_tools tests.host.test_boot_stage2
python3 -m unittest tests.host.test_build_runtime.BuildRuntimeTests.test_public_targets_build_expected_artifacts tests.host.test_build_runtime.BuildRuntimeTests.test_incremental_build_is_exact_and_kernel_dependency_is_selective
bash environment/with-env.sh make BUILD_DIR=.p6-cmd-final -j4 image
bash environment/with-env.sh make BUILD_DIR=.p6-cmd-final test-image
python3 -m unittest discover -s tests/host -v
```

结果：

- 环境验证：PASS；
- 构建契约、MiniFS 工具与启动专项组合：49/49 PASS，用时 84.119 秒；
- 受影响运行时构建专项：2/2 PASS；
- 独立干净镜像构建与 `make test-image`：PASS；
- 完整宿主回归：239/239 PASS，用时 565.244 秒；
- 专用 MiniFS 双启动第一次创建并写入 45,179-byte 跨 direct/indirect 文件及 65 个目录文件，第二次逐字节验证、截断、迭代并删除；两次启动后的宿主 fsck 均 PASS；
- 产品双启动第一次由用户 `write` 创建 `/p6-command-persist`，第二次由用户 `cat` 读取并输出 verified；ls/cat/touch/write/mkdir/rm 闭环 PASS；
- `kernel.elf`：145,656 bytes，SHA-256 `2a0749ff4fb27289c79e1a9f75b186b7dcd66ac0b777a0177ad84734aa87873b`；
- `minifs.img`：66,060,288 bytes，SHA-256 `79fe925f71552cf9b4fd47cedd99ef91b08a3bfc1d97ec0d5c301435156ead2b`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `3c55f18a0a4768d98e8d834a9f783c47adf7d77c88d9576d436f4f35bb0001fe`。

当前仓库尚未提供聚合 `make test`/`make test-host` 目标，因此本阶段按上述真实 unittest 入口完成全量覆盖；聚合入口归入 P7。

## 未解决问题

- MiniFS 不提供 journal 或掉电事务；当前写入顺序和失败回滚只缩小不一致窗口，不能保证任意中断点的崩溃原子性。
- ATA 仅支持 primary master LBA28 PIO，不支持分区表、LBA48、DMA 或 IRQ 驱动 I/O；单 CPU 关中断串行化不适用于 SMP。
- 目录删除项形成的空洞可复用，但目录文件不会在普通删除后自动缩小并回收尾部目录块。
- console/keyboard 仍由 syscall 适配，不是统一 VFS file object；普通 fd 不跨 spawn 继承。
- Shell 没有 cwd syscall，`cd/pwd` 仍只支持根目录；权限、链接、rename 和完整 POSIX 语义不在最低范围内。
- 聚合 `make test`、Linux CI、最终演示脚本、代码量统计与 release checklist 归入 P7。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、`docs/filesystem.md`、`docs/syscall.md`、`docs/process.md`、`docs/testing.md`、`docs/progress.md`、`docs/provenance.md` 和 `docs/review-notes.md`。
- 已新增本阶段报告；P6 功能与文档提交完成后等待本地 no-ff 合并，不自动推送。
