#ifndef MINIOS_ABI_SYSCALL_H
#define MINIOS_ABI_SYSCALL_H

enum syscall_number {
    SYS_exit = 0,
    SYS_write = 1,
    SYS_waitpid = 11,
    SYS_getpid = 12,
    SYS_yield = 13,
    SYS_sleep = 14,
    SYS_getticks = 17
};

#endif
