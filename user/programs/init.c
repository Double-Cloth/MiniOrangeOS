#include <minios/user.h>
#include <minios/string.h>
#include <minios/abi/errno.h>

static volatile int32_t init_status;

int main(int argc, char **argv);

int main(int argc, char **argv) {
    static const char message[] = "[USER] elf init PASS\n";
    static char *const echo_arguments[] = {
        "/bin/echo",
        "[USER]",
        "echo",
        "child",
        "PASS",
        NULL
    };
    static char *const shell_arguments[] = {
        "/bin/sh",
        "--self-test",
        NULL
    };
    static char *const fault_arguments[] = {
        "/bin/fault",
        NULL
    };
    static const char fault_pass[] = "[USER] fault isolation PASS\n";
    int32_t written;
    int32_t child_status = -1;
    int32_t child_pid;

    if (init_status != 0) {
        return 3;
    }
    if (argc != 2 || argv == NULL || argv[0] == NULL || argv[1] == NULL ||
        argv[2] != NULL || !minios_streq(argv[0], "/bin/init") ||
        !minios_streq(argv[1], "--self-test")) {
        return 2;
    }
    child_pid = minios_spawn("/bin/echo", echo_arguments);
    if (child_pid < 1 || minios_waitpid(child_pid, &child_status) != child_pid ||
        child_status != 0) {
        return 4;
    }
    child_status = -1;
    child_pid = minios_spawn("/bin/sh", shell_arguments);
    if (child_pid < 1 || minios_waitpid(child_pid, &child_status) != child_pid ||
        child_status != 0) {
        return 5;
    }
    child_status = 0;
    child_pid = minios_spawn("/bin/fault", fault_arguments);
    if (child_pid < 1 || minios_waitpid(child_pid, &child_status) != child_pid ||
        child_status != -MINIOS_EFAULT ||
        minios_write(1, fault_pass, sizeof(fault_pass) - 1U) !=
            (int32_t)(sizeof(fault_pass) - 1U)) {
        return 6;
    }
    written = minios_write(1, message, sizeof(message) - 1U);
    init_status = written == (int32_t)(sizeof(message) - 1U) ? 0 : 1;
    return init_status;
}
