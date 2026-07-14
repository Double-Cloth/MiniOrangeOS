#include <minios/panic.h>

#include <stdint.h>

struct trap_frame {
    uint32_t edi;
    uint32_t esi;
    uint32_t ebp;
    uint32_t esp_before_pushad;
    uint32_t ebx;
    uint32_t edx;
    uint32_t ecx;
    uint32_t eax;
    uint32_t vector;
    uint32_t error_code;
    uint32_t eip;
    uint32_t cs;
    uint32_t eflags;
};

_Noreturn void exception_dispatch(const struct trap_frame *frame);

_Noreturn void exception_dispatch(const struct trap_frame *frame)
{
    panicf(
        "exception vector=%u error=%x eip=%p",
        frame->vector,
        frame->error_code,
        (void *)(uintptr_t)frame->eip
    );
}
