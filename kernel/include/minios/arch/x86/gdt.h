#ifndef MINIOS_ARCH_X86_GDT_H
#define MINIOS_ARCH_X86_GDT_H

#include <stdint.h>

#define GDT_KERNEL_CODE_SELECTOR 0x08U
#define GDT_KERNEL_DATA_SELECTOR 0x10U
#define GDT_USER_CODE_SELECTOR 0x1BU
#define GDT_USER_DATA_SELECTOR 0x23U
#define GDT_TSS_SELECTOR 0x28U

void gdt_init(void);
void gdt_set_kernel_stack(uint32_t stack_top);

#endif
