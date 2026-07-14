#include <minios/user.h>
#include <minios/string.h>
#include <minios/abi/errno.h>

#include <stdbool.h>

static volatile int32_t init_status;

static bool test_file_syscalls(void) {
    static const char pass[] = "[USER] file syscall PASS\n";
    struct minios_stat status;
    uint8_t magic[4];
    int32_t descriptor;

    if (minios_stat("/bin/init", &status) != 0 || status.size < sizeof(magic) ||
        minios_open("/bin/missing", MINIOS_O_RDONLY) != -MINIOS_ENOENT ||
        minios_open("/bin/init", 0x80000000U) != -MINIOS_EINVAL) {
        return false;
    }
    descriptor = minios_open("/bin/init", MINIOS_O_RDONLY);
    if (descriptor < 3 ||
        minios_read(descriptor, magic, sizeof(magic)) !=
            (int32_t)sizeof(magic) ||
        magic[0] != 0x7FU || magic[1] != 'E' || magic[2] != 'L' ||
        magic[3] != 'F' ||
        minios_lseek(descriptor, 0, MINIOS_SEEK_SET) != 0 ||
        minios_read(descriptor, magic, 1U) != 1 || magic[0] != 0x7FU ||
        minios_close(descriptor) != 0 ||
        minios_close(descriptor) != -MINIOS_EBADF) {
        if (descriptor >= 3) {
            (void)minios_close(descriptor);
        }
        return false;
    }
    /* 故意保留一个 fd，由进程退出路径验证自动关闭。 */
    descriptor = minios_open("/bin/sh", MINIOS_O_RDONLY);
    if (descriptor < 3) {
        return false;
    }
    return minios_write(1, pass, sizeof(pass) - 1U) ==
        (int32_t)(sizeof(pass) - 1U);
}

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
        !minios_streq(argv[1], "--self-test") || !test_file_syscalls()) {
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
