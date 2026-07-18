#ifndef MINIOS_USER_H
#define MINIOS_USER_H

#include <stddef.h>
#include <stdint.h>
#include <minios/abi/file.h>
#include <minios/abi/process.h>

_Noreturn void minios_exit(int32_t status);
int32_t minios_write(int32_t descriptor, const void *buffer, size_t count);
int32_t minios_read(int32_t descriptor, void *buffer, size_t count);
int32_t minios_open(const char *path, uint32_t flags);
int32_t minios_close(int32_t descriptor);
int32_t minios_lseek(int32_t descriptor, int32_t offset, int32_t whence);
int32_t minios_create(const char *path);
int32_t minios_unlink(const char *path);
int32_t minios_mkdir(const char *path);
int32_t minios_readdir(int32_t descriptor, struct minios_dirent *entry,
                       size_t length);
int32_t minios_stat(const char *path, struct minios_stat *status);
int32_t minios_spawn(const char *path, char *const argv[]);
int32_t minios_waitpid(int32_t pid, int32_t *status);
int32_t minios_getpid(void);
int32_t minios_yield(void);
int32_t minios_sleep(uint32_t ticks);
int32_t minios_chdir(const char *path);
int32_t minios_getcwd(char *buffer, size_t capacity);
uint32_t minios_getticks(void);
int32_t minios_ps(struct minios_process_info *processes, size_t capacity);
_Noreturn void minios_shutdown(void);

#endif
