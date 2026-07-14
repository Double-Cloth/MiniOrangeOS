#include <minios/abi/errno.h>
#include <minios/abi/minifs.h>
#include <minios/io.h>
#include <minios/user.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

int main(int argc, char **argv);

int main(int argc, char **argv)
{
    struct minios_stat source_status;
    struct minios_stat destination_status;
    uint8_t buffer[256];
    int32_t source = -1;
    int32_t destination = -1;
    int32_t result;
    bool success = false;

    if (argc != 3 || argv == NULL || argv[0] == NULL ||
        argv[1] == NULL || argv[2] == NULL) {
        (void)minios_print(2, "usage: cp source destination\n");
        return 2;
    }
    result = minios_stat(argv[1], &source_status);
    if (result < 0) {
        (void)minios_report_error("cp", argv[1], result);
        return 1;
    }
    if (source_status.mode != MINIFS_MODE_REGULAR) {
        (void)minios_report_error("cp", argv[1], -MINIOS_EISDIR);
        return 1;
    }
    result = minios_stat(argv[2], &destination_status);
    if (result == 0 && destination_status.inode == source_status.inode) {
        (void)minios_report_error("cp", argv[2], -MINIOS_EINVAL);
        return 1;
    }
    if (result == 0 && destination_status.mode == MINIFS_MODE_DIRECTORY) {
        (void)minios_report_error("cp", argv[2], -MINIOS_EISDIR);
        return 1;
    }
    if (result < 0 && result != -MINIOS_ENOENT) {
        (void)minios_report_error("cp", argv[2], result);
        return 1;
    }
    source = minios_open(argv[1], MINIOS_O_RDONLY);
    if (source < 3) {
        (void)minios_report_error("cp", argv[1], source);
        return 1;
    }
    destination = minios_open(
        argv[2], MINIOS_O_WRONLY | MINIOS_O_CREAT | MINIOS_O_TRUNC
    );
    if (destination < 3) {
        (void)minios_report_error("cp", argv[2], destination);
        goto finish;
    }
    while ((result = minios_read(source, buffer, sizeof(buffer))) > 0) {
        if (!minios_write_all(destination, buffer, (size_t)result)) {
            (void)minios_report_error("cp", argv[2], -MINIOS_EIO);
            goto finish;
        }
    }
    if (result < 0) {
        (void)minios_report_error("cp", argv[1], result);
        goto finish;
    }
    success = true;

finish:
    if (destination >= 3 && minios_close(destination) < 0) {
        (void)minios_report_error("cp", argv[2], -MINIOS_EIO);
        success = false;
    }
    if (source >= 3 && minios_close(source) < 0) {
        (void)minios_report_error("cp", argv[1], -MINIOS_EIO);
        success = false;
    }
    return success ? 0 : 1;
}
