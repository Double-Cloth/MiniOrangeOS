# P1 启动链阶段报告

阶段：P1 完成启动链

分支：`feature/P1-boot-chain`

提交：

- `414a5e7`：`feat(boot): enter protected mode with e820 map`
- `8bdb7be`：`feat(boot): load high-half kernel from ata`

## 修改文件

- `boot/stage2/entry.asm`、`boot/stage2/linker.ld`
- `boot/include/boot_info.inc`
- `kernel/arch/x86/entry.asm`、`kernel/linker.ld`
- `tools/generate_boot_layout.py`、`Makefile`
- `tests/host/test_boot_stage1.py`、`tests/host/test_boot_stage2.py`
- `tests/host/test_build_contract.py`、`tests/host/test_qemu_contract.py`
- `PROJECT_PLAN.md`、`README.md` 与 P1 相关专题/进度/来源文档

## 关键实现

- 使用内存别名测试验证 A20，依次尝试 BIOS `INT 15h/AX=2401h` 和 Fast A20 端口。
- 采集最多 128 个 24-byte E820 条目，过滤空/无效条目并检查地址回绕；内核物理段必须完整位于 type 1 区域且不与保留类型重叠。
- 加载临时平坦 GDT，设置 `CR0.PE` 并进入 32 位保护模式。
- 从统一生成的镜像布局读取 Kernel LBA/上限，通过 primary master ATA PIO LBA28 分段读取 ELF 文件。
- 校验 ELF32、little-endian、`ET_EXEC`、`EM_386`、Program Header 范围、段大小/对齐/物理范围和重叠；按 `p_paddr` 装载并清零 BSS。
- 内核采用 `VMA 0xC0100000 / LMA 0x00100000`；Loader 翻译物理入口，构造 64-byte Boot Info 和加和校验，使用 `EAX/EBX` 交接。
- 内核分页前早期入口使用相对寻址校验 Boot Info，串口输出 `[KERN] boot info valid`。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/verify.sh
bash environment/with-env.sh make clean
bash environment/with-env.sh make -j4 image
bash environment/with-env.sh make test-qemu QEMU_TIMEOUT=5
bash environment/with-env.sh make test-boot-qemu QEMU_TIMEOUT=5
python3 -m unittest discover -s tests/host -v
```

结果：

- 环境验证：PASS；
- 干净镜像构建：PASS；
- 通用 QEMU 串口协议：PASS；
- P1 启动链专项：11/11 PASS；
- 完整宿主回归：205/205 PASS，用时 257.238 秒；
- 真实产品串口依次到达 `[S2] protected mode entered`、`[S2] kernel loaded entry=0xC0100000`、`[KERN] boot info valid`；
- 坏 ELF 魔数、`filesz > memsz`、覆盖 Loader、`PT_LOAD` 重叠均在内核入口前输出 `[S2] ELF failure`；
- `stage2.bin`：2544 bytes，SHA-256 `da323d9f7cb876cfa2b4b1881413b4dd66c727dfa2e99b26f793bc94270539e8`；
- `kernel.elf`：9356 bytes，SHA-256 `9b500f7b4b51c4543d097b3c3f2a4edaf95fe423de05b4273b1f64c9b56b7717`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `869fcd020a3df0c370d65e8cf3ca512aaf35b6970a30c26df545f60cf9f2f35d`。

## 未解决问题

- 聚合入口 `make test` 尚未实现；实际执行返回 `No rule to make target 'test'`。本阶段用上述环境、构建、QEMU 和 205 项宿主回归替代，聚合入口按计划在 P7 收敛。
- 内核目前仅在分页前物理入口校验 Boot Info；早期页表、正式高半跳转、`.bss` 初始化编排和内核日志/panic 属于 P2。
- Loader ATA 仅支持 BIOS `DL=0x80` 对应的 primary master LBA28；内核通用 ATA/block 驱动属于 P6。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、`README.md`、`docs/boot.md`、`docs/testing.md`、`docs/provenance.md`、`docs/progress.md` 和 `docs/review-notes.md`。
