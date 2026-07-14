#include <minios/arch/x86/gdt.h>

#include <stddef.h>
#include <stdint.h>

#define GDT_ENTRY_COUNT 3U
#define GDT_LIMIT 0x000FFFFFU
#define GDT_CODE_ACCESS 0x9AU
#define GDT_DATA_ACCESS 0x92U
#define GDT_FLAGS 0xCFU

struct gdt_entry {
    uint16_t limit_low;
    uint16_t base_low;
    uint8_t base_middle;
    uint8_t access;
    uint8_t limit_high_and_flags;
    uint8_t base_high;
} __attribute__((packed));

struct gdt_pointer {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

_Static_assert(sizeof(struct gdt_entry) == 8U, "GDT entry 必须为 8 bytes");
_Static_assert(sizeof(struct gdt_pointer) == 6U, "GDTR operand 必须为 6 bytes");

static struct gdt_entry gdt[GDT_ENTRY_COUNT];
static struct gdt_pointer gdtr;

void gdt_load(const struct gdt_pointer *pointer);

static void gdt_set_entry(size_t index, uint32_t base, uint32_t limit, uint8_t access)
{
    gdt[index].limit_low = (uint16_t)(limit & 0xFFFFU);
    gdt[index].base_low = (uint16_t)(base & 0xFFFFU);
    gdt[index].base_middle = (uint8_t)((base >> 16U) & 0xFFU);
    gdt[index].access = access;
    gdt[index].limit_high_and_flags =
        (uint8_t)(((limit >> 16U) & 0x0FU) | (GDT_FLAGS & 0xF0U));
    gdt[index].base_high = (uint8_t)((base >> 24U) & 0xFFU);
}

void gdt_init(void)
{
    gdt_set_entry(0U, 0U, 0U, 0U);
    gdt_set_entry(1U, 0U, GDT_LIMIT, GDT_CODE_ACCESS);
    gdt_set_entry(2U, 0U, GDT_LIMIT, GDT_DATA_ACCESS);

    gdtr.limit = (uint16_t)(sizeof(gdt) - 1U);
    gdtr.base = (uint32_t)(uintptr_t)&gdt[0];
    gdt_load(&gdtr);
}
