#include <minios/console.h>
#include <minios/abi/file.h>
#include <minios/abi/minifs.h>
#include <minios/arch/x86/irq.h>
#include <minios/errno.h>
#include <minios/drivers/keyboard.h>
#include <minios/drivers/pit.h>
#include <minios/fs/vfs.h>
#include <minios/mm/heap.h>
#include <minios/mm/usercopy.h>
#include <minios/panic.h>
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
    uint8_t buffer[SYSCALL_WRITE_BUFFER_SIZE];
    size_t offset = 0U;

    if (descriptor == 0U || descriptor >= MINIOS_PROCESS_FD_LIMIT) {
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
        int32_t written;

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
        if (descriptor == 1U || descriptor == 2U) {
            size_t index;

            for (index = 0U; index < chunk; ++index) {
                console_putc((char)buffer[index]);
            }
            written = (int32_t)chunk;
        } else {
            written = vfs_write((int32_t)descriptor, buffer, chunk);
        }
        if (written < 0) {
            return offset == 0U ? written : (int32_t)offset;
        }
        offset += (size_t)written;
        if ((size_t)written < chunk) {
            break;
        }
    }
    return (int32_t)offset;
}

static int32_t syscall_read(uint32_t descriptor, void *user_buffer,
                            size_t length)
{
    uint8_t buffer[SYSCALL_WRITE_BUFFER_SIZE];
    size_t offset = 0U;

    if (descriptor == 1U || descriptor == 2U ||
        descriptor >= MINIOS_PROCESS_FD_LIMIT) {
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
    if (descriptor == 0U) {
        char character;

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
    while (offset < length) {
        size_t chunk = length - offset;
        int32_t read;

        if (chunk > sizeof(buffer)) {
            chunk = sizeof(buffer);
        }
        read = vfs_read((int32_t)descriptor, buffer, chunk);
        if (read < 0) {
            return offset == 0U ? read : (int32_t)offset;
        }
        if (read == 0) {
            break;
        }
        if (copy_to_user((void *)((uintptr_t)user_buffer + offset),
                         buffer, (size_t)read) != 0) {
            return offset == 0U ? -MINIOS_EFAULT : (int32_t)offset;
        }
        offset += (size_t)read;
        if ((size_t)read < chunk) {
            break;
        }
    }
    return (int32_t)offset;
}

static int32_t copy_syscall_path(char *path, const char *user_path)
{
    if (copy_user_string(path, user_path, SYSCALL_PATH_MAX) != 0) {
        return -MINIOS_EFAULT;
    }
    return path[0] == '\0' ? -MINIOS_EINVAL : 0;
}

static int32_t syscall_open(const char *user_path, uint32_t flags)
{
    char path[SYSCALL_PATH_MAX];
    int32_t result = copy_syscall_path(path, user_path);

    return result < 0 ? result : vfs_open(path, flags);
}

static int32_t syscall_create(const char *user_path)
{
    int32_t descriptor = syscall_open(
        user_path, MINIOS_O_WRONLY | MINIOS_O_CREAT
    );

    return descriptor < 0 ? descriptor : vfs_close(descriptor);
}

static int32_t syscall_stat(const char *user_path, void *user_status)
{
    struct minios_stat status;
    char path[SYSCALL_PATH_MAX];
    int32_t result;

    if (!validate_user_range(user_status, sizeof(status), USER_ACCESS_WRITE)) {
        return -MINIOS_EFAULT;
    }
    result = copy_syscall_path(path, user_path);
    if (result < 0) {
        return result;
    }
    result = vfs_stat(path, &status);
    if (result < 0) {
        return result;
    }
    return copy_to_user(user_status, &status, sizeof(status)) == 0 ?
        0 : -MINIOS_EFAULT;
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
    struct minios_stat status;
    uint8_t *image = NULL;
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
    {
        int32_t descriptor;
        int32_t result = vfs_stat(path, &status);

        if (result < 0) {
            return result;
        }
        if (status.mode == MINIFS_MODE_DIRECTORY) {
            return -MINIOS_EISDIR;
        }
        if (status.size == 0U) {
            return -MINIOS_ENOEXEC;
        }
        image = (uint8_t *)kmalloc(status.size);
        if (image == NULL) {
            return -MINIOS_ENOMEM;
        }
        descriptor = vfs_open(path, MINIOS_O_RDONLY);
        if (descriptor < 0 ||
            vfs_read(descriptor, image, status.size) !=
                (int32_t)status.size ||
            vfs_close(descriptor) != 0) {
            if (descriptor >= 0) {
                (void)vfs_close(descriptor);
            }
            if (!kfree(image)) {
                panic("spawn image buffer rollback failed");
            }
            return descriptor < 0 ? descriptor : -MINIOS_EIO;
        }
        result = scheduler_spawn_image(path, image, status.size, arguments);
        if (!kfree(image)) {
            panic("spawn image buffer release failed");
        }
        return result;
    }
}

static int32_t syscall_ps(void *user_processes, size_t capacity)
{
    struct minios_process_info processes[MINIOS_PROCESS_LIMIT];
    size_t count;
    size_t bytes;

    if (capacity > MINIOS_PROCESS_LIMIT) {
        return -MINIOS_EINVAL;
    }
    bytes = capacity * sizeof(processes[0]);
    if (!validate_user_range(user_processes, bytes, USER_ACCESS_WRITE)) {
        return -MINIOS_EFAULT;
    }
    count = scheduler_process_snapshot(processes, capacity);
    bytes = count * sizeof(processes[0]);
    if (copy_to_user(user_processes, processes, bytes) != 0) {
        return -MINIOS_EFAULT;
    }
    return (int32_t)count;
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
        case SYS_open:
            result = syscall_open(
                (const char *)(uintptr_t)frame->ebx,
                frame->ecx
            );
            break;
        case SYS_close:
            result = vfs_close((int32_t)frame->ebx);
            break;
        case SYS_lseek:
            result = vfs_lseek(
                (int32_t)frame->ebx,
                (int32_t)frame->ecx,
                (int32_t)frame->edx
            );
            break;
        case SYS_create:
            result = syscall_create(
                (const char *)(uintptr_t)frame->ebx
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
        case SYS_stat:
            result = syscall_stat(
                (const char *)(uintptr_t)frame->ebx,
                (void *)(uintptr_t)frame->ecx
            );
            break;
        case SYS_ps:
            result = syscall_ps(
                (void *)(uintptr_t)frame->ebx,
                (size_t)frame->ecx
            );
            break;
        default:
            result = -MINIOS_ENOSYS;
            break;
        }
    }
    frame->eax = (uint32_t)result;
}
