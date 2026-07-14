#include <minios/user.h>

#include <stdbool.h>

static volatile int32_t init_status;

static bool string_equal(const char *left, const char *right)
{
    size_t index = 0U;

    while (left[index] != '\0' && right[index] != '\0') {
        if (left[index] != right[index]) {
            return false;
        }
        ++index;
    }
    return left[index] == right[index];
}

int main(int argc, char **argv);

int main(int argc, char **argv) {
    static const char message[] = "[USER] elf init PASS\n";
    int32_t written;

    if (init_status != 0) {
        return 3;
    }
    if (argc != 2 || argv == NULL || argv[0] == NULL || argv[1] == NULL ||
        argv[2] != NULL || !string_equal(argv[0], "/bin/init") ||
        !string_equal(argv[1], "--self-test")) {
        return 2;
    }
    written = minios_write(1, message, sizeof(message) - 1U);
    init_status = written == (int32_t)(sizeof(message) - 1U) ? 0 : 1;
    return init_status;
}
