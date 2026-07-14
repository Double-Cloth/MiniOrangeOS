#ifndef MINIOS_SYSCALL_H
#define MINIOS_SYSCALL_H

#include <minios/arch/x86/trap_frame.h>

enum syscall_number {
    SYS_exit = 0,
    SYS_write = 1,
    SYS_waitpid = 11,
    SYS_getpid = 12,
    SYS_yield = 13,
    SYS_sleep = 14,
    SYS_getticks = 17
};

void syscall_dispatch(struct trap_frame *frame);

#endif
