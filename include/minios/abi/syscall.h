#ifndef MINIOS_ABI_SYSCALL_H
#define MINIOS_ABI_SYSCALL_H

enum syscall_number {
    SYS_exit = 0,
    SYS_write = 1,
    SYS_read = 2,
    SYS_open = 3,
    SYS_close = 4,
    SYS_lseek = 5,
    SYS_create = 6,
    SYS_unlink = 7,
    SYS_mkdir = 8,
    SYS_readdir = 9,
    SYS_spawn = 10,
    SYS_waitpid = 11,
    SYS_getpid = 12,
    SYS_yield = 13,
    SYS_sleep = 14,
    SYS_stat = 16,
    SYS_getticks = 17,
    SYS_ps = 18
};

#endif
