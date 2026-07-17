#include <minios/abi/errno.h>
#include <minios/abi/input.h>
#include <minios/abi/minifs.h>
#include <minios/io.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define EDIT_BUFFER_CAPACITY 32768U
#define EDIT_COMMAND_CAPACITY 256U
#define EDIT_IO_CHUNK 4096U

enum editor_action {
    EDITOR_CONTINUE,
    EDITOR_EXIT,
    EDITOR_FATAL,
};

static uint8_t edit_buffer[EDIT_BUFFER_CAPACITY];
static size_t edit_length;

static bool text_byte_supported(uint8_t value)
{
    return value == (uint8_t)'\n' || value == (uint8_t)'\t' ||
        (value >= 0x20U && value <= 0x7EU);
}

static bool buffer_set_text(const char *text)
{
    size_t length = minios_strlen(text);
    size_t index;

    if (length > sizeof(edit_buffer)) {
        return false;
    }
    for (index = 0U; index < length; ++index) {
        edit_buffer[index] = (uint8_t)text[index];
    }
    edit_length = length;
    return true;
}

static bool buffer_matches(const char *text)
{
    size_t length = minios_strlen(text);
    size_t index;

    if (edit_length != length) {
        return false;
    }
    for (index = 0U; index < length; ++index) {
        if (edit_buffer[index] != (uint8_t)text[index]) {
            return false;
        }
    }
    return true;
}

static size_t line_count(void)
{
    size_t count = 0U;
    size_t index;

    if (edit_length == 0U) {
        return 0U;
    }
    for (index = 0U; index < edit_length; ++index) {
        if (edit_buffer[index] == (uint8_t)'\n') {
            ++count;
        }
    }
    if (edit_buffer[edit_length - 1U] != (uint8_t)'\n') {
        ++count;
    }
    return count;
}

static bool line_bounds(size_t number, size_t *start, size_t *content_end,
                        size_t *full_end)
{
    size_t current = 1U;
    size_t position = 0U;

    if (number == 0U || edit_length == 0U) {
        return false;
    }
    while (current < number) {
        while (position < edit_length &&
               edit_buffer[position] != (uint8_t)'\n') {
            ++position;
        }
        if (position == edit_length) {
            return false;
        }
        ++position;
        ++current;
    }
    if (position >= edit_length) {
        return false;
    }
    *start = position;
    while (position < edit_length &&
           edit_buffer[position] != (uint8_t)'\n') {
        ++position;
    }
    *content_end = position;
    *full_end = position < edit_length ? position + 1U : position;
    return true;
}

static bool replace_range(size_t start, size_t end, const char *replacement,
                          size_t replacement_length)
{
    size_t removed;
    size_t tail;
    size_t new_length;
    size_t index;

    if (start > end || end > edit_length ||
        (replacement == NULL && replacement_length != 0U)) {
        return false;
    }
    removed = end - start;
    if (replacement_length > sizeof(edit_buffer) - (edit_length - removed)) {
        return false;
    }
    tail = edit_length - end;
    new_length = edit_length - removed + replacement_length;
    if (replacement_length > removed) {
        for (index = tail; index > 0U; --index) {
            edit_buffer[start + replacement_length + index - 1U] =
                edit_buffer[end + index - 1U];
        }
    } else {
        for (index = 0U; index < tail; ++index) {
            edit_buffer[start + replacement_length + index] =
                edit_buffer[end + index];
        }
    }
    for (index = 0U; index < replacement_length; ++index) {
        edit_buffer[start + index] = (uint8_t)replacement[index];
    }
    edit_length = new_length;
    return true;
}

static bool build_line_payload(char *payload, size_t capacity,
                               bool leading_newline, const char *text,
                               size_t *length)
{
    size_t text_length = minios_strlen(text);
    size_t cursor = 0U;
    size_t index;

    if (text_length + (leading_newline ? 2U : 1U) > capacity) {
        return false;
    }
    if (leading_newline) {
        payload[cursor] = '\n';
        ++cursor;
    }
    for (index = 0U; index < text_length; ++index) {
        payload[cursor] = text[index];
        ++cursor;
    }
    payload[cursor] = '\n';
    ++cursor;
    *length = cursor;
    return true;
}

static bool append_line(const char *text)
{
    char payload[EDIT_COMMAND_CAPACITY + 2U];
    bool needs_separator = edit_length > 0U &&
        edit_buffer[edit_length - 1U] != (uint8_t)'\n';
    size_t payload_length;

    return build_line_payload(payload, sizeof(payload), needs_separator, text,
                              &payload_length) &&
        replace_range(edit_length, edit_length, payload, payload_length);
}

