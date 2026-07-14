#include <minios/arch/x86/trap_frame.h>
#include <minios/arch/x86/page_fault.h>
#include <minios/panic.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PAGE_FAULT_VECTOR 14U
#define PAGE_FAULT_USER 0x04U

static user_page_fault_handler user_fault_handler;

void exception_dispatch(const struct trap_frame *frame);

static uint32_t read_cr2(void)
{
    uint32_t address;
    __asm__ volatile("mov %%cr2, %0" : "=r"(address));
    return address;
}

static bool page_fault_is_user(uint32_t error_code)
{
    return (error_code & PAGE_FAULT_USER) != 0U;
}

void page_fault_set_user_handler(user_page_fault_handler handler)
{
    user_fault_handler = handler;
}

bool page_fault_self_test(void)
{
    return !page_fault_is_user(0U) && page_fault_is_user(PAGE_FAULT_USER);
}

void exception_dispatch(const struct trap_frame *frame)
{
    if (frame->vector == PAGE_FAULT_VECTOR) {
        uint32_t address = read_cr2();

        if (page_fault_is_user(frame->error_code) &&
            user_fault_handler != NULL &&
            user_fault_handler(address, frame->error_code, frame)) {
            return;
        }
        panicf(
            "%s page fault address=%p error=%x eip=%p",
            page_fault_is_user(frame->error_code) ? "user" : "kernel",
            (void *)(uintptr_t)address,
            frame->error_code,
            (void *)(uintptr_t)frame->eip
        );
    }
    panicf(
        "exception vector=%u error=%x eip=%p",
        frame->vector,
        frame->error_code,
        (void *)(uintptr_t)frame->eip
    );
}
