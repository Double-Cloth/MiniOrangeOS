#include <minios/abi/errno.h>
#include <minios/io.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    bool force = false;
    bool success = true;
    int first_path = 1;
    int index;

    if (argc > 1 && argv != NULL && argv[1] != NULL &&
        minios_streq(argv[1], "-f")) {
        force = true;
        first_path = 2;
    }
    if (argc <= first_path || argv == NULL || argv[0] == NULL) {
        (void)minios_print(2, "usage: rm [-f] path...\n");
        return 2;
    }
    for (index = first_path; index < argc; ++index) {
        int32_t result;

        if (argv[index] == NULL) {
            return 2;
        }
        result = minios_unlink(argv[index]);
        if (result < 0 && !(force && result == -MINIOS_ENOENT)) {
            (void)minios_report_error("rm", argv[index], result);
            success = false;
        }
    }
    return success ? 0 : 1;
}
