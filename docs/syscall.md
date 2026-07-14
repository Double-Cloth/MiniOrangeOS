# 系统调用与用户指针安全设计

> 覆盖阶段：P4 进程与系统调用、P5 用户态、P6 文件系统。

## 调用约定

系统调用采用 `int 0x80`：

| 寄存器 | 含义 |
|---|---|
| `EAX` | 系统调用号，返回值 |
| `EBX` | 参数 1 |
| `ECX` | 参数 2 |
| `EDX` | 参数 3 |
| `ESI` | 参数 4 |
| `EDI` | 参数 5 |

返回值：

- 非负数表示成功；
- 负数表示错误码；
- `SYS_exit` 不返回。

## 最低系统调用表

| 编号 | 名称 | 参数草案 | 返回 |
|---:|---|---|---|
| 0 | `SYS_exit` | `int status` | 不返回 |
| 1 | `SYS_write` | `int fd, const void *buf, size_t len` | 写入字节数 |
| 2 | `SYS_read` | `int fd, void *buf, size_t len` | 读取字节数 |
| 3 | `SYS_open` | `const char *path, int flags` | fd |
| 4 | `SYS_close` | `int fd` | 0 |
| 5 | `SYS_lseek` | `int fd, int offset, int whence` | 新偏移 |
| 6 | `SYS_create` | `const char *path` | 0 |
| 7 | `SYS_unlink` | `const char *path` | 0 |
| 8 | `SYS_mkdir` | `const char *path` | 0 |
| 9 | `SYS_readdir` | `int fd, void *dirent, size_t len` | 1/0 |
| 10 | `SYS_spawn` | `const char *path, char *const argv[]` | pid |
| 11 | `SYS_waitpid` | `int pid, int *status` | pid |
| 12 | `SYS_getpid` | 无 | pid |
| 13 | `SYS_yield` | 无 | 0 |
| 14 | `SYS_sleep` | `uint32_t ticks` | 0 |
| 15 | `SYS_sbrk` | `intptr_t increment` | old break |
| 16 | `SYS_stat` | `const char *path, void *statbuf` | 0 |
| 17 | `SYS_getticks` | 无 | tick 低 32 位 |

后续实现必须让用户态 libc wrapper 与内核表保持同一编号来源，避免手写两份不一致的 enum。

当前 P4 最小实现安装了 vector `0x80`、DPL=3 的 32-bit interrupt gate，入口保存通用寄存器和用户段寄存器，切到 Ring 0 data selector 后把可修改 trap frame 交给 C 分发器。已实现 `SYS_exit`、`SYS_write`、`SYS_waitpid`、`SYS_getpid`、`SYS_yield`、`SYS_sleep`、`SYS_getticks`；`write` 当前只接受 fd 1/2，单次最多 4096 bytes，先验证完整用户范围再按 128-byte 内核缓冲分块输出。`waitpid` 在阻塞前验证可选 status 用户指针，成功后回写 exit code；`sleep` 由 PIT deadline 唤醒。内嵌 Ring 3 自检覆盖正常输出/让出/睡眠/退出，以及未知调用号、非法 fd、跨入内核空间的指针、超长写入和无子进程 wait 错误码。其余表项仍按后续 P5-P6 阶段实现。

## 安全边界

系统调用入口必须区分两类错误：

- 用户输入错误：返回负数错误码或终止当前进程。
- 内核不变量破坏：panic。

任何用户传入的指针、长度、fd、路径、pid、flags 都不可信。

## Usercopy 规则

每个系统调用在访问用户内存前必须：

1. 检查地址范围不跨越 `0xC0000000`。
2. 检查地址加长度不溢出。
3. 检查覆盖的每个页已映射。
4. 写方向检查页可写。
5. 字符串使用最大长度限制。
6. 拷贝到内核缓冲后再解析。

路径最大长度建议：

```text
MAX_PATH = 256
MAX_NAME = 59
```

命令行和 `argv` 建议限制：

```text
MAX_ARGC = 16
MAX_ARG_LEN = 64
MAX_ARG_BYTES = 1024
```

## fd 语义

每个进程独立 fd 表：

| fd | 默认对象 |
|---:|---|
| 0 | 键盘/控制台输入 |
| 1 | 控制台输出 |
| 2 | 控制台错误输出 |

要求：

- fd 越界返回 `-EBADF`；
- close 后再次使用返回 `-EBADF`；
- 不同进程打开同一 inode 时 offset 独立；
- spawn 的子进程可继承标准 fd，普通文件继承策略可先采用不继承；
- exit 必须关闭所有 fd。

## 进程系统调用

`SYS_spawn`：

- 拷贝路径和 argv；
- P5 先从构建期只读 ELF 注册表按路径取 bytes，P6 改为通过 VFS 打开 ELF；
- 调用用户 ELF 加载器；
- 建立父子关系；
- 将子进程放入 READY；
- 返回 pid。

`SYS_waitpid`：

- `pid > 0` 等待指定子进程；
- `pid == -1` 等待任意子进程；
- 无子进程返回错误；
- 子进程已 ZOMBIE 时立即回收；
- 未退出时当前进程 BLOCKED。

`SYS_exit`：

- 设置 exit_code；
- 关闭 fd；
- 释放用户地址空间；
- 唤醒父进程；
- 进入 ZOMBIE；
- 调度其他进程。
