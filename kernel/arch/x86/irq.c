#include <minios/arch/x86/irq.h>
#include <minios/arch/x86/trap_frame.h>
#include <minios/drivers/keyboard.h>
#include <minios/drivers/pic.h>
#include <minios/drivers/pit.h>
#include <minios/panic.h>

#include <stdint.h>

#define HARDWARE_IRQ_BASE 32U
#define HARDWARE_IRQ_COUNT 16U

void irq_dispatch(const struct trap_frame *frame);

void irq_dispatch(const struct trap_frame *frame)
{
    uint32_t irq;

    if (frame->vector < HARDWARE_IRQ_BASE ||
        frame->vector >= HARDWARE_IRQ_BASE + HARDWARE_IRQ_COUNT) {
        panicf("invalid irq vector=%u", frame->vector);
    }
    irq = frame->vector - HARDWARE_IRQ_BASE;
    if (irq == 0U) {
        pit_handle_irq();
    } else if (irq == 1U) {
        keyboard_handle_irq();
    }
    pic_send_eoi((uint8_t)irq);
}

void irq_enable(void)
{
    __asm__ volatile("sti");
}

uint32_t irq_read_flags(void)
{
    uint32_t flags;
    __asm__ volatile("pushf; pop %0" : "=r"(flags));
    return flags;
}

uint32_t irq_save_disable(void)
{
    uint32_t flags = irq_read_flags();
    __asm__ volatile("cli" : : : "memory");
    return flags;
}

void irq_restore(uint32_t flags)
{
    if ((flags & 0x00000200U) != 0U) {
        __asm__ volatile("sti" : : : "memory");
    } else {
        __asm__ volatile("cli" : : : "memory");
    }
}
