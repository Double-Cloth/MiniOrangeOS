#include <minios/proc/program_registry.h>

#include <stddef.h>
#include <stdint.h>

extern const uint8_t embedded_init_start[];
extern const uint8_t embedded_init_end[];

static bool path_equal(const char *left, const char *right)
{
    size_t index = 0U;

    while (left[index] != '\0' && right[index] != '\0') {
        if (left[index] != right[index]) {
            return false;
        }
        ++index;
    }
    return left[index] == right[index];
}

bool program_registry_lookup(const char *path, const uint8_t **image,
                             size_t *image_size)
{
    if (path == NULL || image == NULL || image_size == NULL ||
        !path_equal(path, "/bin/init")) {
        return false;
    }
    *image = embedded_init_start;
    *image_size = (size_t)(embedded_init_end - embedded_init_start);
    return *image_size != 0U;
}
