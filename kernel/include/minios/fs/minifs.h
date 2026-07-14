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

enum minifs_persistence_result {
    MINIFS_PERSISTENCE_FAILED = 0,
    MINIFS_PERSISTENCE_CREATED = 1,
    MINIFS_PERSISTENCE_VERIFIED_AND_TRUNCATED = 2
};

int32_t minifs_mount(void);
uint32_t minifs_total_blocks(void);
uint32_t minifs_total_inodes(void);
int32_t minifs_lookup(const char *path, struct minifs_stat *status);
int32_t minifs_read(uint32_t inode, uint32_t offset, void *buffer,
                    size_t length);
int32_t minifs_create(const char *path, struct minifs_stat *status);
int32_t minifs_write(uint32_t inode, uint32_t offset, const void *buffer,
                     size_t length);
int32_t minifs_truncate(uint32_t inode, uint32_t new_size);
bool minifs_self_test(void);
enum minifs_persistence_result minifs_persistence_self_test(void);

#endif
