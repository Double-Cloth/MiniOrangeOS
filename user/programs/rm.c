#include <minios/user.h>

#include <stddef.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    if (argc != 2 || argv == NULL || argv[0] == NULL || argv[1] == NULL) {
        return 2;
    }
    return minios_unlink(argv[1]) == 0 ? 0 : 1;
}
