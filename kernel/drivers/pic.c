#include <minios/arch/x86/io.h>
#include <minios/drivers/pic.h>
#include <minios/panic.h>

#include <stdint.h>

#define PIC_MASTER_COMMAND 0x20
#define PIC_MASTER_DATA 0x21
#define PIC_SLAVE_COMMAND 0xA0
#define PIC_SLAVE_DATA 0xA1
#define PIC_MASTER_OFFSET 0x20
#define PIC_SLAVE_OFFSET 0x28
#define PIC_INITIALIZE 0x11
#define PIC_8086_MODE 0x01
#define PIC_EOI 0x20
#define PIC_CASCADE_IRQ 2U
#define IO_WAIT_PORT 0x80

static void pic_write(uint16_t port, uint8_t value)
{
    io_out8(port, value);
    io_out8(IO_WAIT_PORT, 0U);
}

void pic_init(void)
{
    pic_write(PIC_MASTER_COMMAND, PIC_INITIALIZE);
    pic_write(PIC_SLAVE_COMMAND, PIC_INITIALIZE);
    pic_write(PIC_MASTER_DATA, PIC_MASTER_OFFSET);
    pic_write(PIC_SLAVE_DATA, PIC_SLAVE_OFFSET);
    pic_write(PIC_MASTER_DATA, 1U << PIC_CASCADE_IRQ);
    pic_write(PIC_SLAVE_DATA, PIC_CASCADE_IRQ);
    pic_write(PIC_MASTER_DATA, PIC_8086_MODE);
    pic_write(PIC_SLAVE_DATA, PIC_8086_MODE);
    io_out8(PIC_MASTER_DATA, 0xFFU);
    io_out8(PIC_SLAVE_DATA, 0xFFU);
}

void pic_unmask(uint8_t irq)
{
    uint16_t port;
    uint8_t bit;
    uint8_t mask;

    if (irq >= 16U) {
        panicf("invalid irq=%u", (uint32_t)irq);
    }
    if (irq >= 8U) {
        port = PIC_SLAVE_DATA;
        bit = (uint8_t)(irq - 8U);
        mask = io_in8(PIC_MASTER_DATA);
        io_out8(PIC_MASTER_DATA, (uint8_t)(mask & ~(1U << PIC_CASCADE_IRQ)));
    } else {
        port = PIC_MASTER_DATA;
        bit = irq;
    }
    mask = io_in8(port);
    io_out8(port, (uint8_t)(mask & ~(1U << bit)));
}

void pic_send_eoi(uint8_t irq)
{
    if (irq >= 8U) {
        io_out8(PIC_SLAVE_COMMAND, PIC_EOI);
    }
    io_out8(PIC_MASTER_COMMAND, PIC_EOI);
}
