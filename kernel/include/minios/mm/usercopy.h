#ifndef MINIOS_MM_USERCOPY_H
#define MINIOS_MM_USERCOPY_H

#include <stdbool.h>
#include <stddef.h>

enum user_access {
    USER_ACCESS_READ = 0,
    USER_ACCESS_WRITE = 1
};

bool validate_user_range(const void *user_pointer, size_t length,
                         enum user_access access);
int copy_from_user(void *kernel_destination, const void *user_source,
                   size_t length);
int copy_to_user(void *user_destination, const void *kernel_source,
                 size_t length);
int copy_user_string(char *kernel_destination, const char *user_source,
                     size_t maximum_length);
bool usercopy_self_test(void);

#endif
