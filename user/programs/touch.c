#include <minios/abi/errno.h>
#include <minios/io.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    bool success = true;
    int index;

    if (argc < 2 || argv == NULL || argv[0] == NULL) {
        (void)minios_print(2, "usage: touch file...\n");
        return 2;
    }
    for (index = 1; index < argc; ++index) {
        int32_t descriptor;

        if (argv[index] == NULL) {
            return 2;
        }
        descriptor = minios_open(
            argv[index], MINIOS_O_WRONLY | MINIOS_O_CREAT
        );
        if (descriptor < 3) {
            (void)minios_report_error("touch", argv[index], descriptor);
            success = false;
        } else if (minios_close(descriptor) < 0) {
            (void)minios_report_error(
                "touch", argv[index], -MINIOS_EIO
            );
            success = false;
        }
    }
    return success ? 0 : 1;
}
