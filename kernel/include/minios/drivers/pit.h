#ifndef MINIOS_DRIVERS_PIT_H
#define MINIOS_DRIVERS_PIT_H

#include <stdint.h>

void pit_init(uint32_t frequency_hz);
void pit_handle_irq(void);
uint32_t pit_ticks(void);

#endif
