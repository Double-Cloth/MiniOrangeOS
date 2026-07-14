#include <minios/arch/x86/idt.h>

#include <stddef.h>
#include <stdint.h>

#define IDT_ENTRY_COUNT 256
#define CPU_EXCEPTION_COUNT 32U
#define KERNEL_CODE_SELECTOR 0x0008U
#define IDT_INTERRUPT_GATE 0x8EU

struct idt_entry {
    uint16_t offset_low;
    uint16_t selector;
    uint8_t zero;
    uint8_t type_attributes;
    uint16_t offset_high;
} __attribute__((packed));

struct idt_pointer {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

_Static_assert(sizeof(struct idt_entry) == 8U, "IDT entry 必须为 8 bytes");
_Static_assert(sizeof(struct idt_pointer) == 6U, "IDTR operand 必须为 6 bytes");

extern void (*exception_stub_table[CPU_EXCEPTION_COUNT])(void);
void idt_load(const struct idt_pointer *pointer);

static struct idt_entry idt[IDT_ENTRY_COUNT];
static struct idt_pointer idtr;

static void idt_set_gate(size_t index, void (*handler)(void))
{
    uint32_t address = (uint32_t)(uintptr_t)handler;

    idt[index].offset_low = (uint16_t)(address & 0xFFFFU);
    idt[index].selector = KERNEL_CODE_SELECTOR;
    idt[index].zero = 0U;
    idt[index].type_attributes = IDT_INTERRUPT_GATE;
    idt[index].offset_high = (uint16_t)((address >> 16U) & 0xFFFFU);
}

void idt_init(void)
{
    size_t index;

    for (index = 0U; index < IDT_ENTRY_COUNT; ++index) {
        idt[index].offset_low = 0U;
        idt[index].selector = 0U;
        idt[index].zero = 0U;
        idt[index].type_attributes = 0U;
        idt[index].offset_high = 0U;
    }
    for (index = 0U; index < CPU_EXCEPTION_COUNT; ++index) {
        idt_set_gate(index, exception_stub_table[index]);
    }

    idtr.limit = (uint16_t)(sizeof(idt) - 1U);
    idtr.base = (uint32_t)(uintptr_t)&idt[0];
    idt_load(&idtr);
}
