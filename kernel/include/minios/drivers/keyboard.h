#ifndef MINIOS_DRIVERS_KEYBOARD_H
#define MINIOS_DRIVERS_KEYBOARD_H

#include <stdbool.h>
#include <stdint.h>

void keyboard_init(void);
void keyboard_handle_irq(void);
bool keyboard_try_read(uint8_t *character);

#endif
