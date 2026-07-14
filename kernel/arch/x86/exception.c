#include <minios/arch/x86/trap_frame.h>
#include <minios/panic.h>

#include <stdint.h>

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
