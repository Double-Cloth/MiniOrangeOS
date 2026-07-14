#ifndef MINIOS_PROC_SCHEDULER_H
#define MINIOS_PROC_SCHEDULER_H

#include <stdbool.h>
#include <stdint.h>

typedef void (*kernel_thread_entry)(void *argument);

void scheduler_init(void);
int32_t kernel_thread_create(const char *name, kernel_thread_entry entry,
                             void *argument);
void scheduler_yield(void);
uint32_t scheduler_current_pid(void);
bool scheduler_self_test(void);

#endif
