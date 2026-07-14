#ifndef MINIOS_ARCH_X86_USER_MODE_H
#define MINIOS_ARCH_X86_USER_MODE_H

#include <stdint.h>

_Noreturn void enter_user_mode(uint32_t entry, uint32_t stack_top);

extern const uint8_t user_test_start[];
extern const uint8_t user_test_end[];

#endif
