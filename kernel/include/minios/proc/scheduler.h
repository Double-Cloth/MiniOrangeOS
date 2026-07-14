#ifndef MINIOS_PROC_SCHEDULER_H
#define MINIOS_PROC_SCHEDULER_H

#include <minios/abi/process.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef void (*kernel_thread_entry)(void *argument);

#define MINIOS_PROCESS_FD_LIMIT 16U

void scheduler_init(void);
int32_t kernel_thread_create(const char *name, kernel_thread_entry entry,
                             void *argument);
int32_t scheduler_spawn_image(const char *name, const uint8_t *image,
                              size_t image_size,
                              const char *const argv[]);
void scheduler_yield(void);
bool scheduler_sleep_current(uint32_t ticks);
int32_t scheduler_waitpid(int32_t pid, int32_t *exit_code);
void scheduler_on_tick(void);
uint32_t scheduler_current_pid(void);
int32_t scheduler_fd_install(uintptr_t handle);
uintptr_t scheduler_fd_get(int32_t descriptor);
uintptr_t scheduler_fd_remove(int32_t descriptor);
size_t scheduler_process_snapshot(struct minios_process_info *processes,
                                  size_t capacity);
_Noreturn void scheduler_exit_current(int32_t exit_code);
bool scheduler_self_test(void);
bool scheduler_preemption_self_test(void);
bool scheduler_lifecycle_self_test(void);
bool user_process_self_test(void);
bool user_elf_self_test(void);
bool user_page_fault_self_test(void);

#endif
