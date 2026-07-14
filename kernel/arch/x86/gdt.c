#include <minios/arch/x86/gdt.h>
#include <minios/panic.h>

#include <stddef.h>
#include <stdint.h>

#define GDT_ENTRY_COUNT 6U
#define GDT_LIMIT 0x000FFFFFU
#define GDT_CODE_ACCESS 0x9AU
#define GDT_DATA_ACCESS 0x92U
#define GDT_USER_CODE_ACCESS 0xFAU
#define GDT_USER_DATA_ACCESS 0xF2U
#define GDT_TSS_ACCESS 0x89U
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

struct task_state_segment {
    uint32_t previous_task_link;
    uint32_t esp0;
    uint32_t ss0;
    uint32_t esp1;
    uint32_t ss1;
    uint32_t esp2;
    uint32_t ss2;
    uint32_t cr3;
    uint32_t eip;
    uint32_t eflags;
    uint32_t eax;
    uint32_t ecx;
    uint32_t edx;
    uint32_t ebx;
    uint32_t esp;
    uint32_t ebp;
    uint32_t esi;
    uint32_t edi;
    uint32_t es;
    uint32_t cs;
    uint32_t ss;
    uint32_t ds;
    uint32_t fs;
    uint32_t gs;
    uint32_t ldt;
    uint16_t trap;
    uint16_t io_map_base;
} __attribute__((packed));

_Static_assert(sizeof(struct gdt_entry) == 8U, "GDT entry 必须为 8 bytes");
_Static_assert(sizeof(struct gdt_pointer) == 6U, "GDTR operand 必须为 6 bytes");
_Static_assert(sizeof(struct task_state_segment) == 104U,
               "32-bit TSS 必须为 104 bytes");

static struct gdt_entry gdt[GDT_ENTRY_COUNT];
static struct gdt_pointer gdtr;
static struct task_state_segment tss;

void gdt_load(const struct gdt_pointer *pointer);
void tss_load(uint16_t selector);

static void gdt_set_entry(size_t index, uint32_t base, uint32_t limit,
                          uint8_t access, uint8_t flags)
{
    gdt[index].limit_low = (uint16_t)(limit & 0xFFFFU);
    gdt[index].base_low = (uint16_t)(base & 0xFFFFU);
    gdt[index].base_middle = (uint8_t)((base >> 16U) & 0xFFU);
    gdt[index].access = access;
    gdt[index].limit_high_and_flags =
        (uint8_t)(((limit >> 16U) & 0x0FU) | (flags & 0xF0U));
    gdt[index].base_high = (uint8_t)((base >> 24U) & 0xFFU);
}

void gdt_init(void)
{
    uint32_t stack_top;

    __asm__ volatile("mov %%esp, %0" : "=r"(stack_top));
    tss.ss0 = GDT_KERNEL_DATA_SELECTOR;
    tss.esp0 = stack_top;
    tss.io_map_base = (uint16_t)sizeof(tss);

    gdt_set_entry(0U, 0U, 0U, 0U, 0U);
    gdt_set_entry(1U, 0U, GDT_LIMIT, GDT_CODE_ACCESS, GDT_FLAGS);
    gdt_set_entry(2U, 0U, GDT_LIMIT, GDT_DATA_ACCESS, GDT_FLAGS);
    gdt_set_entry(3U, 0U, GDT_LIMIT, GDT_USER_CODE_ACCESS, GDT_FLAGS);
    gdt_set_entry(4U, 0U, GDT_LIMIT, GDT_USER_DATA_ACCESS, GDT_FLAGS);
    gdt_set_entry(5U, (uint32_t)(uintptr_t)&tss,
                  (uint32_t)sizeof(tss) - 1U, GDT_TSS_ACCESS, 0U);

    gdtr.limit = (uint16_t)(sizeof(gdt) - 1U);
    gdtr.base = (uint32_t)(uintptr_t)&gdt[0];
    gdt_load(&gdtr);
    tss_load((uint16_t)GDT_TSS_SELECTOR);
}

void gdt_set_kernel_stack(uint32_t stack_top)
{
    if (stack_top == 0U) {
        panic("TSS kernel stack cannot be null");
    }
    tss.esp0 = stack_top;
}
