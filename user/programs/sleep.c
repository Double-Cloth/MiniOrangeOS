#include <minios/abi/errno.h>
#include <minios/io.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

static bool parse_seconds(const char *text, uint32_t *seconds)
{
    uint32_t value = 0U;
    size_t index;

    if (text == NULL || text[0] == '\0' || seconds == NULL) {
        return false;
    }
    for (index = 0U; text[index] != '\0'; ++index) {
        uint32_t digit;

        if (text[index] < '0' || text[index] > '9') {
            return false;
        }
        digit = (uint32_t)(text[index] - '0');
        if (value > (0x7FFFFFFFU / 100U - digit) / 10U) {
            return false;
        }
        value = value * 10U + digit;
    }
    *seconds = value;
    return true;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    uint32_t seconds;
    int32_t result;

    if (argc != 2 || argv == NULL || argv[0] == NULL ||
        argv[1] == NULL || !parse_seconds(argv[1], &seconds)) {
        (void)minios_print(2, "usage: sleep seconds\n");
        return 2;
    }
    result = minios_sleep(seconds * 100U);
    if (result < 0) {
        (void)minios_report_error("sleep", NULL, result);
        return 1;
    }
    return 0;
}
