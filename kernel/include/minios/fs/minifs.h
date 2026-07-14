#ifndef MINIOS_FS_MINIFS_H
#define MINIOS_FS_MINIFS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MINIFS_PATH_MAX 256U

struct minifs_stat {
    uint32_t inode;
    uint16_t mode;
    uint16_t link_count;
    uint32_t size;
};

int32_t minifs_mount(void);
uint32_t minifs_total_blocks(void);
uint32_t minifs_total_inodes(void);
int32_t minifs_lookup(const char *path, struct minifs_stat *status);
int32_t minifs_read(uint32_t inode, uint32_t offset, void *buffer,
                    size_t length);
bool minifs_self_test(void);

#endif
