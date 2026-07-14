#ifndef MINIOS_CONSOLE_H
#define MINIOS_CONSOLE_H

#include <stdarg.h>

void console_init(void);
void console_putc(char character);
void console_write(const char *text);
void console_vprintf(const char *format, va_list arguments);
void console_printf(const char *format, ...);

#endif
