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
    bool append = false;
    bool newline = true;
    int path_index = 1;
    int32_t descriptor;
    int index;

    if (argv == NULL || argv[0] == NULL) {
        return 2;
    }
    while (path_index < argc && argv[path_index] != NULL &&
           argv[path_index][0] == '-' && argv[path_index][1] != '\0') {
        size_t option_index;

        if (minios_streq(argv[path_index], "--")) {
            ++path_index;
            break;
        }
        for (option_index = 1U;
             argv[path_index][option_index] != '\0'; ++option_index) {
            if (argv[path_index][option_index] == 'a') {
                append = true;
            } else if (argv[path_index][option_index] == 'n') {
                newline = false;
            } else {
                (void)minios_print(
                    2, "usage: write [-a] [-n] [--] file [text...]\n"
                );
                return 2;
            }
        }
        ++path_index;
    }
    if (argc <= path_index || argv[path_index] == NULL) {
        (void)minios_print(
            2, "usage: write [-a] [-n] [--] file [text...]\n"
        );
        return 2;
    }
    descriptor = minios_open(
        argv[path_index],
        MINIOS_O_WRONLY | MINIOS_O_CREAT |
            (append ? 0U : MINIOS_O_TRUNC)
    );
    if (descriptor < 3) {
        (void)minios_report_error("write", argv[path_index], descriptor);
        return 1;
    }
    if (append && minios_lseek(descriptor, 0, MINIOS_SEEK_END) < 0) {
        (void)minios_report_error("write", argv[path_index], -MINIOS_EIO);
        (void)minios_close(descriptor);
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
