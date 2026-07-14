#ifndef MINIOS_SYSCALL_H
#define MINIOS_SYSCALL_H

#include <minios/abi/syscall.h>
#include <minios/arch/x86/trap_frame.h>

void syscall_dispatch(struct trap_frame *frame);

#endif
