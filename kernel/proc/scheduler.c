#include <minios/arch/x86/gdt.h>
#include <minios/arch/x86/irq.h>
#include <minios/mm/heap.h>
#include <minios/panic.h>
#include <minios/proc/scheduler.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PROCESS_LIMIT 16U
#define PROCESS_NAME_LENGTH 32U
#define PROCESS_FD_LIMIT 16U
#define KERNEL_STACK_SIZE 16384U
#define DEFAULT_TIME_SLICE 5U
#define EFLAGS_INTERRUPT_ENABLE 0x00000200U
#define SELF_TEST_THREADS 3U
#define SELF_TEST_ROUNDS 2U
#define SELF_TEST_TRACE_LENGTH (SELF_TEST_THREADS * SELF_TEST_ROUNDS)

enum process_state {
    PROCESS_UNUSED = 0,
    PROCESS_NEW,
    PROCESS_READY,
    PROCESS_RUNNING,
    PROCESS_BLOCKED,
    PROCESS_ZOMBIE,
    PROCESS_REAPED
};

struct process {
    uint32_t pid;
    enum process_state state;
    char name[32];
    uint32_t *saved_stack;
    uint32_t kernel_stack_top;
    uint32_t user_stack_top;
    uint32_t page_directory;
    int32_t exit_code;
    uint32_t parent_pid;
    uint32_t wake_tick;
    uint32_t time_slice;
    uintptr_t fd_table[PROCESS_FD_LIMIT];
    struct process *run_node;
    struct process *wait_node;
    kernel_thread_entry entry;
    void *argument;
    void *kernel_stack_allocation;
    uint32_t initial_eflags;
};

static struct process process_table[PROCESS_LIMIT];
static struct process *current_process;
static uint32_t next_pid;
static uint32_t self_test_trace[SELF_TEST_TRACE_LENGTH];
static uint32_t self_test_trace_count;

void context_switch(uint32_t **old_saved_stack, uint32_t *new_saved_stack);
extern uint8_t boot_stack_top[];

static size_t process_index(const struct process *process)
{
    return (size_t)(process - &process_table[0]);
}

static void clear_process(struct process *process)
{
    size_t index;

    process->pid = 0U;
    process->state = PROCESS_UNUSED;
    for (index = 0U; index < PROCESS_NAME_LENGTH; ++index) {
        process->name[index] = '\0';
    }
    process->saved_stack = NULL;
    process->kernel_stack_top = 0U;
    process->user_stack_top = 0U;
    process->page_directory = 0U;
    process->exit_code = 0;
    process->parent_pid = 0U;
    process->wake_tick = 0U;
    process->time_slice = 0U;
    for (index = 0U; index < PROCESS_FD_LIMIT; ++index) {
        process->fd_table[index] = (uintptr_t)0U;
    }
    process->run_node = NULL;
    process->wait_node = NULL;
    process->entry = NULL;
    process->argument = NULL;
    process->kernel_stack_allocation = NULL;
    process->initial_eflags = 0U;
}

static void set_process_name(struct process *process, const char *name)
{
    size_t index = 0U;

    while (index + 1U < PROCESS_NAME_LENGTH && name[index] != '\0') {
        process->name[index] = name[index];
        ++index;
    }
    process->name[index] = '\0';
}

static struct process *find_unused_process(void)
{
    size_t index;

    for (index = 1U; index < PROCESS_LIMIT; ++index) {
        if (process_table[index].state == PROCESS_UNUSED) {
            return &process_table[index];
        }
    }
    return NULL;
}

static struct process *find_next_ready(const struct process *after)
{
    size_t start = process_index(after);
    size_t offset;

    for (offset = 1U; offset <= PROCESS_LIMIT; ++offset) {
        size_t index = (start + offset) % PROCESS_LIMIT;
        if (process_table[index].state == PROCESS_READY) {
            return &process_table[index];
        }
    }
    return NULL;
}

static void switch_to(struct process *next)
{
    struct process *previous = current_process;

    current_process = next;
    next->state = PROCESS_RUNNING;
    next->time_slice = DEFAULT_TIME_SLICE;
    gdt_set_kernel_stack(next->kernel_stack_top);
    context_switch(&previous->saved_stack, next->saved_stack);
}

static _Noreturn void thread_exit(int32_t exit_code)
{
    uint32_t flags = irq_save_disable();
    struct process *next;

    (void)flags;
    current_process->exit_code = exit_code;
    current_process->state = PROCESS_ZOMBIE;
    next = find_next_ready(current_process);
    if (next == NULL) {
        panic("last kernel thread exited");
    }
    switch_to(next);
    panic("zombie kernel thread resumed");
}

static _Noreturn void thread_trampoline(void)
{
    kernel_thread_entry entry = current_process->entry;
    void *argument = current_process->argument;

    irq_restore(current_process->initial_eflags);
    entry(argument);
    thread_exit(0);
}

