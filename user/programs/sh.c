#include <minios/abi/errno.h>
#include <minios/abi/input.h>
#include <minios/abi/minifs.h>
#include <minios/io.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SHELL_LINE_SIZE 256U
#define SHELL_ARGUMENT_LIMIT 16U
#define SHELL_PATH_SIZE 256U
#define SHELL_HISTORY_LIMIT 8U
#define SHELL_COMMAND_NAME_SIZE (MINIFS_NAME_MAX + 1U)
#define SHELL_RUN_EXIT 1

struct shell_completion {
    size_t match_count;
    size_t common_length;
    char common[SHELL_COMMAND_NAME_SIZE];
};

static const char *const shell_builtin_commands[] = {
    "help", "clear", "cd", "pwd", "exit", "shutdown"
};

static int shell_exit_status;
static char shell_history[SHELL_HISTORY_LIMIT][SHELL_LINE_SIZE];
static size_t shell_history_count;

static bool write_text(const char *text)
{
    return minios_print(1, text);
}

static bool is_separator(char character)
{
    return character == ' ' || character == '\t';
}

static bool string_has_prefix(const char *value, const char *prefix,
                              size_t prefix_length)
{
    size_t index;

    for (index = 0U; index < prefix_length; ++index) {
        if (value[index] == '\0' || value[index] != prefix[index]) {
            return false;
        }
    }
    return true;
}

static bool command_is_builtin(const char *command)
{
    size_t index;

    for (index = 0U;
         index < sizeof(shell_builtin_commands) /
                     sizeof(shell_builtin_commands[0]);
         ++index) {
        if (minios_streq(command, shell_builtin_commands[index])) {
            return true;
        }
    }
    return false;
}

static void completion_add(struct shell_completion *completion,
                           const char *command, const char *prefix,
                           size_t prefix_length)
{
    size_t command_length;
    size_t index;

    if (!string_has_prefix(command, prefix, prefix_length)) {
        return;
    }
    command_length = minios_strlen(command);
    if (command_length > MINIFS_NAME_MAX) {
        return;
    }
    if (completion->match_count == 0U) {
        for (index = 0U; index < command_length; ++index) {
            completion->common[index] = command[index];
        }
        completion->common[command_length] = '\0';
        completion->common_length = command_length;
    } else {
        size_t common_limit = completion->common_length < command_length ?
            completion->common_length : command_length;

        for (index = 0U; index < common_limit; ++index) {
            if (completion->common[index] != command[index]) {
                break;
            }
        }
        completion->common_length = index;
        completion->common[index] = '\0';
    }
    ++completion->match_count;
}

static bool collect_command_matches(const char *prefix, size_t prefix_length,
                                    struct shell_completion *completion)
{
    struct minios_dirent entry;
    int32_t descriptor;
    int32_t result;
    int32_t close_result;
    size_t index;

    completion->match_count = 0U;
    completion->common_length = 0U;
    completion->common[0] = '\0';
    for (index = 0U;
         index < sizeof(shell_builtin_commands) /
                     sizeof(shell_builtin_commands[0]);
         ++index) {
        completion_add(completion, shell_builtin_commands[index], prefix,
                       prefix_length);
    }
    descriptor = minios_open("/bin", MINIOS_O_RDONLY);
    if (descriptor < 3) {
        return false;
    }
    while ((result = minios_readdir(descriptor, &entry, sizeof(entry))) == 1) {
        if (entry.mode == MINIFS_MODE_REGULAR &&
            !command_is_builtin(entry.name)) {
            completion_add(completion, entry.name, prefix, prefix_length);
        }
    }
    close_result = minios_close(descriptor);
    return result == 0 && close_result == 0;
}

