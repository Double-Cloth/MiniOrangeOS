#ifndef MINIOS_ARCH_X86_IRQ_H
#define MINIOS_ARCH_X86_IRQ_H

#include <stdint.h>

void irq_enable(void);
uint32_t irq_read_flags(void);
uint32_t irq_save_disable(void);
void irq_restore(uint32_t flags);

#endif
