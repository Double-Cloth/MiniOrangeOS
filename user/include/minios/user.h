#ifndef MINIOS_USER_H
#define MINIOS_USER_H

#include <stddef.h>
#include <stdint.h>

_Noreturn void minios_exit(int32_t status);
int32_t minios_write(int32_t descriptor, const void *buffer, size_t count);
int32_t minios_waitpid(int32_t pid, int32_t *status);
int32_t minios_getpid(void);
int32_t minios_yield(void);
int32_t minios_sleep(uint32_t ticks);
uint32_t minios_getticks(void);

#endif