static int parse_line(char *line, char **arguments, size_t *argument_count)
{
    size_t read_cursor = 0U;
    size_t write_cursor = 0U;
    size_t count = 0U;

    while (line[read_cursor] != '\0') {
        char quote = '\0';

        while (is_separator(line[read_cursor])) {
            ++read_cursor;
        }
        if (line[read_cursor] == '\0') {
            break;
        }
        if (count >= SHELL_ARGUMENT_LIMIT) {
            (void)minios_print(2, "sh: too many arguments\n");
            return -1;
        }
        arguments[count] = &line[write_cursor];
        ++count;
        while (line[read_cursor] != '\0') {
            char character = line[read_cursor];

            if (quote != '\0') {
                if (character == quote) {
                    quote = '\0';
                    ++read_cursor;
                    continue;
                }
                if (quote == '"' && character == '\\') {
                    ++read_cursor;
                    if (line[read_cursor] == '\0') {
                        (void)minios_print(
                            2, "sh: trailing escape character\n"
                        );
                        return -1;
                    }
                    character = line[read_cursor];
                }
                line[write_cursor] = character;
                ++write_cursor;
                ++read_cursor;
                continue;
            }
            if (is_separator(character)) {
                break;
            }
            if (character == '\'' || character == '"') {
                quote = character;
                ++read_cursor;
                continue;
            }
            if (character == '\\') {
                ++read_cursor;
                if (line[read_cursor] == '\0') {
                    (void)minios_print(
                        2, "sh: trailing escape character\n"
                    );
                    return -1;
                }
                character = line[read_cursor];
            }
            line[write_cursor] = character;
            ++write_cursor;
            ++read_cursor;
        }
        if (quote != '\0') {
            (void)minios_print(2, "sh: unterminated quote\n");
            return -1;
        }
        while (is_separator(line[read_cursor])) {
            ++read_cursor;
        }
        line[write_cursor] = '\0';
        ++write_cursor;
    }
    arguments[count] = NULL;
    *argument_count = count;
    return 0;
}

static bool command_has_slash(const char *command)
{
    size_t index;

    for (index = 0U; command[index] != '\0'; ++index) {
        if (command[index] == '/') {
            return true;
        }
    }
    return false;
}

