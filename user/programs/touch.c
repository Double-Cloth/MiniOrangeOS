#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    int32_t descriptor;

    if (argc != 2 || argv == NULL || argv[0] == NULL || argv[1] == NULL) {
        return 2;
    }
    descriptor = minios_open(argv[1], MINIOS_O_WRONLY | MINIOS_O_CREAT);
    return descriptor >= 3 && minios_close(descriptor) == 0 ? 0 : 1;
}
