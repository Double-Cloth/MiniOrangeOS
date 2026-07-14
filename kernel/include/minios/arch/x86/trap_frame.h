#ifndef MINIOS_ARCH_X86_TRAP_FRAME_H
#define MINIOS_ARCH_X86_TRAP_FRAME_H

#include <stdint.h>

struct trap_frame {
    uint32_t edi;
    uint32_t esi;
    uint32_t ebp;
    uint32_t esp_before_pushad;
    uint32_t ebx;
    uint32_t edx;
    uint32_t ecx;
    uint32_t eax;
    uint32_t vector;
    uint32_t error_code;
    uint32_t eip;
    uint32_t cs;
    uint32_t eflags;
};

#endif
