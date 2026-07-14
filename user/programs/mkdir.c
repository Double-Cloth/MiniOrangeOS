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
        (void)minios_print(2, "usage: mkdir directory...\n");
        return 2;
    }
    for (index = 1; index < argc; ++index) {
        int32_t result;

        if (argv[index] == NULL) {
            return 2;
        }
        result = minios_mkdir(argv[index]);
        if (result < 0) {
            (void)minios_report_error("mkdir", argv[index], result);
            success = false;
        }
    }
    return success ? 0 : 1;
}
