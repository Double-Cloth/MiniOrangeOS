#include <minios/user.h>
#include <minios/string.h>
#include <minios/abi/errno.h>
#include <minios/abi/minifs.h>

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

static bool test_directory_syscalls(void) {
    static const char pass[] = "[USER] directory syscall PASS\n";
    struct minios_dirent entry;
    struct minios_stat status;
    int32_t directory = -1;
    int32_t file = -1;
    uint32_t entries = 0U;
    bool saw_current = false;
    bool saw_parent = false;
    bool saw_file = false;
    int32_t result;

    if (minios_mkdir("/p6-user-dir") != 0 ||
        minios_mkdir("/p6-user-dir") != -MINIOS_EEXIST ||
        minios_create("/p6-user-dir/file") != 0 ||
        minios_unlink("/p6-user-dir") != -MINIOS_ENOTEMPTY) {
        goto fail;
    }
    file = minios_open("/p6-user-dir/file", MINIOS_O_RDONLY);
    if (file < 3 ||
        minios_unlink("/p6-user-dir/file") != -MINIOS_EBUSY ||
        minios_readdir(file, &entry, sizeof(entry)) != -MINIOS_ENOTDIR ||
        minios_close(file) != 0) {
        goto fail;
    }
    file = -1;
    directory = minios_open("/p6-user-dir", MINIOS_O_RDONLY);
    if (directory < 3 ||
        minios_readdir(directory, &entry, sizeof(entry) - 1U) !=
            -MINIOS_EINVAL) {
        goto fail;
    }
    while ((result = minios_readdir(directory, &entry, sizeof(entry))) == 1) {
        ++entries;
        if (minios_streq(entry.name, ".")) {
            saw_current = entry.mode == MINIFS_MODE_DIRECTORY;
        } else if (minios_streq(entry.name, "..")) {
            saw_parent = entry.mode == MINIFS_MODE_DIRECTORY;
        } else if (minios_streq(entry.name, "file")) {
            saw_file = entry.mode == MINIFS_MODE_REGULAR;
        }
    }
    if (result != 0 || entries != 3U || !saw_current || !saw_parent ||
        !saw_file || minios_close(directory) != 0) {
        goto fail;
    }
    directory = -1;
    if (minios_unlink("/p6-user-dir/file") != 0 ||
        minios_stat("/p6-user-dir/file", &status) != -MINIOS_ENOENT ||
        minios_unlink("/p6-user-dir") != 0 ||
        minios_stat("/p6-user-dir", &status) != -MINIOS_ENOENT ||
        minios_write(1, pass, sizeof(pass) - 1U) !=
            (int32_t)(sizeof(pass) - 1U)) {
        goto fail;
    }
    return true;

fail:
    if (file >= 3) {
        (void)minios_close(file);
    }
    if (directory >= 3) {
        (void)minios_close(directory);
    }
    return false;
}

static bool test_cwd_syscalls(void) {
    static const char pass[] = "[USER] cwd syscall PASS\n";
    struct minios_stat status;
    char path[256];
    int32_t descriptor = -1;

    if (minios_getcwd(path, sizeof(path)) != 0 ||
        !minios_streq(path, "/") ||
        minios_chdir("/bin/") != 0 ||
        minios_getcwd(path, sizeof(path)) != 0 ||
        !minios_streq(path, "/bin") ||
        minios_stat("./sh", &status) != 0 ||
        status.mode != MINIFS_MODE_REGULAR) {
        goto fail;
    }
    descriptor = minios_open("../bin/echo", MINIOS_O_RDONLY);
    if (descriptor < 3 || minios_close(descriptor) != 0) {
        goto fail;
    }
    descriptor = -1;
    if (minios_chdir("init") != -MINIOS_ENOTDIR ||
        minios_chdir("missing") != -MINIOS_ENOENT ||
        minios_chdir("..") != 0 ||
        minios_getcwd(path, sizeof(path)) != 0 ||
        !minios_streq(path, "/") ||
        minios_write(1, pass, sizeof(pass) - 1U) !=
            (int32_t)(sizeof(pass) - 1U)) {
        goto fail;
    }
    return true;

fail:
    if (descriptor >= 3) {
        (void)minios_close(descriptor);
    }
    (void)minios_chdir("/");
    return false;
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
        !minios_streq(argv[1], "--self-test") || !test_file_syscalls() ||
        !test_directory_syscalls() || !test_cwd_syscalls()) {
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
