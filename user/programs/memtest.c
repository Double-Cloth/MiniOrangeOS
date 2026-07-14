#include <minios/user.h>

#include <stdint.h>

static volatile uint32_t private_value;

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    static const char message[] = "[USER] memtest PASS\n";
    uint32_t pid;

    if (argc != 1 || argv == NULL || argv[0] == NULL ||
        private_value != 0U) {
        return 2;
    }
    pid = (uint32_t)minios_getpid();
    private_value = 0x4D454D00U | (pid & 0xFFU);
    if (pid == 0U || private_value != (0x4D454D00U | (pid & 0xFFU))) {
        return 1;
    }
    return minios_write(1, message, sizeof(message) - 1U) ==
        (int32_t)(sizeof(message) - 1U) ? 0 : 1;
}
