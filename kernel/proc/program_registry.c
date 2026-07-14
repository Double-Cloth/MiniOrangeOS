#include <minios/proc/program_registry.h>

#include <stddef.h>
#include <stdint.h>

extern const uint8_t embedded_init_start[];
extern const uint8_t embedded_init_end[];
extern const uint8_t embedded_echo_start[];
extern const uint8_t embedded_echo_end[];
extern const uint8_t embedded_sh_start[];
extern const uint8_t embedded_sh_end[];
extern const uint8_t embedded_ps_start[];
extern const uint8_t embedded_ps_end[];
extern const uint8_t embedded_memtest_start[];
extern const uint8_t embedded_memtest_end[];
extern const uint8_t embedded_fault_start[];
extern const uint8_t embedded_fault_end[];

struct program_entry {
    const char *path;
    const uint8_t *start;
    const uint8_t *end;
};

static const struct program_entry programs[] = {
    {"/bin/init", embedded_init_start, embedded_init_end},
    {"/bin/echo", embedded_echo_start, embedded_echo_end},
    {"/bin/sh", embedded_sh_start, embedded_sh_end},
    {"/bin/ps", embedded_ps_start, embedded_ps_end},
    {"/bin/memtest", embedded_memtest_start, embedded_memtest_end},
    {"/bin/fault", embedded_fault_start, embedded_fault_end}
};

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
    size_t index;

    if (path == NULL || image == NULL || image_size == NULL) {
        return false;
    }
    for (index = 0U; index < sizeof(programs) / sizeof(programs[0]); ++index) {
        if (path_equal(path, programs[index].path)) {
            *image = programs[index].start;
            *image_size =
                (size_t)(programs[index].end - programs[index].start);
            return *image_size != 0U;
        }
    }
    return false;
}
