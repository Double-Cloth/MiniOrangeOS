#include <minios/abi/errno.h>
#include <minios/io.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

bool minios_write_all(int32_t descriptor, const void *buffer, size_t length)
{
    const uint8_t *bytes = (const uint8_t *)buffer;
    size_t offset = 0U;

    if (buffer == NULL && length != 0U) {
        return false;
    }
    while (offset < length) {
        size_t chunk = length - offset;
        int32_t written;

        if (chunk > 4096U) {
            chunk = 4096U;
        }
        written = minios_write(descriptor, &bytes[offset], chunk);

        if (written <= 0) {
            return false;
        }
        offset += (size_t)written;
    }
    return true;
}

bool minios_print(int32_t descriptor, const char *text)
{
    return text != NULL &&
        minios_write_all(descriptor, text, minios_strlen(text));
}

bool minios_print_uint32(int32_t descriptor, uint32_t value)
{
    char digits[10];
    size_t count = 0U;
    size_t index;

    do {
        digits[count] = (char)('0' + value % 10U);
        value /= 10U;
        ++count;
    } while (value != 0U);
    for (index = 0U; index < count / 2U; ++index) {
        char temporary = digits[index];

        digits[index] = digits[count - index - 1U];
        digits[count - index - 1U] = temporary;
    }
    return minios_write_all(descriptor, digits, count);
}

bool minios_print_int32(int32_t descriptor, int32_t value)
{
    uint32_t magnitude;

    if (value >= 0) {
        return minios_print_uint32(descriptor, (uint32_t)value);
    }
    magnitude = (uint32_t)(-(int64_t)value);
    return minios_print(descriptor, "-") &&
        minios_print_uint32(descriptor, magnitude);
}

const char *minios_error_text(int32_t error)
{
    int32_t code = error < 0 ? -error : error;

    switch (code) {
    case MINIOS_ENOENT:
        return "not found";
    case MINIOS_EIO:
        return "I/O error";
    case MINIOS_E2BIG:
        return "argument list too long";
    case MINIOS_ENOEXEC:
        return "not executable";
    case MINIOS_EBADF:
        return "bad file descriptor";
    case MINIOS_ECHILD:
        return "no child process";
    case MINIOS_EAGAIN:
        return "resource temporarily unavailable";
    case MINIOS_ENOMEM:
        return "out of memory";
    case MINIOS_EFAULT:
        return "bad address";
    case MINIOS_EBUSY:
        return "resource busy";
    case MINIOS_EEXIST:
        return "already exists";
    case MINIOS_ENOTDIR:
        return "not a directory";
    case MINIOS_EISDIR:
        return "is a directory";
    case MINIOS_EINVAL:
        return "invalid argument";
    case MINIOS_ENFILE:
        return "system file table full";
    case MINIOS_EMFILE:
        return "too many open files";
    case MINIOS_ENOSPC:
        return "no space left";
    case MINIOS_ENOSYS:
        return "not implemented";
    case MINIOS_ENOTEMPTY:
        return "directory not empty";
    default:
        return "unknown error";
    }
}

bool minios_report_error(const char *command, const char *operand,
                         int32_t error)
{
    bool result = minios_print(2, command) && minios_print(2, ": ");

    if (operand != NULL) {
        result = result && minios_print(2, operand) && minios_print(2, ": ");
    }
    return result && minios_print(2, minios_error_text(error)) &&
        minios_print(2, "\n");
}
