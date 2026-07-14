#include <minios/console.h>
#include <minios/panic.h>

#include <stdarg.h>

_Noreturn void panicf(const char *format, ...)
{
    va_list arguments;

    __asm__ volatile("cli");
    console_write("[PANIC] ");
    va_start(arguments, format);
    console_vprintf(format, arguments);
    va_end(arguments);
    console_putc('\n');
    for (;;) {
        __asm__ volatile("hlt");
    }
}

_Noreturn void panic(const char *message)
{
    panicf("%s", message);
}
