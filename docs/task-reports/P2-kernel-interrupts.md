# P2 内核基础与中断阶段报告

阶段：P2 内核基础与中断

分支：`feature/P2-kernel-interrupts`

提交：

- `473ff53`：`feat(kernel): enter high half with early paging`
- `558fd30`：`feat(kernel): add console formatting and panic`
- `771d9fb`：`feat(kernel): install formal ring0 gdt`
- `79a6df8`：`feat(kernel): handle cpu exceptions through idt`
- `bc5f204`：`feat(kernel): route timer irqs through pic`
- `2927c89`：`feat(kernel): deliver ps2 keyboard input`
- `714b36f`：`docs(p2): record completed kernel interrupts`
- `6a307e8`：`merge: complete P2 kernel interrupts`

## 修改文件

- `kernel/arch/x86/`：高半入口、早期页表、GDT、IDT、异常和 IRQ 汇编/C 入口
- `kernel/core/`：初始化编排、双输出格式化控制台和 panic
- `kernel/drivers/`：COM1、VGA、8259 PIC、PIT 和 PS/2 键盘
- `kernel/include/minios/`：架构、控制台、panic 与驱动公开接口
- `kernel/linker.ld`、`Makefile`、`tools/build_dir_guard.py`
- `tests/host/test_boot_stage2.py`
- `PROJECT_PLAN.md`、`README.md` 与 P2 相关专题/进度/来源文档

## 关键实现

- 建立低端 0-4 MiB 恒等映射及 `0xC0000000` 高半别名，加载 CR3/CR0.PG 后跳入高半入口。
- 将页目录、页表和 16 KiB 启动栈放入独立 NOBITS 区段；清零 `.bss` 并以预污染探针验证结果。
- 实现有界 COM1 轮询、VGA text mode、双输出控制台、最小 `%s/%c/%u/%d/%x/%p/%%` 格式化和 panic。
- 安装正式 Ring 0 GDT；建立 256 项 IDT、32 个 CPU 异常入口、16 个 IRQ 入口和统一 trap frame。
- 异常 panic 输出 vector、error code 与 EIP；独立 breakpoint 镜像通过真实 `int3` 验证完整路径。
- 将 8259 master/slave 重映射到 `0x20/0x28`，驱动就绪后逐项放开 IRQ，并在处理后发送 EOI。
- 配置 PIT channel 0 为 100 Hz，以真实 IRQ0 维护 tick。
- 初始化 PS/2 控制器和第一端口，启用 set-1 translation/scanning；IRQ1 维护修饰键状态并写入 64-byte 环形输入缓冲。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/verify.sh
python3 -m unittest discover -s tests/host -v
bash environment/with-env.sh make clean image
bash environment/with-env.sh make test-boot-qemu QEMU_TIMEOUT=5
```

结果：

- 环境验证：PASS；
- 完整宿主回归：214/214 PASS，用时 329.647 秒；
- 干净默认镜像构建：PASS；
- P2 启动专项：20/20 PASS；
- 正式产品串口依次到达分页、BSS、控制台、GDT、IDT、PIC、PIT、键盘、中断开启和 tick 里程碑；
- 独立真实 QEMU 的 `int3` 输出 `[PANIC] exception vector=3 error=0 eip=0x...`；
- 独立真实 QEMU 的 HMP `sendkey a` 输出 `[KERN] keyboard input=a`；
- `kernel.elf`：19,076 bytes，SHA-256 `e441273b3035d73940620ab3de666694818437d4f0e20fe5adef6c3f2d151548`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `8b5d2726cc6ee0275bc62af4b5f435b5bf2b1b106e88af174b2add58474596ee`。

## 未解决问题

- 早期低端恒等映射、全 RW 内核映射和启动页表由 P3 正式 VMM 接管并收紧权限。
- Ring 3 code/data 描述符、TSS 和用户异常终止策略属于 P4；当前 Ring 0 CPU 异常统一 panic。
- 键盘仅将基础 set-1 ASCII 写入内核缓冲，扩展键和阻塞读取语义留给后续控制台/fd 层。
- 聚合入口 `make test` 仍按 P7 路线统一实现；本阶段使用上述公开入口提供可审计证据。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、`README.md`、`docs/architecture.md`、`docs/memory.md`、`docs/testing.md`、`docs/provenance.md`、`docs/progress.md` 和 `docs/review-notes.md`。
