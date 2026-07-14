#ifndef MINIOS_IO_H
#define MINIOS_IO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool minios_write_all(int32_t descriptor, const void *buffer, size_t length);
bool minios_print(int32_t descriptor, const char *text);
bool minios_print_uint32(int32_t descriptor, uint32_t value);
bool minios_print_int32(int32_t descriptor, int32_t value);
const char *minios_error_text(int32_t error);
bool minios_report_error(const char *command, const char *operand,
                         int32_t error);

#endif
