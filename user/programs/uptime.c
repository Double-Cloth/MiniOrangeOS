#include <minios/io.h>
#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    uint32_t ticks;

    if (argc != 1 || argv == NULL || argv[0] == NULL) {
        (void)minios_print(2, "usage: uptime\n");
        return 2;
    }
    ticks = minios_getticks();
    return minios_print(1, "uptime: ") &&
        minios_print_uint32(1, ticks / 100U) &&
        minios_print(1, " seconds (") && minios_print_uint32(1, ticks) &&
        minios_print(1, " ticks)\n") ? 0 : 1;
}
