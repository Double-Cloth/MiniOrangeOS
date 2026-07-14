#include <minios/arch/x86/io.h>
#include <minios/console.h>
#include <minios/drivers/pit.h>
#include <minios/panic.h>

#include <stdint.h>

#define PIT_INPUT_FREQUENCY 1193182U
#define PIT_CHANNEL_ZERO 0x40
#define PIT_COMMAND 0x43
#define PIT_MODE_THREE 0x36
#define PIT_MILESTONE_TICK 5U

static volatile uint32_t tick_count;

void pit_init(uint32_t frequency_hz)
{
    uint32_t divisor;

    if (frequency_hz == 0U) {
        panic("PIT frequency is zero");
    }
    divisor = PIT_INPUT_FREQUENCY / frequency_hz;
    if (divisor == 0U || divisor > 0xFFFFU) {
        panicf("invalid PIT divisor=%u", divisor);
    }
    tick_count = 0U;
    io_out8(PIT_COMMAND, PIT_MODE_THREE);
    io_out8(PIT_CHANNEL_ZERO, (uint8_t)(divisor & 0xFFU));
    io_out8(PIT_CHANNEL_ZERO, (uint8_t)((divisor >> 8U) & 0xFFU));
}

void pit_handle_irq(void)
{
    ++tick_count;
    if (tick_count == PIT_MILESTONE_TICK) {
        console_printf("[KERN] pit tick=%u\n", tick_count);
    }
}

uint32_t pit_ticks(void)
{
    return tick_count;
}
