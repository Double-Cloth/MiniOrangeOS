# 编码规范

## 通用规则

- 所有文本（包括 PowerShell 脚本）使用 UTF-8 和 LF。
- 代码标识符、文件名和第三方 API 使用英文；注释和项目文档使用中文。
- 单个模块只承担一个职责；跨模块依赖通过头文件中的公开接口。
- 不引入未被当前 TXX 要求的框架、依赖或抽象。

## C11 Freestanding

- 文件名和函数名使用 snake_case。
- 类型名使用带模块前缀的 snake_case；宏和常量使用 UPPER_SNAKE_CASE。
- 公开函数必须有原型；内部函数使用 static。
- 使用 stdint.h 和 stddef.h 的定宽类型，不使用 int 表示磁盘地址、物理地址或结构序列化字段。
- 指针和长度运算必须检查溢出；禁止依赖宿主 libc 或 Linux ABI。
- 默认编译警告以 PROJECT_PLAN.md 第 3.2 节为准，警告不得静默忽略。

## NASM

- 使用 Intel 语法；标签使用 snake_case。
- 入口、调用约定、寄存器所有权和栈布局必须在相邻中文注释中说明。
- 魔数、选择子和端口号使用命名常量。

## Python 与 Shell

- Python 工具只使用显式 little-endian 编解码磁盘结构，不依赖对象内存布局。
- Shell 脚本以 set -euo pipefail 开始，对外部输入加引号并显式检查路径边界。
- PowerShell 删除或移动前使用 LiteralPath 和已解析绝对路径检查。

## 错误模型

内核及用户态 C API 成功返回 0 或非负结果；失败返回负错误码。项目稳定的 C API 错误名为：

    EINVAL
    ENOENT
    EEXIST
    ENOMEM
    ENOSPC
    EIO
    EFAULT
    EBADF
    ENOTDIR
    EISDIR
    ENOTEMPTY

错误码数值由首次引入公共错误头的任务统一定义，之后内核和用户态从同一来源生成或引用，禁止手写两份编号。

宿主 Python、Shell 和 PowerShell 工具使用进程退出状态：成功为 0，失败为非零值，不复用内核负错误码作为进程退出状态。

Kernel panic 只用于不可恢复的内核不变量破坏。用户输入、损坏镜像和用户进程异常必须返回错误或终止当前进程。
