#include <minios/io.h>
#include <minios/user.h>

#include <stddef.h>
#include <stdint.h>

static const char *state_name(uint32_t state)
{
    switch (state) {
    case 1U:
        return "NEW";
    case 2U:
        return "READY";
    case 3U:
        return "RUNNING";
    case 4U:
        return "BLOCKED";
    case 5U:
        return "ZOMBIE";
    default:
        return "UNKNOWN";
    }
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    struct minios_process_info processes[MINIOS_PROCESS_LIMIT];
    int32_t count;
    int32_t index;

    if (argc != 1 || argv == NULL || argv[0] == NULL) {
        (void)minios_print(2, "usage: ps\n");
        return 2;
    }
    count = minios_ps(processes, MINIOS_PROCESS_LIMIT);
    if (count < 0) {
        (void)minios_report_error("ps", NULL, count);
        return 1;
    }
    if (!minios_print(1, "PID PPID STATE   NAME\n")) {
        return 1;
    }
    for (index = 0; index < count; ++index) {
        if (!minios_print_uint32(1, processes[index].pid) ||
            !minios_print(1, " ") ||
            !minios_print_uint32(1, processes[index].parent_pid) ||
            !minios_print(1, " ") ||
            !minios_print(1, state_name(processes[index].state)) ||
            !minios_print(1, " ") ||
            !minios_print(1, processes[index].name) ||
            !minios_print(1, "\n")) {
            return 1;
        }
    }
    return 0;
}
