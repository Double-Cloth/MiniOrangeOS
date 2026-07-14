#ifndef MINIOS_ABI_FILE_H
#define MINIOS_ABI_FILE_H

#include <stdint.h>

#define MINIOS_O_RDONLY 0x0000U
#define MINIOS_O_WRONLY 0x0001U
#define MINIOS_O_RDWR 0x0002U
#define MINIOS_O_ACCMODE 0x0003U
#define MINIOS_O_CREAT 0x0100U
#define MINIOS_O_TRUNC 0x0200U

#define MINIOS_SEEK_SET 0
#define MINIOS_SEEK_CUR 1
#define MINIOS_SEEK_END 2

struct minios_stat {
    uint32_t inode;
    uint16_t mode;
    uint16_t link_count;
    uint32_t size;
};

_Static_assert(sizeof(struct minios_stat) == 12U,
               "minios_stat ABI must remain 12 bytes");

#endif
