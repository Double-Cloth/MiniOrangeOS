#include <minios/string.h>
#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

static int write_text(const char *text)
{
    size_t length = minios_strlen(text);

    return minios_write(1, text, length) == (int32_t)length ? 0 : -1;
}

static int write_number(uint32_t value)
{
    char digits[10];
    size_t count = 0U;
    size_t index;

    do {
        digits[count] = (char)('0' + value % 10U);
        value /= 10U;
        ++count;
    } while (value != 0U);
    for (index = 0U; index < count / 2U; ++index) {
        char temporary = digits[index];
        digits[index] = digits[count - index - 1U];
        digits[count - index - 1U] = temporary;
    }
    return minios_write(1, digits, count) == (int32_t)count ? 0 : -1;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    struct minios_process_info processes[MINIOS_PROCESS_LIMIT];
    int32_t count;
    int32_t index;

    if (argc != 1 || argv == NULL || argv[0] == NULL) {
        return 2;
    }
    count = minios_ps(processes, MINIOS_PROCESS_LIMIT);
    if (count < 1 || write_text("PID PPID STATE NAME\n") != 0) {
        return 1;
    }
    for (index = 0; index < count; ++index) {
        if (write_number(processes[index].pid) != 0 ||
            write_text(" ") != 0 ||
            write_number(processes[index].parent_pid) != 0 ||
            write_text(" ") != 0 ||
            write_number(processes[index].state) != 0 ||
            write_text(" ") != 0 ||
            write_text(processes[index].name) != 0 ||
            write_text("\n") != 0) {
            return 1;
        }
    }
    return write_text("[USER] ps PASS\n") == 0 ? 0 : 1;
}
