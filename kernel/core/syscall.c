#include <minios/console.h>
#include <minios/arch/x86/irq.h>
#include <minios/errno.h>
#include <minios/drivers/keyboard.h>
#include <minios/drivers/pit.h>
#include <minios/mm/usercopy.h>
#include <minios/panic.h>
#include <minios/proc/program_registry.h>
#include <minios/proc/scheduler.h>
#include <minios/syscall.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SYSCALL_USER_PRIVILEGE 3U
#define SYSCALL_WRITE_BUFFER_SIZE 128U
#define SYSCALL_WRITE_MAX 4096U
#define SYSCALL_PATH_MAX 256U
#define SYSCALL_ARGUMENT_LIMIT 16U
#define SYSCALL_ARGUMENT_LENGTH 64U
#define SYSCALL_ARGUMENT_BYTES 1024U

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

static int32_t syscall_read(uint32_t descriptor, void *user_buffer,
                            size_t length)
{
    char character;

    if (descriptor != 0U) {
        return -MINIOS_EBADF;
    }
    if (length > SYSCALL_WRITE_MAX) {
        return -MINIOS_EINVAL;
    }
    if (!validate_user_range(user_buffer, length, USER_ACCESS_WRITE)) {
        return -MINIOS_EFAULT;
    }
    if (length == 0U) {
        return 0;
    }
    while (!keyboard_try_read(&character)) {
        irq_enable();
        __asm__ volatile("hlt");
        (void)irq_save_disable();
    }
    if (copy_to_user(user_buffer, &character, 1U) != 0) {
        return -MINIOS_EFAULT;
    }
    return 1;
}

static size_t bounded_length(const char *value, size_t limit)
{
    size_t length;

    for (length = 0U; length < limit; ++length) {
        if (value[length] == '\0') {
            return length;
        }
    }
    return limit;
}

static int32_t syscall_spawn(const char *user_path,
                             const void *user_argv)
{
    char path[SYSCALL_PATH_MAX];
    char argument_storage[SYSCALL_ARGUMENT_LIMIT][SYSCALL_ARGUMENT_LENGTH];
    const char *arguments[SYSCALL_ARGUMENT_LIMIT + 1U];
    const uint8_t *image;
    size_t image_size;
    size_t argument_count;
    size_t argument_bytes = 0U;
    bool terminated = false;

    if (copy_user_string(path, user_path, sizeof(path)) != 0 ||
        user_argv == NULL ||
        !validate_user_range(user_argv,
                             SYSCALL_ARGUMENT_LIMIT * sizeof(uint32_t),
                             USER_ACCESS_READ)) {
        return -MINIOS_EFAULT;
    }
    if (path[0] == '\0') {
        return -MINIOS_EINVAL;
    }
    for (argument_count = 0U;
         argument_count < SYSCALL_ARGUMENT_LIMIT;
         ++argument_count) {
        uint32_t user_argument = 0U;
        const void *user_slot = (const void *)(
            (uintptr_t)user_argv + argument_count * sizeof(uint32_t)
        );
        size_t length;

        if (copy_from_user(&user_argument, user_slot,
                           sizeof(user_argument)) != 0) {
            return -MINIOS_EFAULT;
        }
        if (user_argument == 0U) {
            terminated = true;
            break;
        }
        if (copy_user_string(argument_storage[argument_count],
                             (const char *)(uintptr_t)user_argument,
                             SYSCALL_ARGUMENT_LENGTH) != 0) {
            return -MINIOS_EFAULT;
        }
        length = bounded_length(argument_storage[argument_count],
                                SYSCALL_ARGUMENT_LENGTH);
        if (length == SYSCALL_ARGUMENT_LENGTH ||
            length + 1U > SYSCALL_ARGUMENT_BYTES - argument_bytes) {
            return -MINIOS_E2BIG;
        }
        argument_bytes += length + 1U;
        arguments[argument_count] = argument_storage[argument_count];
    }
    if (!terminated || argument_count == 0U) {
        return -MINIOS_E2BIG;
    }
    arguments[argument_count] = NULL;
    if (!program_registry_lookup(path, &image, &image_size)) {
        return -MINIOS_ENOENT;
    }
    return scheduler_spawn_image(path, image, image_size, arguments);
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
        case SYS_read:
            result = syscall_read(
                frame->ebx,
                (void *)(uintptr_t)frame->ecx,
                (size_t)frame->edx
            );
            break;
        case SYS_spawn:
            result = syscall_spawn(
                (const char *)(uintptr_t)frame->ebx,
                (const void *)(uintptr_t)frame->ecx
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
