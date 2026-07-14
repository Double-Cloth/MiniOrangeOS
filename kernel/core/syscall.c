#include <minios/console.h>
#include <minios/errno.h>
#include <minios/drivers/pit.h>
#include <minios/mm/usercopy.h>
#include <minios/panic.h>
#include <minios/proc/scheduler.h>
#include <minios/syscall.h>

#include <stddef.h>
#include <stdint.h>

#define SYSCALL_USER_PRIVILEGE 3U
#define SYSCALL_WRITE_BUFFER_SIZE 128U
#define SYSCALL_WRITE_MAX 4096U

static int32_t syscall_write(uint32_t descriptor, const void *user_buffer,
                             size_t length)
{
    char buffer[SYSCALL_WRITE_BUFFER_SIZE];
    size_t offset = 0U;

    if (descriptor != 1U && descriptor != 2U) {
        return -MINIOS_EBADF;
    }
    if (length > SYSCALL_WRITE_MAX) {
        return -MINIOS_EINVAL;
    }
    if (!validate_user_range(user_buffer, length, USER_ACCESS_READ)) {
        return -MINIOS_EFAULT;
    }
    while (offset < length) {
        size_t chunk = length - offset;
        size_t index;

        if (chunk > sizeof(buffer)) {
            chunk = sizeof(buffer);
        }
        if (copy_from_user(
                buffer,
                (const void *)((uintptr_t)user_buffer + offset),
                chunk
            ) != 0) {
            return -MINIOS_EFAULT;
        }
        for (index = 0U; index < chunk; ++index) {
            console_putc(buffer[index]);
        }
        offset += chunk;
    }
    return (int32_t)length;
}

void syscall_dispatch(struct trap_frame *frame)
{
    int32_t result;

    if (frame == NULL) {
        panic("null syscall frame");
    }
    if ((frame->cs & SYSCALL_USER_PRIVILEGE) != SYSCALL_USER_PRIVILEGE) {
        result = -MINIOS_ENOSYS;
    } else {
        switch (frame->eax) {
        case SYS_exit:
            scheduler_exit_current((int32_t)frame->ebx);
        case SYS_write:
            result = syscall_write(
                frame->ebx,
                (const void *)(uintptr_t)frame->ecx,
                (size_t)frame->edx
            );
            break;
        case SYS_getpid:
            result = (int32_t)scheduler_current_pid();
            break;
        case SYS_yield:
            scheduler_yield();
            result = 0;
            break;
        case SYS_sleep:
            result = scheduler_sleep_current(frame->ebx) ? 0 :
                -MINIOS_EINVAL;
            break;
        case SYS_waitpid:
            if (frame->ecx != 0U &&
                !validate_user_range((const void *)(uintptr_t)frame->ecx,
                                     sizeof(int32_t), USER_ACCESS_WRITE)) {
                result = -MINIOS_EFAULT;
            } else {
                int32_t exit_code = 0;

                result = scheduler_waitpid((int32_t)frame->ebx,
                                           &exit_code);
                if (result >= 0 && frame->ecx != 0U &&
                    copy_to_user((void *)(uintptr_t)frame->ecx,
                                 &exit_code, sizeof(exit_code)) != 0) {
                    result = -MINIOS_EFAULT;
                }
            }
            break;
        case SYS_getticks:
            result = (int32_t)pit_ticks();
            break;
        default:
            result = -MINIOS_ENOSYS;
            break;
        }
    }
    frame->eax = (uint32_t)result;
}
