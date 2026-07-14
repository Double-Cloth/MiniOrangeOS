#include <minios/abi/errno.h>
#include <minios/abi/minifs.h>
#include <minios/io.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LS_PATH_SIZE 256U

struct ls_options {
    bool show_all;
    bool long_format;
};

static bool join_path(char *destination, size_t capacity,
                      const char *directory, const char *name)
{
    size_t cursor = 0U;
    size_t index;

    for (index = 0U; directory[index] != '\0'; ++index) {
        if (cursor + 1U >= capacity) {
            return false;
        }
        destination[cursor] = directory[index];
        ++cursor;
    }
    if (cursor == 0U || destination[cursor - 1U] != '/') {
        if (cursor + 1U >= capacity) {
            return false;
        }
        destination[cursor] = '/';
        ++cursor;
    }
    for (index = 0U; name[index] != '\0'; ++index) {
        if (cursor + 1U >= capacity) {
            return false;
        }
        destination[cursor] = name[index];
        ++cursor;
    }
    destination[cursor] = '\0';
    return true;
}

static bool print_name(const char *name, uint16_t mode)
{
    return minios_print(1, name) &&
        (mode != MINIFS_MODE_DIRECTORY || minios_print(1, "/")) &&
        minios_print(1, "\n");
}

static bool print_long_entry(const char *display_name,
                             const struct minios_stat *status)
{
    char type = status->mode == MINIFS_MODE_DIRECTORY ? 'd' : '-';

    return minios_write_all(1, &type, 1U) && minios_print(1, " ") &&
        minios_print_uint32(1, status->size) && minios_print(1, " ") &&
        print_name(display_name, status->mode);
}

static bool list_directory(const char *path, const struct ls_options *options)
{
    struct minios_dirent entry;
    int32_t descriptor = minios_open(path, MINIOS_O_RDONLY);
    int32_t result;
    bool success = true;

    if (descriptor < 3) {
        (void)minios_report_error("ls", path, descriptor);
        return false;
    }
    while ((result = minios_readdir(descriptor, &entry, sizeof(entry))) == 1) {
        if (!options->show_all &&
            (minios_streq(entry.name, ".") ||
             minios_streq(entry.name, ".."))) {
            continue;
        }
        if (options->long_format) {
            struct minios_stat status;
            char child_path[LS_PATH_SIZE];

            if (!join_path(child_path, sizeof(child_path), path, entry.name)) {
                (void)minios_report_error(
                    "ls", entry.name, -MINIOS_EINVAL
                );
                success = false;
                continue;
            }
            result = minios_stat(child_path, &status);
            if (result < 0) {
                (void)minios_report_error("ls", child_path, result);
                success = false;
                continue;
            }
            if (!print_long_entry(entry.name, &status)) {
                success = false;
                break;
            }
        } else if (!print_name(entry.name, entry.mode)) {
            success = false;
            break;
        }
    }
    if (result < 0) {
        (void)minios_report_error("ls", path, result);
        success = false;
    }
    if (minios_close(descriptor) < 0) {
        (void)minios_report_error("ls", path, -MINIOS_EIO);
        success = false;
    }
    return success;
}

static bool list_path(const char *path, const struct ls_options *options,
                      bool heading)
{
    struct minios_stat status;
    int32_t result = minios_stat(path, &status);

    if (result < 0) {
        (void)minios_report_error("ls", path, result);
        return false;
    }
    if (heading && (!minios_print(1, path) || !minios_print(1, ":\n"))) {
        return false;
    }
    if (status.mode == MINIFS_MODE_DIRECTORY) {
        return list_directory(path, options);
    }
    return options->long_format ? print_long_entry(path, &status) :
        print_name(path, status.mode);
}

static bool parse_options(int argc, char **argv, struct ls_options *options,
                          int *first_path)
{
    int index = 1;

    options->show_all = false;
    options->long_format = false;
    while (index < argc && argv[index] != NULL && argv[index][0] == '-' &&
           argv[index][1] != '\0') {
        size_t option;

        if (minios_streq(argv[index], "--")) {
            ++index;
            break;
        }
        for (option = 1U; argv[index][option] != '\0'; ++option) {
            if (argv[index][option] == 'a') {
                options->show_all = true;
            } else if (argv[index][option] == 'l') {
                options->long_format = true;
            } else {
                return false;
            }
        }
        ++index;
    }
    *first_path = index;
    return true;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    struct ls_options options;
    int first_path;
    int path_count;
    int index;
    bool success = true;

    if (argc < 1 || argv == NULL || argv[0] == NULL ||
        !parse_options(argc, argv, &options, &first_path)) {
        (void)minios_print(2, "usage: ls [-a] [-l] [path...]\n");
        return 2;
    }
    path_count = argc - first_path;
    if (path_count == 0) {
        return list_path(".", &options, false) ? 0 : 1;
    }
    for (index = first_path; index < argc; ++index) {
        if (argv[index] == NULL) {
            return 2;
        }
        if (index > first_path && !minios_print(1, "\n")) {
            success = false;
        }
        if (!list_path(argv[index], &options, path_count > 1)) {
            success = false;
        }
    }
    return success ? 0 : 1;
}
