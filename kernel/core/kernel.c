#include <minios/console.h>

void kernel_main(void);

void kernel_main(void)
{
    console_init();
    console_printf("[KERN] console ready hex=%x dec=%u str=%s\n", 0xC0FFEEU, 42U, "ok");
    for (;;) {
        __asm__ volatile("hlt");
    }
}
