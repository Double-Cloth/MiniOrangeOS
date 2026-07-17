#include <minios/abi/errno.h>
#include <minios/io.h>
#include <minios/string.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

static bool print_line_number(uint32_t line_number)
{
    return minios_print_uint32(1, line_number) && minios_print(1, "\t");
}

static bool copy_file(const char *path, bool number_lines,
                      uint32_t *line_number, bool *line_start)
{
    uint8_t buffer[256];
    int32_t descriptor = minios_open(path, MINIOS_O_RDONLY);
    int32_t result;

    if (descriptor < 3) {
        (void)minios_report_error("cat", path, descriptor);
        return false;
    }
    while ((result = minios_read(descriptor, buffer, sizeof(buffer))) > 0) {
        size_t offset = 0U;

        while (offset < (size_t)result) {
            size_t end = offset;

            if (number_lines && *line_start) {
                if (!print_line_number(*line_number)) {
                    (void)minios_report_error("cat", path, -MINIOS_EIO);
                    (void)minios_close(descriptor);
                    return false;
                }
                *line_start = false;
            }
            while (end < (size_t)result && buffer[end] != (uint8_t)'\n') {
                ++end;
            }
            if (end < (size_t)result) {
                ++end;
            }
            if (!minios_write_all(1, &buffer[offset], end - offset)) {
                (void)minios_report_error("cat", path, -MINIOS_EIO);
                (void)minios_close(descriptor);
                return false;
            }
            if (end > offset && buffer[end - 1U] == (uint8_t)'\n') {
                *line_start = true;
                if (*line_number < UINT32_MAX) {
                    ++*line_number;
                }
            }
            offset = end;
        }
    }
    if (result < 0) {
        (void)minios_report_error("cat", path, result);
    }
    if (minios_close(descriptor) < 0) {
        (void)minios_report_error("cat", path, -MINIOS_EIO);
        return false;
    }
    return result == 0;
}

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    bool success = true;
    bool number_lines = false;
    bool line_start = true;
    uint32_t line_number = 1U;
    int first_path = 1;
    int index;

    if (argv == NULL || argv[0] == NULL) {
        return 2;
    }
    while (first_path < argc && argv[first_path] != NULL &&
           argv[first_path][0] == '-') {
        if (minios_streq(argv[first_path], "--")) {
            ++first_path;
            break;
        }
        if (!minios_streq(argv[first_path], "-n")) {
            (void)minios_print(2, "usage: cat [-n] [--] file...\n");
            return 2;
        }
        number_lines = true;
        ++first_path;
    }
    if (first_path >= argc) {
        (void)minios_print(2, "usage: cat [-n] [--] file...\n");
        return 2;
    }
    for (index = first_path; index < argc; ++index) {
        if (argv[index] == NULL) {
            return 2;
        }
        if (!copy_file(argv[index], number_lines, &line_number, &line_start)) {
            success = false;
        }
    }
    return success ? 0 : 1;
}
