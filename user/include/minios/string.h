#ifndef MINIOS_STRING_H
#define MINIOS_STRING_H

#include <stdbool.h>
#include <stddef.h>

size_t minios_strlen(const char *value);
bool minios_streq(const char *left, const char *right);

#endif