static bool insert_line(size_t number, const char *text)
{
    char payload[EDIT_COMMAND_CAPACITY + 2U];
    size_t count = line_count();
    size_t start = 0U;
    size_t content_end;
    size_t full_end;
    size_t payload_length;

    if (number == count + 1U) {
        return append_line(text);
    }
    if (number == 0U || number > count ||
        !line_bounds(number, &start, &content_end, &full_end)) {
        return false;
    }
    return build_line_payload(payload, sizeof(payload), false, text,
                              &payload_length) &&
        replace_range(start, start, payload, payload_length);
}

static bool replace_line(size_t number, const char *text)
{
    size_t start;
    size_t content_end;
    size_t full_end;

    if (!line_bounds(number, &start, &content_end, &full_end)) {
        return false;
    }
    return replace_range(start, content_end, text, minios_strlen(text));
}

static bool delete_line(size_t number)
{
    size_t start;
    size_t content_end;
    size_t full_end;

    if (!line_bounds(number, &start, &content_end, &full_end)) {
        return false;
    }
    return replace_range(start, full_end, NULL, 0U);
}

static bool print_range(size_t first, size_t last)
{
    size_t count = line_count();
    size_t number;

    if (count == 0U) {
        return minios_print(1, "(empty)\n");
    }
    if (first == 0U || last < first || last > count) {
        return false;
    }
    for (number = first; number <= last; ++number) {
        size_t start;
        size_t content_end;
        size_t full_end;

        if (!line_bounds(number, &start, &content_end, &full_end) ||
            !minios_print_uint32(1, (uint32_t)number) ||
            !minios_print(1, "\t") ||
            !minios_write_all(1, &edit_buffer[start], content_end - start) ||
            !minios_print(1, "\n")) {
            return false;
        }
    }
    return true;
}

static bool load_file(const char *path, bool *new_file)
{
    struct minios_stat status;
    int32_t descriptor;
    int32_t result;

    edit_length = 0U;
    result = minios_stat(path, &status);
    if (result == -MINIOS_ENOENT) {
        *new_file = true;
        return true;
    }
    if (result < 0) {
        (void)minios_report_error("edit", path, result);
        return false;
    }
    if (status.mode != MINIFS_MODE_REGULAR) {
        (void)minios_report_error("edit", path, -MINIOS_EISDIR);
        return false;
    }
    if (status.size > sizeof(edit_buffer)) {
        (void)minios_report_error("edit", path, -MINIOS_E2BIG);
        return false;
    }
    descriptor = minios_open(path, MINIOS_O_RDONLY);
    if (descriptor < 3) {
        (void)minios_report_error("edit", path, descriptor);
        return false;
    }
    while (edit_length < (size_t)status.size) {
        size_t chunk = (size_t)status.size - edit_length;

        if (chunk > EDIT_IO_CHUNK) {
            chunk = EDIT_IO_CHUNK;
        }
        result = minios_read(
            descriptor, &edit_buffer[edit_length], chunk
        );
        if (result <= 0) {
            (void)minios_report_error(
                "edit", path, result < 0 ? result : -MINIOS_EIO
            );
            (void)minios_close(descriptor);
            return false;
        }
        edit_length += (size_t)result;
    }
    if (minios_close(descriptor) < 0) {
        (void)minios_report_error("edit", path, -MINIOS_EIO);
        return false;
    }
    for (size_t index = 0U; index < edit_length; ++index) {
        if (!text_byte_supported(edit_buffer[index])) {
            (void)minios_print(2, "edit: ");
            (void)minios_print(2, path);
            (void)minios_print(2, ": unsupported non-text byte\n");
            return false;
        }
    }
    *new_file = false;
    return true;
}

static bool save_file(const char *path, bool *dirty)
{
    int32_t descriptor = minios_open(
        path, MINIOS_O_WRONLY | MINIOS_O_CREAT | MINIOS_O_TRUNC
    );
    bool success = true;

    if (descriptor < 3) {
        (void)minios_report_error("edit", path, descriptor);
        return false;
    }
    if (!minios_write_all(descriptor, edit_buffer, edit_length)) {
        (void)minios_report_error("edit", path, -MINIOS_EIO);
        success = false;
    }
    if (minios_close(descriptor) < 0) {
        (void)minios_report_error("edit", path, -MINIOS_EIO);
        success = false;
    }
    if (success) {
        *dirty = false;
        (void)minios_print_uint32(1, (uint32_t)edit_length);
        (void)minios_print(1, " bytes written\n");
    }
    return success;
}

