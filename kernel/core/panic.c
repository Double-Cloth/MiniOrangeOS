#include <minios/console.h>
#include <minios/panic.h>

_Noreturn void panic(const char *message)
{
    __asm__ volatile("cli");
    console_printf("[PANIC] %s\n", message);
    for (;;) {
        __asm__ volatile("hlt");
    }
}
