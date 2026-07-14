#include <minios/string.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SHELL_LINE_SIZE 128U
#define SHELL_ARGUMENT_LIMIT 16U
#define SHELL_PATH_SIZE 64U
#define SHELL_RUN_EXIT 1

static bool write_text(const char *text)
{
    size_t length = minios_strlen(text);

    return minios_write(1, text, length) == (int32_t)length;
}

static bool build_path(char *destination, size_t capacity,
                       const char *command)
{
    static const char prefix[] = "/bin/";
    size_t cursor = 0U;
    size_t index;

    if (command[0] != '/') {
        for (index = 0U; prefix[index] != '\0'; ++index) {
            if (cursor + 1U >= capacity) {
                return false;
            }
            destination[cursor] = prefix[index];
            ++cursor;
        }
    }
    for (index = 0U; command[index] != '\0'; ++index) {
        if (cursor + 1U >= capacity) {
            return false;
        }
        destination[cursor] = command[index];
        ++cursor;
    }
    destination[cursor] = '\0';
    return true;
}

static int run_line(char *line)
{
    char *arguments[SHELL_ARGUMENT_LIMIT + 1U];
    char path[SHELL_PATH_SIZE];
    size_t argument_count = 0U;
    size_t cursor = 0U;
    int32_t child_status = -1;
    int32_t child_pid;

    while (line[cursor] != '\0') {
        while (line[cursor] == ' ' || line[cursor] == '\t') {
            ++cursor;
        }
        if (line[cursor] == '\0') {
            break;
        }
        if (argument_count >= SHELL_ARGUMENT_LIMIT) {
            (void)write_text("sh: too many arguments\n");
            return -1;
        }
        arguments[argument_count] = &line[cursor];
        ++argument_count;
        while (line[cursor] != '\0' && line[cursor] != ' ' &&
               line[cursor] != '\t') {
            ++cursor;
        }
        if (line[cursor] != '\0') {
            line[cursor] = '\0';
            ++cursor;
        }
    }
    if (argument_count == 0U) {
        return 0;
    }
    arguments[argument_count] = NULL;
    if (minios_streq(arguments[0], "exit")) {
        return SHELL_RUN_EXIT;
    }
    if (minios_streq(arguments[0], "help")) {
        return write_text("builtins: help clear cd pwd exit\n") ? 0 : -1;
    }
    if (minios_streq(arguments[0], "clear")) {
        return write_text("\x1B[2J\x1B[H") ? 0 : -1;
    }
    if (minios_streq(arguments[0], "pwd")) {
        return write_text("/\n") ? 0 : -1;
    }
    if (minios_streq(arguments[0], "cd")) {
        if (argument_count == 2U && minios_streq(arguments[1], "/")) {
            return 0;
        }
        (void)write_text("sh: only root directory is available\n");
        return -1;
    }
    if (!build_path(path, sizeof(path), arguments[0])) {
        (void)write_text("sh: command path too long\n");
        return -1;
    }
    arguments[0] = path;
    child_pid = minios_spawn(path, arguments);
    if (child_pid < 1) {
        (void)write_text("sh: command not found\n");
        return -1;
    }
    if (minios_waitpid(child_pid, &child_status) != child_pid ||
        child_status != 0) {
        (void)write_text("sh: command failed\n");
        return -1;
    }
    return 0;
}

static int run_self_test(void)
{
    char help_line[] = "help";
    char command_line[] = "echo [USER] shell command PASS";

    if (run_line(help_line) != 0 || run_line(command_line) != 0 ||
        !write_text("[USER] shell self-test PASS\n")) {
        return 1;
    }
    return 0;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    char line[SHELL_LINE_SIZE];
    size_t length = 0U;

    if (argc == 2 && argv != NULL && argv[0] != NULL && argv[1] != NULL &&
        minios_streq(argv[1], "--self-test")) {
        return run_self_test();
    }
    if (argc != 1 || argv == NULL || argv[0] == NULL) {
        return 2;
    }
    if (!write_text("MiniOrangeOS shell\n$ ")) {
        return 1;
    }
    for (;;) {
        char character;
        int32_t read_result = minios_read(0, &character, 1U);

        if (read_result != 1) {
            return 1;
        }
        if (character == '\b') {
            if (length > 0U) {
                --length;
                (void)write_text("\b \b");
            }
            continue;
        }
        if (character == '\n') {
            int result;

            (void)write_text("\n");
            line[length] = '\0';
            result = run_line(line);
            length = 0U;
            if (result == SHELL_RUN_EXIT) {
                return 0;
            }
            if (!write_text("$ ")) {
                return 1;
            }
            continue;
        }
        if (length + 1U < sizeof(line)) {
            line[length] = character;
            ++length;
            if (minios_write(1, &character, 1U) != 1) {
                return 1;
            }
        }
    }
}
