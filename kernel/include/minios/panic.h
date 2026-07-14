#ifndef MINIOS_PANIC_H
#define MINIOS_PANIC_H

_Noreturn void panic(const char *message);
_Noreturn void panicf(const char *format, ...);

#endif
