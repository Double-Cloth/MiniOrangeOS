#ifndef MINIOS_ARCH_X86_PAGE_FAULT_H
#define MINIOS_ARCH_X86_PAGE_FAULT_H

#include <minios/arch/x86/trap_frame.h>

#include <stdbool.h>
#include <stdint.h>

typedef bool (*user_page_fault_handler)(
    uint32_t address,
    uint32_t error_code,
    const struct trap_frame *frame
);

void page_fault_set_user_handler(user_page_fault_handler handler);
bool page_fault_self_test(void);

#endif