static int read_command(char *command, size_t capacity)
{
    size_t length = 0U;

    for (;;) {
        uint8_t character;
        int32_t result = minios_read(0, &character, 1U);

        if (result != 1) {
            return -1;
        }
        if (character == 4U && length == 0U) {
            (void)minios_print(1, "\n");
            return 0;
        }
        if (character == 3U) {
            command[0] = '\0';
            (void)minios_print(1, "^C\n");
            return 1;
        }
        if (character == (uint8_t)'\n') {
            command[length] = '\0';
            (void)minios_print(1, "\n");
            return 1;
        }
        if (character == (uint8_t)'\b' ||
            character == MINIOS_KEY_DELETE) {
            if (length > 0U) {
                --length;
                if (!minios_print(1, "\b \b")) {
                    return -1;
                }
            }
            continue;
        }
        if (character == (uint8_t)'\t') {
            character = (uint8_t)' ';
        }
        if (character < 0x20U || character > 0x7EU ||
            length + 1U >= capacity) {
            continue;
        }
        command[length] = (char)character;
        ++length;
        if (!minios_write_all(1, &character, 1U)) {
            return -1;
        }
    }
}

static void skip_spaces(char **cursor)
{
    while (**cursor == ' ' || **cursor == '\t') {
        ++*cursor;
    }
}

static char *command_arguments(char *command, char verb)
{
    char *cursor;

    if (command[0] != verb ||
        (command[1] != '\0' && command[1] != ' ' && command[1] != '\t')) {
        return NULL;
    }
    cursor = &command[1];
    skip_spaces(&cursor);
    return cursor;
}

static bool consume_number(char **cursor, size_t *value)
{
    uint32_t parsed = 0U;
    bool found = false;

    skip_spaces(cursor);
    while (**cursor >= '0' && **cursor <= '9') {
        uint32_t digit = (uint32_t)(**cursor - '0');

        if (parsed > (UINT32_MAX - digit) / 10U) {
            return false;
        }
        parsed = parsed * 10U + digit;
        found = true;
        ++*cursor;
    }
    if (!found || (**cursor != '\0' && **cursor != ' ' && **cursor != '\t')) {
        return false;
    }
    skip_spaces(cursor);
    *value = (size_t)parsed;
    return true;
}

static bool print_help(void)
{
    return minios_print(
        1,
        "edit commands:\n"
        "  p [first [last]]  print numbered lines\n"
        "  a [text]          append a line\n"
        "  i line [text]     insert before a line\n"
        "  r line [text]     replace a line\n"
        "  d line            delete a line\n"
        "  w                 save\n"
        "  q / q!            quit / discard changes\n"
        "  h                 show this help\n"
    );
}

