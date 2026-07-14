# 最终发布检查清单

> 本清单只在对应命令真实通过后勾选；P7 阶段报告记录最终产物、哈希、CI 状态和未解决限制。

## 环境与来源

- [x] `environment/verify.sh` 在正式 `MiniOrangeOS-Dev` 中 PASS。
- [x] 固定 Ubuntu、Binutils、GCC 与 OCI 基础镜像来源和 SHA-256 与 `environment/versions.env` 一致。
- [x] GitHub Actions 仅使用完整提交 SHA 固定的 action，工作流权限最小化为 `contents: read`。
- [x] `docs/provenance.md` 已覆盖最终模块、CI 与第三方边界。

## 构建与测试

- [x] `./environment/with-env.sh make clean` 后 `make -j4 image` PASS。
- [x] `./environment/with-env.sh make test` 聚合入口 PASS。
- [x] `./environment/with-env.sh make loc` 生成分类型代码量统计。
- [x] 最终 `kernel.elf`、`minifs.img` 与 `miniorangeos.img` 已记录大小和 SHA-256。
- [x] Linux CI 在干净 Ubuntu runner 的固定容器环境中 PASS（运行 `29331275773`，最终分支 HEAD `72add84`，246/246 PASS）。

## 演示闭环

- [x] `./environment/with-env.sh make demo-persistence` PASS。
- [x] 串口证据覆盖 BIOS → Stage 1 → Stage 2 → protected mode → kernel → Ring 3 → `/bin/init` → Shell。
- [x] 用户文件命令真实完成创建、覆盖、读取、列举与删除。
- [x] 同一磁盘镜像第二次启动读取第一次写入的内容。
- [x] 每次写入启动后宿主 `fsck` PASS，且串口无 `[PANIC]`。

## 文档与交付

- [x] `README.md`、`PROJECT_PLAN.md`、专题文档和真实实现一致。
- [x] `docs/progress.md` 与所有已完成阶段报告的提交、测试和合并状态一致。
- [x] `docs/problems.md` 区分已解决问题、当前风险和有意限制。
- [x] `docs/review-notes.md` 已记录 P7 审查心得。
- [x] 工作树干净，P7 提交可审计，未提交构建产物或临时实验文件。

## 已知限制

- [x] 已明确不支持 x86_64、UEFI、SMP、网络、USB、图形桌面、动态链接和完整 POSIX。
- [x] 已明确 MiniFS 无 journal/掉电原子性，ATA 限于 primary master LBA28 PIO。
- [x] 已明确 Shell 无 cwd syscall，console/keyboard 尚未统一为 VFS file object。
- [x] 已明确 Linux CI 证明 QEMU/容器路径，不等同于真实硬件验收。
