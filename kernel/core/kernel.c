#include <minios/arch/x86/gdt.h>
#include <minios/arch/x86/idt.h>
#include <minios/arch/x86/irq.h>
#include <minios/boot_info.h>
#include <minios/console.h>
#include <minios/drivers/keyboard.h>
#include <minios/drivers/pic.h>
#include <minios/drivers/pit.h>
#include <minios/mm/pmm.h>
#include <minios/mm/vmm.h>
#include <minios/panic.h>

void kernel_main(const struct boot_info *boot_info);

void kernel_main(const struct boot_info *boot_info)
{
    console_init();
    console_printf("[KERN] console ready hex=%x dec=%u str=%s\n", 0xC0FFEEU, 42U, "ok");
    gdt_init();
    console_printf("[KERN] gdt ready\n");
    idt_init();
    console_printf("[KERN] idt ready\n");
#if MINIOS_TEST_BREAKPOINT == 1
    __asm__ volatile("int3");
#endif
    pmm_init(boot_info);
    {
        struct pmm_stats stats = pmm_get_stats();
        console_printf(
            "[KERN] pmm pages total=%u free=%u reserved=%u\n",
            stats.total_pages,
            stats.free_pages,
            stats.reserved_pages
        );
    }
    if (!pmm_self_test()) {
        panic("PMM self-test failed");
    }
    console_printf("[KERN] pmm self-test PASS\n");
    vmm_init(boot_info);
    console_printf("[KERN] vmm ready identity=off wp=on\n");
    if (!vmm_self_test()) {
        panic("VMM self-test failed");
    }
    console_printf("[KERN] vmm self-test PASS\n");
    pic_init();
    console_printf("[KERN] pic ready\n");
    pit_init(100U);
    pic_unmask(0U);
    console_printf("[KERN] pit ready hz=100\n");
    keyboard_init();
    pic_unmask(1U);
    console_printf("[KERN] keyboard ready\n");
    irq_enable();
    console_printf("[KERN] interrupts enabled\n");
    for (;;) {
        __asm__ volatile("hlt");
    }
}
