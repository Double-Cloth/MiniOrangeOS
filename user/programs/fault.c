#include <minios/user.h>

#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    static const char message[] = "[USER] fault trigger\n";
    volatile uint32_t *invalid =
        (volatile uint32_t *)(uintptr_t)0x0BADF000U;

    if (argc != 1 || argv == NULL || argv[0] == NULL ||
        minios_write(1, message, sizeof(message) - 1U) !=
            (int32_t)(sizeof(message) - 1U)) {
        return 2;
    }
    *invalid = 0xFA17FA17U;
    return 1;
}
