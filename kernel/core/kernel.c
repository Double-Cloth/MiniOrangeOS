#include <minios/arch/x86/gdt.h>
#include <minios/arch/x86/idt.h>
#include <minios/arch/x86/irq.h>
#include <minios/console.h>
#include <minios/drivers/pic.h>
#include <minios/drivers/pit.h>

void kernel_main(void);

void kernel_main(void)
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
    pic_init();
    console_printf("[KERN] pic ready\n");
    pit_init(100U);
    pic_unmask(0U);
    console_printf("[KERN] pit ready hz=100\n");
    irq_enable();
    console_printf("[KERN] interrupts enabled\n");
    for (;;) {
        __asm__ volatile("hlt");
    }
}