static bool build_path(char *destination, size_t capacity,
                       const char *command)
{
    static const char prefix[] = "/bin/";
    size_t cursor = 0U;
    size_t index;

    if (!command_has_slash(command)) {
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

static bool parse_exit_status(const char *text, int *status)
{
    uint32_t value = 0U;
    size_t index;

    if (text == NULL || text[0] == '\0' || status == NULL) {
        return false;
    }
    for (index = 0U; text[index] != '\0'; ++index) {
        if (text[index] < '0' || text[index] > '9') {
            return false;
        }
        value = value * 10U + (uint32_t)(text[index] - '0');
        if (value > 255U) {
            return false;
        }
    }
    *status = (int)value;
    return true;
}

static int run_builtin(char **arguments, size_t argument_count)
{
    if (minios_streq(arguments[0], "exit")) {
        if (argument_count > 2U ||
            (argument_count == 2U &&
             !parse_exit_status(arguments[1], &shell_exit_status))) {
            (void)minios_print(2, "usage: exit [status]\n");
            return -1;
        }
        return SHELL_RUN_EXIT;
    }
    if (minios_streq(arguments[0], "help")) {
        if (argument_count != 1U) {
            (void)minios_print(2, "usage: help\n");
            return -1;
        }
        return write_text(
            "builtins: help clear cd pwd exit shutdown\n"
            "commands: ls cat touch write edit mkdir rm cp stat echo ps sleep uptime\n"
            "diagnostics: memtest fault\n"
            "completion: Tab completes builtins and /bin commands\n"
            "quoting:  'single quoted' \"double quoted\" backslash\\escape\n"
        ) ? 0 : -1;
    }
    if (minios_streq(arguments[0], "shutdown")) {
        if (argument_count != 1U) {
            (void)minios_print(2, "usage: shutdown\n");
            return -1;
        }
        if (!write_text("Shutting down MiniOrangeOS...\n")) {
            return -1;
        }
        minios_shutdown();
    }
    if (minios_streq(arguments[0], "clear")) {
        if (argument_count != 1U) {
            (void)minios_print(2, "usage: clear\n");
            return -1;
        }
        return write_text("\x1B[2J\x1B[H") ? 0 : -1;
    }
    if (minios_streq(arguments[0], "pwd")) {
        char path[SHELL_PATH_SIZE];

        if (argument_count != 1U) {
            (void)minios_print(2, "usage: pwd\n");
            return -1;
        }
        if (minios_getcwd(path, sizeof(path)) != 0) {
            (void)minios_report_error("pwd", NULL, -MINIOS_EIO);
            return -1;
        }
        return minios_print(1, path) && minios_print(1, "\n") ? 0 : -1;
    }
    if (minios_streq(arguments[0], "cd")) {
        const char *path;
        int32_t result;

        if (argument_count > 2U) {
            (void)minios_print(2, "usage: cd [directory]\n");
            return -1;
        }
        path = argument_count == 1U ? "/" : arguments[1];
        result = minios_chdir(path);
        if (result < 0) {
            (void)minios_report_error("cd", path, result);
            return -1;
        }
        return 0;
    }
    return -2;
}

static int run_line(char *line)
{
    char *arguments[SHELL_ARGUMENT_LIMIT + 1U];
    char path[SHELL_PATH_SIZE];
    size_t argument_count = 0U;
    int32_t child_status = -1;
    int32_t child_pid;
    int builtin_result;

    if (parse_line(line, arguments, &argument_count) != 0) {
        return -1;
    }
    if (argument_count == 0U) {
        return 0;
    }
    builtin_result = run_builtin(arguments, argument_count);
    if (builtin_result != -2) {
        return builtin_result;
    }
    if (!build_path(path, sizeof(path), arguments[0])) {
        (void)minios_print(2, "sh: command path too long\n");
        return -1;
    }
    arguments[0] = path;
    child_pid = minios_spawn(path, arguments);
    if (child_pid < 1) {
        (void)minios_report_error("sh", path, child_pid);
        return -1;
    }
    if (minios_waitpid(child_pid, &child_status) != child_pid) {
        (void)minios_print(2, "sh: wait failed\n");
        return -1;
    }
    if (child_status != 0) {
        (void)minios_print(2, "sh: ");
        (void)minios_print(2, path);
        (void)minios_print(2, ": exited with status ");
        (void)minios_print_int32(2, child_status);
        (void)minios_print(2, "\n");
        return -1;
    }
    return 0;
}

static bool print_prompt(void)
{
    char path[SHELL_PATH_SIZE];

    return minios_getcwd(path, sizeof(path)) == 0 &&
        minios_print(1, path) && minios_print(1, "$ ");
}

static bool run_file_command_self_test(void)
{
    static const char persistence_payload[] =
        "[USER] command persistence payload\n";
    struct minios_stat status;
    char persistence_write[] =
        "write /p6-command-persist [USER] command persistence payload";
    char persistence_cat[] = "cat /p6-command-persist";
    char mkdir_line[] = "mkdir /p6-command-dir";
    char touch_line[] = "touch /p6-command-dir/file";
    char write_line[] = "write /p6-command-dir/file file command data";
    char append_line[] = "write -a /p6-command-dir/file appended data";
    char cat_line[] = "cat -n /p6-command-dir/file";
    char edit_line[] = "edit --self-test";
    char cp_line[] = "cp /p6-command-dir/file /p6-command-dir/copy";
    char stat_line[] = "stat /p6-command-dir/copy";
    char ls_line[] = "ls /p6-command-dir";
    char rm_file_line[] = "rm /p6-command-dir/file";
    char rm_copy_line[] = "rm /p6-command-dir/copy";
    char rm_directory_line[] = "rm /p6-command-dir";
    int32_t result = minios_stat("/p6-command-persist", &status);

    if (result == -MINIOS_ENOENT ||
        (result == 0 && status.mode == MINIFS_MODE_REGULAR &&
         status.size != sizeof(persistence_payload) - 1U)) {
        if (run_line(persistence_write) != 0 ||
            !write_text("[USER] command persistence created PASS\n")) {
            return false;
        }
    } else if (result == 0 && status.mode == MINIFS_MODE_REGULAR &&
               status.size == sizeof(persistence_payload) - 1U) {
        if (run_line(persistence_cat) != 0 ||
            !write_text("[USER] command persistence verified PASS\n")) {
            return false;
        }
    } else {
        return false;
    }
    return run_line(mkdir_line) == 0 && run_line(touch_line) == 0 &&
        run_line(write_line) == 0 && run_line(append_line) == 0 &&
        run_line(cat_line) == 0 && run_line(edit_line) == 0 &&
        run_line(cp_line) == 0 && run_line(stat_line) == 0 &&
        run_line(ls_line) == 0 && run_line(rm_file_line) == 0 &&
        run_line(rm_copy_line) == 0 &&
        run_line(rm_directory_line) == 0 &&
        write_text("[USER] file commands PASS\n");
}

static bool run_completion_self_test(void)
{
    struct shell_completion completion;

    if (!collect_command_matches("ec", 2U, &completion) ||
        completion.match_count != 1U ||
        !minios_streq(completion.common, "echo") ||
        !collect_command_matches("hel", 3U, &completion) ||
        completion.match_count != 1U ||
        !minios_streq(completion.common, "help") ||
        !collect_command_matches("c", 1U, &completion) ||
        completion.match_count < 2U || completion.common_length != 1U ||
        completion.common[0] != 'c') {
        return false;
    }
    return write_text("[USER] shell completion PASS\n");
}

static int run_self_test(void)
{
    char help_line[] = "help";
    char command_line[] = "echo [USER] shell command PASS";
    char quoted_line[] = "echo \"[USER] quoted shell command PASS\"";
    char cd_line[] = "cd /bin";
    char relative_line[] = "./echo [USER] relative command PASS";
    char root_line[] = "cd /";
    char ps_line[] = "ps";
    char sleep_line[] = "sleep 0";
    char uptime_line[] = "uptime";
    char memtest_line[] = "memtest";

    if (run_line(help_line) != 0 || run_line(command_line) != 0 ||
        run_line(quoted_line) != 0 || run_line(cd_line) != 0 ||
        run_line(relative_line) != 0 || run_line(root_line) != 0 ||
        run_line(ps_line) != 0 ||
        !write_text("[USER] ps PASS\n") || run_line(sleep_line) != 0 ||
        run_line(uptime_line) != 0 ||
        !write_text("[USER] time commands PASS\n") ||
        run_line(memtest_line) != 0 ||
        !run_completion_self_test() ||
        !run_file_command_self_test() ||
        !write_text("[USER] shell self-test PASS\n")) {
        return 1;
    }
    return 0;
}

static bool write_buffer(const char *buffer, size_t length)
{
    return length == 0U || minios_write(1, buffer, length) == (int32_t)length;
}

static bool write_backspaces(size_t count)
{
    size_t index;

    for (index = 0U; index < count; ++index) {
        if (!write_text("\b")) {
            return false;
        }
    }
    return true;
}

static bool redraw_line(const char *line, size_t length, size_t cursor,
                        size_t old_length, size_t old_cursor)
{
    size_t rendered_length = length > old_length ? length : old_length;
    size_t index;

    if (!write_backspaces(old_cursor) || !write_buffer(line, length)) {
        return false;
    }
    for (index = length; index < old_length; ++index) {
        if (!write_text(" ")) {
            return false;
        }
    }
    return write_backspaces(rendered_length - cursor);
}

static bool print_command_matches(const char *prefix, size_t prefix_length,
                                  const char *line, size_t length,
                                  size_t cursor)
{
    struct minios_dirent entry;
    int32_t descriptor;
    int32_t result;
    int32_t close_result;
    size_t index;
    bool success = write_text("\n");

    for (index = 0U;
         success && index < sizeof(shell_builtin_commands) /
                                sizeof(shell_builtin_commands[0]);
         ++index) {
        if (string_has_prefix(shell_builtin_commands[index], prefix,
                              prefix_length)) {
            success = write_text(shell_builtin_commands[index]) &&
                write_text("\n");
        }
    }
    descriptor = minios_open("/bin", MINIOS_O_RDONLY);
    if (descriptor < 3) {
        return false;
    }
    while (success &&
           (result = minios_readdir(descriptor, &entry, sizeof(entry))) == 1) {
        if (entry.mode == MINIFS_MODE_REGULAR &&
            !command_is_builtin(entry.name) &&
            string_has_prefix(entry.name, prefix, prefix_length)) {
            success = write_text(entry.name) && write_text("\n");
        }
    }
    close_result = minios_close(descriptor);
    if (!success || result != 0 || close_result != 0) {
        return false;
    }
    return print_prompt() && write_buffer(line, length) &&
        write_backspaces(length - cursor);
}

static bool insert_completion(char *line, size_t capacity, size_t *length,
                              size_t *cursor, const char *completion,
                              size_t completion_length,
                              size_t prefix_length, bool append_separator)
{
    size_t old_length = *length;
    size_t old_cursor = *cursor;
    size_t suffix_length;
    size_t separator_length;
    size_t added_length;
    size_t index;

    if (completion_length < prefix_length) {
        return true;
    }
    suffix_length = completion_length - prefix_length;
    separator_length = append_separator &&
        (*cursor == *length || !is_separator(line[*cursor])) ? 1U : 0U;
    added_length = suffix_length + separator_length;
    if (added_length == 0U || *length + added_length + 1U > capacity) {
        return true;
    }
    for (index = *length; index > *cursor; --index) {
        line[index + added_length - 1U] = line[index - 1U];
    }
    for (index = 0U; index < suffix_length; ++index) {
        line[*cursor + index] = completion[prefix_length + index];
    }
    if (separator_length != 0U) {
        line[*cursor + suffix_length] = ' ';
    }
    *cursor += added_length;
    *length += added_length;
    line[*length] = '\0';
    if (old_cursor == old_length) {
        return write_buffer(&line[old_cursor], added_length);
    }
    return redraw_line(line, *length, *cursor, old_length, old_cursor);
}

static bool complete_command(char *line, size_t capacity, size_t *length,
                             size_t *cursor)
{
    struct shell_completion completion;
    size_t command_start = 0U;
    size_t prefix_length;
    size_t index;

    while (command_start < *cursor && is_separator(line[command_start])) {
        ++command_start;
    }
    if (command_start == *cursor) {
        return true;
    }
    for (index = command_start; index < *cursor; ++index) {
        if (is_separator(line[index])) {
            return true;
        }
    }
    if (*cursor < *length && !is_separator(line[*cursor])) {
        return true;
    }
    prefix_length = *cursor - command_start;
    if (prefix_length > MINIFS_NAME_MAX ||
        !collect_command_matches(&line[command_start], prefix_length,
                                 &completion) ||
        completion.match_count == 0U) {
        return true;
    }
    if (completion.match_count == 1U) {
        return insert_completion(
            line, capacity, length, cursor, completion.common,
            completion.common_length, prefix_length, true
        );
    }
    if (completion.common_length > prefix_length) {
        return insert_completion(
            line, capacity, length, cursor, completion.common,
            completion.common_length, prefix_length, false
        );
    }
    return print_command_matches(&line[command_start], prefix_length, line,
                                 *length, *cursor);
}

static void copy_line(char *destination, const char *source, size_t length)
{
    size_t index;

    for (index = 0U; index < length; ++index) {
        destination[index] = source[index];
    }
    destination[length] = '\0';
}

static bool line_has_content(const char *line, size_t length)
{
    size_t index;

    for (index = 0U; index < length; ++index) {
        if (!is_separator(line[index])) {
            return true;
        }
    }
    return false;
}

static void history_add(const char *line, size_t length)
{
    size_t index;

    if (!line_has_content(line, length) ||
        (shell_history_count > 0U &&
         minios_streq(shell_history[shell_history_count - 1U], line))) {
        return;
    }
    if (shell_history_count == SHELL_HISTORY_LIMIT) {
        for (index = 1U; index < SHELL_HISTORY_LIMIT; ++index) {
            copy_line(shell_history[index - 1U], shell_history[index],
                      minios_strlen(shell_history[index]));
        }
        --shell_history_count;
    }
    copy_line(shell_history[shell_history_count], line, length);
    ++shell_history_count;
}

static bool recall_line(char *line, size_t *length, size_t *cursor,
                        const char *replacement)
{
    size_t old_length = *length;
    size_t old_cursor = *cursor;
    size_t replacement_length = minios_strlen(replacement);

    copy_line(line, replacement, replacement_length);
    *length = replacement_length;
    *cursor = replacement_length;
    return redraw_line(line, *length, *cursor, old_length, old_cursor);
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    char line[SHELL_LINE_SIZE];
    char draft[SHELL_LINE_SIZE];
    size_t length = 0U;
    size_t cursor = 0U;
    size_t draft_length = 0U;
    size_t history_position = 0U;

    if (argc == 2 && argv != NULL && argv[0] != NULL && argv[1] != NULL &&
        minios_streq(argv[1], "--self-test")) {
        return run_self_test();
    }
    if (argc != 1 || argv == NULL || argv[0] == NULL) {
        return 2;
    }
    shell_exit_status = 0;
    shell_history_count = 0U;
    draft[0] = '\0';
    if (!write_text("MiniOrangeOS shell\n") || !print_prompt()) {
        return 1;
    }
    history_position = shell_history_count;
    for (;;) {
        uint8_t character;
        int32_t read_result = minios_read(0, &character, 1U);

        if (read_result != 1) {
            return 1;
        }
        if (character == MINIOS_KEY_LEFT) {
            if (cursor > 0U && !write_text("\b")) {
                return 1;
            }
            cursor -= cursor > 0U ? 1U : 0U;
            continue;
        }
        if (character == MINIOS_KEY_RIGHT) {
            if (cursor < length) {
                if (!write_buffer(&line[cursor], 1U)) {
                    return 1;
                }
                ++cursor;
            }
            continue;
        }
        if (character == MINIOS_KEY_HOME || character == 1U) {
            if (!write_backspaces(cursor)) {
                return 1;
            }
            cursor = 0U;
            continue;
        }
        if (character == MINIOS_KEY_END || character == 5U) {
            if (!write_buffer(&line[cursor], length - cursor)) {
                return 1;
            }
            cursor = length;
            continue;
        }
        if (character == MINIOS_KEY_UP || character == MINIOS_KEY_DOWN) {
            const char *replacement;

            if (character == MINIOS_KEY_UP) {
                if (history_position == 0U) {
                    continue;
                }
                if (history_position == shell_history_count) {
                    copy_line(draft, line, length);
                    draft_length = length;
                }
                --history_position;
                replacement = shell_history[history_position];
            } else {
                if (history_position >= shell_history_count) {
                    continue;
                }
                ++history_position;
                if (history_position == shell_history_count) {
                    draft[draft_length] = '\0';
                    replacement = draft;
                } else {
                    replacement = shell_history[history_position];
                }
            }
            if (!recall_line(line, &length, &cursor, replacement)) {
                return 1;
            }
            continue;
        }
        if (character == '\b' || character == MINIOS_KEY_DELETE ||
            character == 4U) {
            size_t old_length = length;
            size_t old_cursor = cursor;
            size_t index;

            if (character == '\b') {
                if (cursor == 0U) {
                    continue;
                }
                for (index = cursor; index < length; ++index) {
                    line[index - 1U] = line[index];
                }
                --cursor;
                --length;
            } else {
                if (cursor == length) {
                    if (character == 4U && length == 0U) {
                        (void)write_text("\n");
                        return shell_exit_status;
                    }
                    continue;
                }
                for (index = cursor + 1U; index < length; ++index) {
                    line[index - 1U] = line[index];
                }
                --length;
            }
            if (!redraw_line(line, length, cursor, old_length, old_cursor)) {
                return 1;
            }
            continue;
        }
        if (character == 3U) {
            length = 0U;
            cursor = 0U;
            draft_length = 0U;
            history_position = shell_history_count;
            if (!write_text("^C\n") || !print_prompt()) {
                return 1;
            }
            continue;
        }
        if (character == 11U || character == 21U) {
            size_t old_length = length;
            size_t old_cursor = cursor;
            size_t index;

            if (character == 11U) {
                length = cursor;
            } else {
                for (index = cursor; index < length; ++index) {
                    line[index - cursor] = line[index];
                }
                length -= cursor;
                cursor = 0U;
            }
            if (!redraw_line(line, length, cursor, old_length, old_cursor)) {
                return 1;
            }
            continue;
        }
        if (character == 12U) {
            if (!write_text("\x1B[2J\x1B[H") || !print_prompt() ||
                !write_buffer(line, length) ||
                !write_backspaces(length - cursor)) {
                return 1;
            }
            continue;
        }
        if (character == '\n') {
            int result = 0;

            (void)write_text("\n");
            line[length] = '\0';
            history_add(line, length);
            result = run_line(line);
            length = 0U;
            cursor = 0U;
            draft_length = 0U;
            history_position = shell_history_count;
            if (result == SHELL_RUN_EXIT) {
                return shell_exit_status;
            }
            if (!print_prompt()) {
                return 1;
            }
            continue;
        }
        if (character == '\t') {
            if (!complete_command(line, sizeof(line), &length, &cursor)) {
                return 1;
            }
            continue;
        }
        if (character < 0x20U || character > 0x7EU) {
            continue;
        }
        if (length + 1U >= sizeof(line)) {
            continue;
        }
        {
            size_t old_length = length;
            size_t old_cursor = cursor;
            size_t index;
            bool append_at_end = cursor == length;

            for (index = length; index > cursor; --index) {
                line[index] = line[index - 1U];
            }
            line[cursor] = (char)character;
            ++cursor;
            ++length;
            if ((append_at_end && !write_buffer(&line[cursor - 1U], 1U)) ||
                (!append_at_end &&
                 !redraw_line(line, length, cursor, old_length, old_cursor))) {
                return 1;
            }
        }
    }
}