static enum editor_action process_command(char *command, const char *path,
                                          bool *dirty)
{
    char *arguments;

    if (command[0] == '\0') {
        return EDITOR_CONTINUE;
    }
    if (minios_streq(command, "h")) {
        return print_help() ? EDITOR_CONTINUE : EDITOR_FATAL;
    }
    if (minios_streq(command, "w")) {
        (void)save_file(path, dirty);
        return EDITOR_CONTINUE;
    }
    if (minios_streq(command, "q!")) {
        return EDITOR_EXIT;
    }
    if (minios_streq(command, "q")) {
        if (*dirty) {
            (void)minios_print(
                2, "edit: unsaved changes; use w or q!\n"
            );
            return EDITOR_CONTINUE;
        }
        return EDITOR_EXIT;
    }
    arguments = command_arguments(command, 'p');
    if (arguments != NULL) {
        size_t count = line_count();
        size_t first;
        size_t last;

        if (*arguments == '\0') {
            return print_range(1U, count) ? EDITOR_CONTINUE : EDITOR_FATAL;
        }
        if (!consume_number(&arguments, &first)) {
            (void)minios_print(2, "usage: p [first [last]]\n");
            return EDITOR_CONTINUE;
        }
        last = first;
        if (*arguments != '\0' && !consume_number(&arguments, &last)) {
            (void)minios_print(2, "usage: p [first [last]]\n");
            return EDITOR_CONTINUE;
        }
        if (*arguments != '\0' || first == 0U || first > last ||
            last > count) {
            (void)minios_print(2, "edit: invalid line range\n");
            return EDITOR_CONTINUE;
        }
        return print_range(first, last) ? EDITOR_CONTINUE : EDITOR_FATAL;
    }
    arguments = command_arguments(command, 'a');
    if (arguments != NULL) {
        if (!append_line(arguments)) {
            (void)minios_print(2, "edit: text buffer full\n");
        } else {
            *dirty = true;
        }
        return EDITOR_CONTINUE;
    }
    arguments = command_arguments(command, 'i');
    if (arguments != NULL) {
        size_t number;

        if (!consume_number(&arguments, &number)) {
            (void)minios_print(2, "usage: i line [text]\n");
        } else if (number == 0U || number > line_count() + 1U) {
            (void)minios_print(2, "edit: invalid line number\n");
        } else if (!insert_line(number, arguments)) {
            (void)minios_print(2, "edit: text buffer full\n");
        } else {
            *dirty = true;
        }
        return EDITOR_CONTINUE;
    }
    arguments = command_arguments(command, 'r');
    if (arguments != NULL) {
        size_t number;

        if (!consume_number(&arguments, &number)) {
            (void)minios_print(2, "usage: r line [text]\n");
        } else if (number == 0U || number > line_count()) {
            (void)minios_print(2, "edit: invalid line number\n");
        } else if (!replace_line(number, arguments)) {
            (void)minios_print(2, "edit: text buffer full\n");
        } else {
            *dirty = true;
        }
        return EDITOR_CONTINUE;
    }
    arguments = command_arguments(command, 'd');
    if (arguments != NULL) {
        size_t number;

        if (!consume_number(&arguments, &number) || *arguments != '\0') {
            (void)minios_print(2, "usage: d line\n");
        } else if (!delete_line(number)) {
            (void)minios_print(2, "edit: invalid line number\n");
        } else {
            *dirty = true;
        }
        return EDITOR_CONTINUE;
    }
    (void)minios_print(2, "edit: unknown command; use h for help\n");
    return EDITOR_CONTINUE;
}

static int run_self_test(void)
{
    static const char path[] = "/edit-self-test";
    static const char expected[] = "beta\ndelta\nomega\n";
    bool dirty = true;
    bool new_file = false;
    int32_t unlink_result = minios_unlink(path);

    if (unlink_result != 0 && unlink_result != -MINIOS_ENOENT) {
        return 1;
    }
    if (!buffer_set_text("alpha\ngamma") ||
        !insert_line(2U, "beta") || !replace_line(3U, "delta") ||
        !delete_line(1U) || !append_line("omega") ||
        !buffer_matches(expected) || !save_file(path, &dirty) || dirty ||
        !load_file(path, &new_file) || new_file ||
        !buffer_matches(expected) || minios_unlink(path) != 0) {
        (void)minios_unlink(path);
        (void)minios_print(2, "edit: self-test failed\n");
        return 1;
    }
    return minios_print(1, "[USER] edit command PASS\n") ? 0 : 1;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    char command[EDIT_COMMAND_CAPACITY];
    bool dirty = false;
    bool new_file = false;

    if (argc == 2 && argv != NULL && argv[0] != NULL && argv[1] != NULL &&
        minios_streq(argv[1], "--self-test")) {
        return run_self_test();
    }
    if (argc != 2 || argv == NULL || argv[0] == NULL || argv[1] == NULL) {
        (void)minios_print(2, "usage: edit file\n");
        return 2;
    }
    if (!load_file(argv[1], &new_file)) {
        return 1;
    }
    if (new_file && !minios_print(1, "[new file]\n")) {
        return 1;
    }
    if (!print_range(1U, line_count()) || !print_help()) {
        return 1;
    }
    for (;;) {
        enum editor_action action;
        int read_result;

        if (!minios_print(1, "edit> ")) {
            return 1;
        }
        read_result = read_command(command, sizeof(command));
        if (read_result < 0) {
            return 1;
        }
        if (read_result == 0) {
            if (dirty) {
                (void)minios_print(
                    2, "edit: unsaved changes; use q! to discard\n"
                );
                continue;
            }
            return 0;
        }
        action = process_command(command, argv[1], &dirty);
        if (action == EDITOR_EXIT) {
            return 0;
        }
        if (action == EDITOR_FATAL) {
            return 1;
        }
    }
}
