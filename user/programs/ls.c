#include <minios/abi/minifs.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    const char *path = "/";
    struct minios_dirent entry;
    int32_t descriptor;
    int32_t result;

    if (argc == 2 && argv != NULL && argv[1] != NULL) {
        path = argv[1];
    } else if (argc != 1 || argv == NULL || argv[0] == NULL) {
        return 2;
    }
    descriptor = minios_open(path, MINIOS_O_RDONLY);
    if (descriptor < 3) {
        return 1;
    }
    while ((result = minios_readdir(descriptor, &entry, sizeof(entry))) == 1) {
        if (minios_streq(entry.name, ".") || minios_streq(entry.name, "..")) {
            continue;
        }
        if (minios_write(1, entry.name, entry.name_length) !=
            (int32_t)entry.name_length ||
            (entry.mode == MINIFS_MODE_DIRECTORY &&
             minios_write(1, "/", 1U) != 1) ||
            minios_write(1, "\n", 1U) != 1) {
            (void)minios_close(descriptor);
            return 1;
        }
    }
    return minios_close(descriptor) == 0 && result == 0 ? 0 : 1;
}
