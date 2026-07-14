#ifndef MINIOS_FS_VFS_H
#define MINIOS_FS_VFS_H

#include <minios/abi/file.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

void vfs_init(void);
int32_t vfs_open(const char *path, uint32_t flags);
int32_t vfs_close(int32_t descriptor);
int32_t vfs_read(int32_t descriptor, void *buffer, size_t length);
int32_t vfs_write(int32_t descriptor, const void *buffer, size_t length);
int32_t vfs_lseek(int32_t descriptor, int32_t offset, int32_t whence);
int32_t vfs_stat(const char *path, struct minios_stat *status);
int32_t vfs_mkdir(const char *path);
int32_t vfs_unlink(const char *path);
int32_t vfs_readdir(int32_t descriptor, struct minios_dirent *entry);
void vfs_close_all_current(void);
bool vfs_self_test(void);

#endif
