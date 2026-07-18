#include <minios/arch/x86/io.h>
#include <minios/arch/x86/irq.h>
#include <minios/console.h>
#include <minios/drivers/power.h>

#include <stdint.h>

#define QEMU_DEBUG_EXIT_PORT 0x00F4U
#define QEMU_SHUTDOWN_VALUE 0x2AU

_Noreturn void power_shutdown(void)
{
    (void)irq_save_disable();
    console_write("[KERN] shutdown requested\n");
    io_out8(QEMU_DEBUG_EXIT_PORT, QEMU_SHUTDOWN_VALUE);

    for (;;) {
        __asm__ volatile("hlt");
    }
}
