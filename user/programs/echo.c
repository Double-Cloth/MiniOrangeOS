#include <minios/string.h>
#include <minios/user.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    static const char separator[] = " ";
    static const char newline[] = "\n";
    int index;

    if (argc < 1 || argv == NULL || argv[0] == NULL) {
        return 2;
    }
    for (index = 1; index < argc; ++index) {
        size_t length;

        if (argv[index] == NULL) {
            return 2;
        }
        if (index > 1 && minios_write(1, separator, 1U) != 1) {
            return 1;
        }
        length = minios_strlen(argv[index]);
        if (minios_write(1, argv[index], length) != (int32_t)length) {
            return 1;
        }
    }
    return minios_write(1, newline, 1U) == 1 ? 0 : 1;
}
