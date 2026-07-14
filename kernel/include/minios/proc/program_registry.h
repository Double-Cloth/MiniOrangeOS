#ifndef MINIOS_PROC_PROGRAM_REGISTRY_H
#define MINIOS_PROC_PROGRAM_REGISTRY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool program_registry_lookup(const char *path, const uint8_t **image,
                             size_t *image_size);

#endif
