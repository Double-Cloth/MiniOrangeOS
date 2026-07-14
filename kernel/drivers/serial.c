#include <minios/arch/x86/io.h>
#include <minios/drivers/serial.h>

#include <stdint.h>

#define COM1_BASE 0x03F8
#define COM1_INTERRUPT_ENABLE (COM1_BASE + 1)
#define COM1_FIFO_CONTROL (COM1_BASE + 2)
#define COM1_LINE_CONTROL (COM1_BASE + 3)
#define COM1_MODEM_CONTROL (COM1_BASE + 4)
#define COM1_LINE_STATUS (COM1_BASE + 5)
#define COM1_TRANSMIT_READY 0x20
#define SERIAL_POLL_LIMIT 0x0000FFFFU

void serial_init(void)
{
    io_out8(COM1_INTERRUPT_ENABLE, 0x00);
    io_out8(COM1_LINE_CONTROL, 0x80);
    io_out8(COM1_BASE, 0x03);
    io_out8(COM1_INTERRUPT_ENABLE, 0x00);
    io_out8(COM1_LINE_CONTROL, 0x03);
    io_out8(COM1_FIFO_CONTROL, 0xC7);
    io_out8(COM1_MODEM_CONTROL, 0x0B);
}

void serial_write_char(char character)
{
    uint32_t remaining = SERIAL_POLL_LIMIT;

    while (remaining > 0U) {
        if ((io_in8(COM1_LINE_STATUS) & COM1_TRANSMIT_READY) != 0U) {
            io_out8(COM1_BASE, (uint8_t)character);
            return;
        }
        --remaining;
    }
}
