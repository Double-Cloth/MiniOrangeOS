#include <minios/abi/minifs.h>
#include <minios/io.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

static bool print_status(const char *path, const struct minios_stat *status)
{
    const char *type = status->mode == MINIFS_MODE_DIRECTORY ?
        "directory" : "file";

    return minios_print(1, path) && minios_print(1, ": type=") &&
        minios_print(1, type) && minios_print(1, " inode=") &&
        minios_print_uint32(1, status->inode) &&
        minios_print(1, " links=") &&
        minios_print_uint32(1, status->link_count) &&
        minios_print(1, " size=") &&
        minios_print_uint32(1, status->size) && minios_print(1, "\n");
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    bool success = true;
    int index;

    if (argc < 2 || argv == NULL || argv[0] == NULL) {
        (void)minios_print(2, "usage: stat path...\n");
        return 2;
    }
    for (index = 1; index < argc; ++index) {
        struct minios_stat status;
        int32_t result;

        if (argv[index] == NULL) {
            return 2;
        }
        result = minios_stat(argv[index], &status);
        if (result < 0) {
            (void)minios_report_error("stat", argv[index], result);
            success = false;
        } else if (!print_status(argv[index], &status)) {
            success = false;
        }
    }
    return success ? 0 : 1;
}
