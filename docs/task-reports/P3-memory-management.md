# P3 内存管理阶段报告

阶段：P3 内存管理

分支：`feature/P3-memory-management`

提交：

- `be16dee`：`feat(mm): initialize physical page bitmap from e820`
- `61ddc58`：`feat(mm): install recursive kernel page tables`
- `66a4c0f`：`feat(mm): add first-fit kernel heap`
- `4fc5db5`：`feat(mm): enforce user memory boundaries`

## 修改文件

- `kernel/mm/`：E820 PMM、正式 VMM、内核堆、用户地址空间和 usercopy
- `kernel/include/minios/mm/`：PMM/VMM/Heap/地址空间/usercopy 公开合同
- `kernel/arch/x86/exception.c` 与 `page_fault.h`：page fault 分类和用户处理器接管点
- `kernel/core/kernel.c`：P3 初始化编排及运行时自检
- `kernel/linker.ld`、`Makefile`、`tests/host/test_boot_stage2.py`
- `PROJECT_PLAN.md`、`README.md` 与 P3 相关专题/进度/来源文档

## 关键实现

- 以两张覆盖 4 GiB 的 bitmap 管理 4 KiB 物理页；E820 usable 先释放、reserved 后覆盖，低端 1 MiB 和完整内核物理范围始终保留。
- 复用启动页目录建立 PDE 1023 递归映射，按需分配/回收页表；移除 PDE 0，按链接段收紧 text/rodata，并启用 CR0.WP。
- 在独立 16 MiB 高半窗口实现 8 字节对齐 first-fit Heap，支持拆分、前后合并、按页扩展、失败回滚、magic 与 double free 检测。
- 通过两个受控工作窗口构造非当前用户页目录；复制稳定高半映射并排除临时窗口，支持用户页映射/查询/解除映射和所有资源销毁。
- usercopy 对范围内每页检查有效 U/S 与 R/W，覆盖跨页缓冲和有界字符串，非法指针返回 `-MINIOS_EFAULT`。
- vector 14 读取 CR2 并按 U/S 位区分来源；内核故障 panic，用户故障可由 P4 注册的进程级处理器接管，缺失处理器时失败关闭。

## 执行命令与测试结果

在正式 `MiniOrangeOS-Dev` 中执行：

```bash
./environment/verify.sh
bash environment/with-env.sh make clean image
python3 -m unittest tests.host.test_boot_stage2 -v
python3 -m unittest discover -s tests/host -p 'test_*.py' -v
```

结果：

- 环境验证：PASS；
- P3 最终启动专项：25/25 PASS；
- 完整宿主回归：219/219 PASS，用时 365.108 秒；
- 正式产品依次输出 PMM、VMM、Heap 与 user memory 自检 PASS，并继续到达 PIT tick；
- 真实 kernel #PF 输出 CR2 `0x00400000`、error code 0 与 EIP；
- 真实 `int3` panic 与 HMP `sendkey a` 回归继续 PASS；
- `kernel.elf`：35,296 bytes，SHA-256 `10777c62c06713692a8dabad98ee91edcbe061bdc7278d4e95d5a0d495ca5161`；
- `miniorangeos.img`：67,108,864 bytes，SHA-256 `49fdcbfc812ee0268e9181bccf1f1f5849e6218ed87bb9d4f6c64603fed081f6`。

## 未解决问题

- 用户页目录已可离线构造和销毁；CR3 激活、激活前共享内核 PDE 刷新、TSS 与上下文切换属于 P4。
- 用户 page fault 已有来源分类和接管接口；“只终止当前进程”需等待 P4 当前进程与调度器。
- Heap 当前不收缩已映射页，且尚未提供可抢占/多 CPU 锁；P4 引入调度前必须确定并发策略。
- 聚合入口 `make test` 仍按 P7 路线统一实现；本阶段使用上述现行入口提供证据。

## 文档同步

- 已更新 `PROJECT_PLAN.md`、`README.md`、`docs/memory.md`、`docs/testing.md`、`docs/provenance.md`、`docs/progress.md` 和 `docs/review-notes.md`。
