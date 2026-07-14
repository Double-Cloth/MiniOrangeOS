#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    uint8_t buffer[128];
    int32_t descriptor;
    int32_t result;

    if (argc != 2 || argv == NULL || argv[0] == NULL || argv[1] == NULL) {
        return 2;
    }
    descriptor = minios_open(argv[1], MINIOS_O_RDONLY);
    if (descriptor < 3) {
        return 1;
    }
    while ((result = minios_read(descriptor, buffer, sizeof(buffer))) > 0) {
        if (minios_write(1, buffer, (size_t)result) != result) {
            (void)minios_close(descriptor);
            return 1;
        }
    }
    return minios_close(descriptor) == 0 && result == 0 ? 0 : 1;
}
