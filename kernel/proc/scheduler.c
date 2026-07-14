#include <minios/arch/x86/gdt.h>
#include <minios/arch/x86/irq.h>
#include <minios/arch/x86/user_mode.h>
#include <minios/mm/address_space.h>
#include <minios/mm/heap.h>
#include <minios/mm/pmm.h>
#include <minios/mm/vmm.h>
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
#define PAGE_SIZE 4096U
#define USER_CODE_VIRTUAL 0x00400000U
#define USER_STACK_VIRTUAL 0xBFFFF000U
#define USER_STACK_TOP 0xC0000000U
#define USER_PAGE_LOAD_WINDOW 0xD0C00000U
#define USER_SELF_TEST_YIELD_LIMIT 8U

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
    uint32_t user_entry;
};

static struct process process_table[PROCESS_LIMIT];
static struct process *current_process;
static uint32_t next_pid;
static uint32_t self_test_trace[SELF_TEST_TRACE_LENGTH];
static uint32_t self_test_trace_count;
static volatile uint32_t preemption_mask;
static volatile uint32_t preemption_busy_count;

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
    process->user_entry = 0U;
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

static struct process *find_process_by_pid(uint32_t pid)
{
    size_t index;

    for (index = 0U; index < PROCESS_LIMIT; ++index) {
        if (process_table[index].state != PROCESS_UNUSED &&
            process_table[index].pid == pid) {
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
    struct vmm_address_space address_space = {next->page_directory};

    if (next->page_directory == 0U) {
        if (!vmm_activate_kernel_address_space()) {
            panic("could not activate kernel address space");
        }
    } else if (!vmm_address_space_activate(&address_space)) {
        panic("could not activate process address space");
    }

    current_process = next;
    next->state = PROCESS_RUNNING;
    next->time_slice = DEFAULT_TIME_SLICE;
    gdt_set_kernel_stack(next->kernel_stack_top);
    context_switch(&previous->saved_stack, next->saved_stack);
}

_Noreturn void scheduler_exit_current(int32_t exit_code)
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
    scheduler_exit_current(0);
}

static _Noreturn void user_process_trampoline(void)
{
    enter_user_mode(current_process->user_entry,
                    current_process->user_stack_top);
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

static bool initialize_user_page(uint32_t physical_address,
                                 const uint8_t *source, size_t length)
{
    volatile uint8_t *page =
        (volatile uint8_t *)(uintptr_t)USER_PAGE_LOAD_WINDOW;
    uint32_t unmapped = 0U;
    size_t index;

    if (length > PAGE_SIZE ||
        !vmm_map(USER_PAGE_LOAD_WINDOW, physical_address, VMM_WRITABLE)) {
        return false;
    }
    for (index = 0U; index < PAGE_SIZE; ++index) {
        page[index] = 0U;
    }
    for (index = 0U; index < length; ++index) {
        page[index] = source[index];
    }
    if (!vmm_unmap(USER_PAGE_LOAD_WINDOW, &unmapped) ||
        unmapped != physical_address) {
        panic("user page load window invariant failed");
    }
    return true;
}

static void release_physical_page(uint32_t physical_address)
{
    if (physical_address != 0U && !pmm_free(physical_address)) {
        panic("user process rollback found invalid page");
    }
}

static int32_t user_process_create(const char *name, const uint8_t *image,
                                   size_t image_size)
{
    struct vmm_address_space address_space = {0U};
    struct process *process;
    void *kernel_stack = NULL;
    uint32_t code_physical = 0U;
    uint32_t stack_physical = 0U;
    uint32_t *stack;
    uint32_t flags;

    if (name == NULL || name[0] == '\0' || image == NULL ||
        image_size == 0U || image_size > PAGE_SIZE) {
        return -1;
    }
    flags = irq_save_disable();
    process = find_unused_process();
    if (process == NULL || next_pid == UINT32_MAX ||
        current_process->page_directory != 0U ||
        vmm_current_page_directory() != vmm_kernel_page_directory()) {
        irq_restore(flags);
        return -1;
    }
    kernel_stack = kmalloc(KERNEL_STACK_SIZE);
    code_physical = pmm_alloc();
    stack_physical = pmm_alloc();
    if (kernel_stack == NULL || code_physical == 0U ||
        stack_physical == 0U ||
        !initialize_user_page(code_physical, image, image_size) ||
        !initialize_user_page(stack_physical, NULL, 0U) ||
        !vmm_address_space_create(&address_space) ||
        !vmm_address_space_map(&address_space, USER_CODE_VIRTUAL,
                               code_physical, 0U)) {
        goto rollback;
    }
    code_physical = 0U;
    if (!vmm_address_space_map(&address_space, USER_STACK_VIRTUAL,
                               stack_physical, VMM_WRITABLE)) {
        goto rollback;
    }
    stack_physical = 0U;

    clear_process(process);
    process->pid = next_pid;
    ++next_pid;
    process->state = PROCESS_NEW;
    set_process_name(process, name);
    process->kernel_stack_allocation = kernel_stack;
    process->kernel_stack_top =
        (uint32_t)(uintptr_t)kernel_stack + KERNEL_STACK_SIZE;
    process->user_stack_top = USER_STACK_TOP;
    process->page_directory = address_space.page_directory_physical;
    process->parent_pid = current_process->pid;
    process->time_slice = DEFAULT_TIME_SLICE;
    process->initial_eflags = EFLAGS_INTERRUPT_ENABLE;
    process->user_entry = USER_CODE_VIRTUAL;

    stack = (uint32_t *)(uintptr_t)process->kernel_stack_top;
    *--stack = (uint32_t)(uintptr_t)thread_returned;
    *--stack = (uint32_t)(uintptr_t)user_process_trampoline;
    *--stack = 0U;
    *--stack = 0U;
    *--stack = 0U;
    *--stack = 0U;
    process->saved_stack = stack;
    process->state = PROCESS_READY;
    irq_restore(flags);
    return (int32_t)process->pid;

rollback:
    if (address_space.page_directory_physical != 0U &&
        !vmm_address_space_destroy(&address_space)) {
        panic("user process address-space rollback failed");
    }
    release_physical_page(code_physical);
    release_physical_page(stack_physical);
    if (kernel_stack != NULL && !kfree(kernel_stack)) {
        panic("user process kernel-stack rollback failed");
    }
    irq_restore(flags);
    return -1;
}

static bool reap_user_process(struct process *process)
{
    struct vmm_address_space address_space;

    if (process == NULL || process->state != PROCESS_ZOMBIE ||
        process->page_directory == 0U) {
        return false;
    }
    address_space.page_directory_physical = process->page_directory;
    if (!vmm_address_space_destroy(&address_space)) {
        return false;
    }
    process->page_directory = 0U;
    if (!kfree(process->kernel_stack_allocation)) {
        return false;
    }
    process->state = PROCESS_REAPED;
    clear_process(process);
    return true;
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

void scheduler_on_tick(void)
{
    struct process *next;

    if (current_process == NULL ||
        current_process->state != PROCESS_RUNNING) {
        return;
    }
    if (current_process->time_slice > 1U) {
        --current_process->time_slice;
        return;
    }
    current_process->state = PROCESS_READY;
    next = find_next_ready(current_process);
    if (next == NULL || next == current_process) {
        current_process->state = PROCESS_RUNNING;
        current_process->time_slice = DEFAULT_TIME_SLICE;
        return;
    }
    switch_to(next);
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
            scheduler_exit_current(-1);
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

static void scheduler_preemption_thread(void *argument)
{
    uint32_t identifier = (uint32_t)(uintptr_t)argument;

    preemption_mask |= 1U << (identifier - 1U);
    if (identifier == 1U) {
        preemption_busy_count = 1U;
        while (preemption_mask != 3U) {
            ++preemption_busy_count;
        }
    }
}

bool scheduler_preemption_self_test(void)
{
    uint32_t flags;
    int32_t first_pid;
    int32_t second_pid;
    struct process *first;
    struct process *second;

    if ((irq_read_flags() & EFLAGS_INTERRUPT_ENABLE) == 0U) {
        return false;
    }
    preemption_mask = 0U;
    preemption_busy_count = 0U;
    flags = irq_save_disable();
    first_pid = kernel_thread_create(
        "preempt-one", scheduler_preemption_thread,
        (void *)(uintptr_t)1U
    );
    second_pid = kernel_thread_create(
        "preempt-two", scheduler_preemption_thread,
        (void *)(uintptr_t)2U
    );
    first = first_pid < 1 ? NULL : find_process_by_pid((uint32_t)first_pid);
    second = second_pid < 1 ? NULL : find_process_by_pid((uint32_t)second_pid);
    if (first != NULL) {
        first->initial_eflags = flags & EFLAGS_INTERRUPT_ENABLE;
    }
    if (second != NULL) {
        second->initial_eflags = flags & EFLAGS_INTERRUPT_ENABLE;
    }
    irq_restore(flags);
    if (first == NULL || second == NULL) {
        return false;
    }

    scheduler_yield();
    while (first->state != PROCESS_ZOMBIE ||
           second->state != PROCESS_ZOMBIE) {
        scheduler_yield();
    }
    if (preemption_mask != 3U || preemption_busy_count == 0U ||
        first->exit_code != 0 || second->exit_code != 0 ||
        !kfree(first->kernel_stack_allocation) ||
        !kfree(second->kernel_stack_allocation)) {
        return false;
    }
    first->state = PROCESS_REAPED;
    second->state = PROCESS_REAPED;
    clear_process(first);
    clear_process(second);
    return current_process == &process_table[0] &&
           current_process->state == PROCESS_RUNNING;
}

bool user_process_self_test(void)
{
    struct heap_stats before = heap_get_stats();
    size_t image_size = (size_t)((uintptr_t)user_test_end -
                                 (uintptr_t)user_test_start);
    int32_t pid = user_process_create("ring3-test", user_test_start,
                                      image_size);
    struct process *process =
        pid < 1 ? NULL : find_process_by_pid((uint32_t)pid);
    uint32_t yields = 0U;
    bool passed;

    if (process == NULL) {
        return false;
    }
    while (process->state != PROCESS_ZOMBIE &&
           yields < USER_SELF_TEST_YIELD_LIMIT) {
        ++yields;
        scheduler_yield();
    }
    passed = process->state == PROCESS_ZOMBIE && process->exit_code == 0 &&
        current_process == &process_table[0] &&
        current_process->state == PROCESS_RUNNING &&
        vmm_current_page_directory() == vmm_kernel_page_directory();
    if (!reap_user_process(process)) {
        return false;
    }
    return passed && heap_get_stats().allocated_blocks ==
        before.allocated_blocks && heap_get_stats().allocated_bytes ==
        before.allocated_bytes;
}
