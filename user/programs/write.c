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
    bool newline = true;
    int path_index = 1;
    int32_t descriptor;
    int index;

    if (argc > 1 && argv != NULL && argv[1] != NULL &&
        minios_streq(argv[1], "-n")) {
        newline = false;
        path_index = 2;
    }
    if (argc <= path_index || argv == NULL || argv[0] == NULL ||
        argv[path_index] == NULL) {
        (void)minios_print(2, "usage: write [-n] file [text...]\n");
        return 2;
    }
    descriptor = minios_open(
        argv[path_index],
        MINIOS_O_WRONLY | MINIOS_O_CREAT | MINIOS_O_TRUNC
    );
    if (descriptor < 3) {
        (void)minios_report_error("write", argv[path_index], descriptor);
        return 1;
    }
    for (index = path_index + 1; index < argc; ++index) {
        if (argv[index] == NULL ||
            (index > path_index + 1 && !minios_print(descriptor, " ")) ||
            !minios_print(descriptor, argv[index])) {
            (void)minios_report_error(
                "write", argv[path_index], -MINIOS_EIO
            );
            (void)minios_close(descriptor);
            return 1;
        }
    }
    if (newline && !minios_print(descriptor, "\n")) {
        (void)minios_report_error("write", argv[path_index], -MINIOS_EIO);
        (void)minios_close(descriptor);
        return 1;
    }
    if (minios_close(descriptor) < 0) {
        (void)minios_report_error("write", argv[path_index], -MINIOS_EIO);
        return 1;
    }
    return 0;
}
