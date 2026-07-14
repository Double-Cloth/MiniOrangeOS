#include <minios/arch/x86/gdt.h>
#include <minios/arch/x86/idt.h>
#include <minios/arch/x86/irq.h>
#include <minios/arch/x86/page_fault.h>
#include <minios/boot_info.h>
#include <minios/console.h>
#include <minios/drivers/keyboard.h>
#include <minios/drivers/pic.h>
#include <minios/drivers/pit.h>
#include <minios/mm/heap.h>
#include <minios/mm/address_space.h>
#include <minios/mm/pmm.h>
#include <minios/mm/usercopy.h>
#include <minios/mm/vmm.h>
#include <minios/panic.h>
#include <minios/proc/scheduler.h>

#include <stdint.h>

void kernel_main(const struct boot_info *boot_info);

void kernel_main(const struct boot_info *boot_info)
{
    console_init();
    console_printf("[KERN] console ready hex=%x dec=%u str=%s\n", 0xC0FFEEU, 42U, "ok");
    gdt_init();
    console_printf("[KERN] gdt ready\n");
    console_printf("[KERN] tss ready\n");
    idt_init();
    console_printf("[KERN] idt ready\n");
#if MINIOS_TEST_BREAKPOINT == 1
    __asm__ volatile("int3");
#endif
#if MINIOS_TEST_PAGE_FAULT == 1
    (void)*(volatile uint32_t *)(uintptr_t)0x00400000U;
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
    heap_init();
    console_printf("[KERN] heap ready\n");
    if (!heap_self_test()) {
        panic("heap self-test failed");
    }
    console_printf("[KERN] heap self-test PASS\n");
    console_printf("[KERN] user memory ready\n");
    if (!vmm_address_space_self_test() || !usercopy_self_test() ||
        !page_fault_self_test()) {
        panic("user memory self-test failed");
    }
    console_printf("[KERN] user memory self-test PASS\n");
    scheduler_init();
    console_printf("[KERN] scheduler ready\n");
    if (!scheduler_self_test()) {
        panic("scheduler self-test failed");
    }
    console_printf("[KERN] scheduler self-test PASS\n");
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
    if (!scheduler_preemption_self_test()) {
        panic("scheduler preemption self-test failed");
    }
    console_printf("[KERN] scheduler preemption PASS\n");
    if (!scheduler_lifecycle_self_test()) {
        panic("process lifecycle self-test failed");
    }
    console_printf("[KERN] process lifecycle self-test PASS\n");
    if (!user_process_self_test()) {
        panic("Ring 3 syscall self-test failed");
    }
    console_printf("[KERN] ring3 syscall self-test PASS\n");
    if (!user_elf_self_test()) {
        panic("ELF user process self-test failed");
    }
    console_printf("[KERN] ELF user process self-test PASS\n");
    if (!user_page_fault_self_test()) {
        panic("user page-fault isolation self-test failed");
    }
    console_printf("[KERN] user fault isolation PASS\n");
    for (;;) {
        __asm__ volatile("hlt");
    }
}
