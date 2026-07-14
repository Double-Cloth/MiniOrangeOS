#include <minios/io.h>
#include <minios/string.h>

#include <stdbool.h>
#include <stddef.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    bool newline = true;
    int index = 1;

    if (argc < 1 || argv == NULL || argv[0] == NULL) {
        return 2;
    }
    if (index < argc && argv[index] != NULL &&
        minios_streq(argv[index], "-n")) {
        newline = false;
        ++index;
    }
    for (; index < argc; ++index) {
        if (argv[index] == NULL ||
            (index > (newline ? 1 : 2) && !minios_print(1, " ")) ||
            !minios_print(1, argv[index])) {
            return 1;
        }
    }
    return !newline || minios_print(1, "\n") ? 0 : 1;
}
