#ifndef MINIOS_USER_H
#define MINIOS_USER_H

#include <stddef.h>
#include <stdint.h>
#include <minios/abi/process.h>

_Noreturn void minios_exit(int32_t status);
int32_t minios_write(int32_t descriptor, const void *buffer, size_t count);
int32_t minios_read(int32_t descriptor, void *buffer, size_t count);
int32_t minios_spawn(const char *path, char *const argv[]);
int32_t minios_waitpid(int32_t pid, int32_t *status);
int32_t minios_getpid(void);
int32_t minios_yield(void);
int32_t minios_sleep(uint32_t ticks);
uint32_t minios_getticks(void);
int32_t minios_ps(struct minios_process_info *processes, size_t capacity);

#endif