static _Noreturn void thread_returned(void)
{
    panic("kernel thread returned past trampoline");
}

void scheduler_init(void)
{
    size_t index;

    for (index = 0U; index < PROCESS_LIMIT; ++index) {
        clear_process(&process_table[index]);
    }
    current_process = &process_table[0];
    current_process->pid = 0U;
    current_process->state = PROCESS_RUNNING;
    set_process_name(current_process, "boot");
    current_process->kernel_stack_top =
        (uint32_t)(uintptr_t)boot_stack_top;
    current_process->time_slice = DEFAULT_TIME_SLICE;
    current_process->initial_eflags = irq_read_flags();
    next_pid = 1U;
}

int32_t kernel_thread_create(const char *name, kernel_thread_entry entry,
                             void *argument)
{
    struct process *process;
    uint32_t *stack;
    void *allocation;
    uint32_t flags;

    if (name == NULL || name[0] == '\0' || entry == NULL) {
        return -1;
    }
    flags = irq_save_disable();
    process = find_unused_process();
    if (process == NULL || next_pid == UINT32_MAX) {
        irq_restore(flags);
        return -1;
    }
    allocation = kmalloc(KERNEL_STACK_SIZE);
    if (allocation == NULL) {
        irq_restore(flags);
        return -1;
    }
    clear_process(process);
    process->pid = next_pid;
    ++next_pid;
    process->state = PROCESS_NEW;
    set_process_name(process, name);
    process->kernel_stack_allocation = allocation;
    process->kernel_stack_top =
        (uint32_t)(uintptr_t)allocation + KERNEL_STACK_SIZE;
    process->entry = entry;
    process->argument = argument;
    process->parent_pid = current_process->pid;
    process->time_slice = DEFAULT_TIME_SLICE;
    process->initial_eflags = flags & EFLAGS_INTERRUPT_ENABLE;

    stack = (uint32_t *)(uintptr_t)process->kernel_stack_top;
    *--stack = (uint32_t)(uintptr_t)thread_returned;
    *--stack = (uint32_t)(uintptr_t)thread_trampoline;
    *--stack = 0U;
    *--stack = 0U;
    *--stack = 0U;
    *--stack = 0U;
    process->saved_stack = stack;
    process->state = PROCESS_READY;
    irq_restore(flags);
    return (int32_t)process->pid;
}

void scheduler_yield(void)
{
    uint32_t flags = irq_save_disable();
    struct process *next;

    current_process->state = PROCESS_READY;
    next = find_next_ready(current_process);
    if (next == NULL || next == current_process) {
        current_process->state = PROCESS_RUNNING;
        irq_restore(flags);
        return;
    }
    switch_to(next);
    irq_restore(flags);
}

uint32_t scheduler_current_pid(void)
{
    return current_process == NULL ? 0U : current_process->pid;
}

static void scheduler_test_thread(void *argument)
{
    uint32_t identifier = (uint32_t)(uintptr_t)argument;
    uint32_t round;

    for (round = 0U; round < SELF_TEST_ROUNDS; ++round) {
        if (self_test_trace_count >= SELF_TEST_TRACE_LENGTH) {
            thread_exit(-1);
        }
        self_test_trace[self_test_trace_count] = identifier;
        ++self_test_trace_count;
        scheduler_yield();
    }
}

bool scheduler_self_test(void)
{
    uint32_t identifiers[SELF_TEST_THREADS];
    uint32_t index;
    bool live;

    self_test_trace_count = 0U;
    for (index = 0U; index < SELF_TEST_THREADS; ++index) {
        int32_t pid = kernel_thread_create(
            "scheduler-test", scheduler_test_thread,
            (void *)(uintptr_t)(index + 1U)
        );
        if (pid < 1) {
            return false;
        }
        identifiers[index] = (uint32_t)pid;
    }
    do {
        live = false;
        for (index = 1U; index <= SELF_TEST_THREADS; ++index) {
            if (process_table[index].state != PROCESS_ZOMBIE) {
                live = true;
            }
        }
        if (live) {
            scheduler_yield();
        }
    } while (live);

    if (self_test_trace_count != SELF_TEST_TRACE_LENGTH) {
        return false;
    }
    for (index = 0U; index < SELF_TEST_TRACE_LENGTH; ++index) {
        if (self_test_trace[index] != (index % SELF_TEST_THREADS) + 1U) {
            return false;
        }
    }
    for (index = 0U; index < SELF_TEST_THREADS; ++index) {
        struct process *process = &process_table[index + 1U];
        if (process->pid != identifiers[index] || process->exit_code != 0 ||
            !kfree(process->kernel_stack_allocation)) {
            return false;
        }
        process->state = PROCESS_REAPED;
        clear_process(process);
    }
    return current_process == &process_table[0] &&
           current_process->state == PROCESS_RUNNING;
}
