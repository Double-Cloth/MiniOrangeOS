#include <minios/string.h>
#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

static void report_open_error(int32_t error)
{
    char digits[10];
    uint32_t value = (uint32_t)(-(int64_t)error);
    size_t count = 0U;

    (void)minios_write(2, "write: open failed code=-", 25U);
    do {
        digits[count] = (char)('0' + value % 10U);
        value /= 10U;
        ++count;
    } while (value != 0U);
    while (count > 0U) {
        --count;
        (void)minios_write(2, &digits[count], 1U);
    }
    (void)minios_write(2, "\n", 1U);
}

int main(int argc, char **argv)
{
    int32_t descriptor;
    int index;

    if (argc < 3 || argv == NULL || argv[0] == NULL || argv[1] == NULL) {
        return 2;
    }
    descriptor = minios_open(
        argv[1], MINIOS_O_WRONLY | MINIOS_O_CREAT | MINIOS_O_TRUNC
    );
    if (descriptor < 3) {
        report_open_error(descriptor);
        return 1;
    }
    for (index = 2; index < argc; ++index) {
        size_t length;

        if (argv[index] == NULL ||
            (index > 2 && minios_write(descriptor, " ", 1U) != 1)) {
            (void)minios_write(2, "write: data failed\n", 19U);
            (void)minios_close(descriptor);
            return 1;
        }
        length = minios_strlen(argv[index]);
        if (minios_write(descriptor, argv[index], length) !=
            (int32_t)length) {
            (void)minios_write(2, "write: data failed\n", 19U);
            (void)minios_close(descriptor);
            return 1;
        }
    }
    if (minios_write(descriptor, "\n", 1U) != 1) {
        (void)minios_write(2, "write: data failed\n", 19U);
        (void)minios_close(descriptor);
        return 1;
    }
    if (minios_close(descriptor) != 0) {
        (void)minios_write(2, "write: close failed\n", 20U);
        return 1;
    }
    return 0;
}
