#include <minios/abi/errno.h>
#include <minios/io.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

static bool copy_file(const char *path)
{
    uint8_t buffer[256];
    int32_t descriptor = minios_open(path, MINIOS_O_RDONLY);
    int32_t result;

    if (descriptor < 3) {
        (void)minios_report_error("cat", path, descriptor);
        return false;
    }
    while ((result = minios_read(descriptor, buffer, sizeof(buffer))) > 0) {
        if (!minios_write_all(1, buffer, (size_t)result)) {
            (void)minios_report_error("cat", path, -MINIOS_EIO);
            (void)minios_close(descriptor);
            return false;
        }
    }
    if (result < 0) {
        (void)minios_report_error("cat", path, result);
    }
    if (minios_close(descriptor) < 0) {
        (void)minios_report_error("cat", path, -MINIOS_EIO);
        return false;
    }
    return result == 0;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    bool success = true;
    int index;

    if (argc < 2 || argv == NULL || argv[0] == NULL) {
        (void)minios_print(2, "usage: cat file...\n");
        return 2;
    }
    for (index = 1; index < argc; ++index) {
        if (argv[index] == NULL) {
            return 2;
        }
        if (!copy_file(argv[index])) {
            success = false;
        }
    }
    return success ? 0 : 1;
}
