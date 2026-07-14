#include <minios/arch/x86/gdt.h>
#include <minios/arch/x86/irq.h>
#include <minios/arch/x86/page_fault.h>
#include <minios/arch/x86/user_mode.h>
#include <minios/errno.h>
#include <minios/drivers/pit.h>
#include <minios/mm/address_space.h>
#include <minios/mm/heap.h>
#include <minios/mm/pmm.h>
#include <minios/mm/vmm.h>
#include <minios/panic.h>
#include <minios/proc/elf.h>
#include <minios/proc/program_registry.h>
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
#define USER_ARGUMENT_LIMIT 16U
#define USER_ARGUMENT_LENGTH_LIMIT 256U
#define USER_FAULT_TEST_ADDRESS 0x0BADF000U
#define PAGE_FAULT_USER_FLAG 0x04U
#define USER_PRIVILEGE_LEVEL 3U
#define PID_MAXIMUM 0x7FFFFFFFU
#define SLEEP_MAXIMUM_TICKS 0x7FFFFFFFU

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
static uint32_t last_user_fault_pid;
static uint32_t last_user_fault_address;
static uint32_t last_user_fault_error;
static uint32_t last_user_fault_eip;

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

static bool allocate_pid(uint32_t *pid)
{
    uint32_t candidate;

    if (pid == NULL) {
        return false;
    }
    if (next_pid != 0U) {
        *pid = next_pid;
        next_pid = next_pid == PID_MAXIMUM ? 0U : next_pid + 1U;
        return true;
    }
    for (candidate = 1U; candidate <= PID_MAXIMUM; ++candidate) {
        if (find_process_by_pid(candidate) == NULL) {
            *pid = candidate;
            return true;
        }
    }
    return false;
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

static void wake_waiting_parent(const struct process *child)
{
    size_t index;

    for (index = 0U; index < PROCESS_LIMIT; ++index) {
        struct process *parent = &process_table[index];

        if (parent->state == PROCESS_BLOCKED &&
            parent->pid == child->parent_pid &&
            (parent->wait_node == child || parent->wait_node == parent)) {
            parent->wait_node = NULL;
            parent->state = PROCESS_READY;
        }
    }
}

_Noreturn void scheduler_exit_current(int32_t exit_code)
{
    uint32_t flags = irq_save_disable();
    struct process *next;

    (void)flags;
    current_process->exit_code = exit_code;
    current_process->state = PROCESS_ZOMBIE;
    wake_waiting_parent(current_process);
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

static bool scheduler_user_page_fault(uint32_t address, uint32_t error_code,
                                      const struct trap_frame *frame)
{
    if (current_process == NULL || current_process->page_directory == 0U ||
        frame == NULL || (frame->cs & USER_PRIVILEGE_LEVEL) !=
        USER_PRIVILEGE_LEVEL) {
        return false;
    }
    last_user_fault_pid = current_process->pid;
    last_user_fault_address = address;
    last_user_fault_error = error_code;
    last_user_fault_eip = frame->eip;
    scheduler_exit_current(-MINIOS_EFAULT);
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
    page_fault_set_user_handler(scheduler_user_page_fault);
}

int32_t kernel_thread_create(const char *name, kernel_thread_entry entry,
                             void *argument)
{
    struct process *process;
    uint32_t *stack;
    void *allocation;
    uint32_t flags;
    uint32_t pid;

    if (name == NULL || name[0] == '\0' || entry == NULL) {
        return -1;
    }
    flags = irq_save_disable();
    process = find_unused_process();
    if (process == NULL) {
        irq_restore(flags);
        return -1;
    }
    allocation = kmalloc(KERNEL_STACK_SIZE);
    if (allocation == NULL) {
        irq_restore(flags);
        return -1;
    }
    if (!allocate_pid(&pid)) {
        if (!kfree(allocation)) {
            panic("kernel thread PID rollback failed");
        }
        irq_restore(flags);
        return -1;
    }
    clear_process(process);
    process->pid = pid;
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

static bool bounded_string_length(const char *value, size_t *length)
{
    size_t index;

    if (value == NULL || length == NULL) {
        return false;
    }
    for (index = 0U; index < USER_ARGUMENT_LENGTH_LIMIT; ++index) {
        if (value[index] == '\0') {
            *length = index;
            return true;
        }
    }
    return false;
}

static bool initialize_user_stack(uint32_t physical_address,
                                  const char *const argv[],
                                  uint32_t *stack_top)
{
    volatile uint8_t *page =
        (volatile uint8_t *)(uintptr_t)USER_PAGE_LOAD_WINDOW;
    uint32_t argument_addresses[USER_ARGUMENT_LIMIT];
    uint32_t unmapped = 0U;
    size_t argument_lengths[USER_ARGUMENT_LIMIT];
    size_t argument_count = 0U;
    size_t string_bytes = 0U;
    size_t cursor = PAGE_SIZE;
    size_t index;

    if (argv == NULL || argv[0] == NULL || stack_top == NULL) {
        return false;
    }
    while (argv[argument_count] != NULL) {
        size_t length;

        if (argument_count >= USER_ARGUMENT_LIMIT ||
            !bounded_string_length(argv[argument_count], &length) ||
            length + 1U > PAGE_SIZE - string_bytes) {
            return false;
        }
        argument_lengths[argument_count] = length;
        string_bytes += length + 1U;
        ++argument_count;
    }
    if (string_bytes + (argument_count + 2U) * sizeof(uint32_t) + 3U >
        PAGE_SIZE ||
        !vmm_map(USER_PAGE_LOAD_WINDOW, physical_address, VMM_WRITABLE)) {
        return false;
    }
    for (index = 0U; index < PAGE_SIZE; ++index) {
        page[index] = 0U;
    }
    for (index = argument_count; index > 0U; --index) {
        size_t argument = index - 1U;
        size_t length = argument_lengths[argument] + 1U;
        size_t character;

        cursor -= length;
        for (character = 0U; character < length; ++character) {
            page[cursor + character] =
                (uint8_t)argv[argument][character];
        }
        argument_addresses[argument] =
            USER_STACK_VIRTUAL + (uint32_t)cursor;
    }
    cursor &= ~(sizeof(uint32_t) - 1U);
    cursor -= (argument_count + 2U) * sizeof(uint32_t);
    {
        volatile uint32_t *words =
            (volatile uint32_t *)(uintptr_t)(USER_PAGE_LOAD_WINDOW + cursor);

        words[0] = (uint32_t)argument_count;
        for (index = 0U; index < argument_count; ++index) {
            words[index + 1U] = argument_addresses[index];
        }
        words[argument_count + 1U] = 0U;
    }
    *stack_top = USER_STACK_VIRTUAL + (uint32_t)cursor;
    if (!vmm_unmap(USER_PAGE_LOAD_WINDOW, &unmapped) ||
        unmapped != physical_address) {
        panic("user stack load window invariant failed");
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
    uint32_t pid;

    if (name == NULL || name[0] == '\0' || image == NULL ||
        image_size == 0U || image_size > PAGE_SIZE) {
        return -1;
    }
    flags = irq_save_disable();
    process = find_unused_process();
    if (process == NULL ||
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
    if (!allocate_pid(&pid)) {
        goto rollback;
    }

    clear_process(process);
    process->pid = pid;
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

int32_t scheduler_spawn_image(const char *name, const uint8_t *image,
                              size_t image_size,
                              const char *const argv[])
{
    struct vmm_address_space address_space = {0U};
    struct process *process;
    void *kernel_stack = NULL;
    uint32_t stack_physical = 0U;
    uint32_t stack_top = 0U;
    uint32_t entry_point = 0U;
    uint32_t *stack;
    uint32_t flags;
    uint32_t pid;
    int32_t result = -MINIOS_ENOMEM;

    if (name == NULL || name[0] == '\0' || image == NULL ||
        image_size == 0U || argv == NULL || argv[0] == NULL) {
        return -MINIOS_EINVAL;
    }
    flags = irq_save_disable();
    process = find_unused_process();
    if (process == NULL) {
        irq_restore(flags);
        return -MINIOS_EAGAIN;
    }
    kernel_stack = kmalloc(KERNEL_STACK_SIZE);
    stack_physical = pmm_alloc();
    if (kernel_stack == NULL || stack_physical == 0U ||
        !vmm_address_space_create(&address_space)) {
        goto rollback;
    }
    result = elf_load_image(&address_space, image, image_size, &entry_point);
    if (result < 0) {
        goto rollback;
    }
    if (!initialize_user_stack(stack_physical, argv, &stack_top)) {
        result = -MINIOS_EINVAL;
        goto rollback;
    }
    if (!vmm_address_space_map(&address_space, USER_STACK_VIRTUAL,
                               stack_physical, VMM_WRITABLE)) {
        result = -MINIOS_ENOMEM;
        goto rollback;
    }
    stack_physical = 0U;
    if (!allocate_pid(&pid)) {
        result = -MINIOS_EAGAIN;
        goto rollback;
    }

    clear_process(process);
    process->pid = pid;
    process->state = PROCESS_NEW;
    set_process_name(process, name);
    process->kernel_stack_allocation = kernel_stack;
    process->kernel_stack_top =
        (uint32_t)(uintptr_t)kernel_stack + KERNEL_STACK_SIZE;
    process->user_stack_top = stack_top;
    process->page_directory = address_space.page_directory_physical;
    process->parent_pid = current_process->pid;
    process->time_slice = DEFAULT_TIME_SLICE;
    process->initial_eflags = EFLAGS_INTERRUPT_ENABLE;
    process->user_entry = entry_point;

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
        panic("ELF process address-space rollback failed");
    }
    release_physical_page(stack_physical);
    if (kernel_stack != NULL && !kfree(kernel_stack)) {
        panic("ELF process kernel-stack rollback failed");
    }
    irq_restore(flags);
    return result;
}

static bool reap_process(struct process *process)
{
    struct vmm_address_space address_space = {0U};

    if (process == NULL || process->state != PROCESS_ZOMBIE ||
        process == current_process || process->kernel_stack_allocation == NULL) {
        return false;
    }
    if (process->page_directory != 0U) {
        address_space.page_directory_physical = process->page_directory;
        if (!vmm_address_space_destroy(&address_space)) {
            return false;
        }
        process->page_directory = 0U;
    }
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

bool scheduler_sleep_current(uint32_t ticks)
{
    uint32_t flags;
    struct process *next;

    if (ticks == 0U) {
        scheduler_yield();
        return true;
    }
    if (ticks > SLEEP_MAXIMUM_TICKS) {
        return false;
    }
    flags = irq_save_disable();
    next = find_next_ready(current_process);
    if (next == NULL) {
        irq_restore(flags);
        return false;
    }
    current_process->wake_tick = pit_ticks() + ticks;
    current_process->wait_node = NULL;
    current_process->state = PROCESS_BLOCKED;
    switch_to(next);
    irq_restore(flags);
    return true;
}

static struct process *find_child(const struct process *parent,
                                  int32_t requested_pid, bool zombie_only)
{
    size_t index;

    for (index = 1U; index < PROCESS_LIMIT; ++index) {
        struct process *child = &process_table[index];

        if (child->state == PROCESS_UNUSED ||
            child->state == PROCESS_REAPED ||
            child->parent_pid != parent->pid ||
            (requested_pid != -1 &&
             child->pid != (uint32_t)requested_pid) ||
            (zombie_only && child->state != PROCESS_ZOMBIE)) {
            continue;
        }
        return child;
    }
    return NULL;
}

int32_t scheduler_waitpid(int32_t pid, int32_t *exit_code)
{
    uint32_t flags;
    struct process *parent;

    if (pid == 0 || pid < -1) {
        return -MINIOS_EINVAL;
    }
    flags = irq_save_disable();
    parent = current_process;
    for (;;) {
        struct process *child = find_child(parent, pid, true);

        if (child != NULL) {
            int32_t result = (int32_t)child->pid;
            int32_t status = child->exit_code;

            if (!reap_process(child)) {
                panic("waitpid could not reap child");
            }
            if (exit_code != NULL) {
                *exit_code = status;
            }
            irq_restore(flags);
            return result;
        }
        child = find_child(parent, pid, false);
        if (child == NULL) {
            irq_restore(flags);
            return -MINIOS_ECHILD;
        }
        parent->state = PROCESS_BLOCKED;
        parent->wait_node = pid == -1 ? parent : child;
        child = find_next_ready(parent);
        if (child == NULL) {
            parent->wait_node = NULL;
            parent->state = PROCESS_RUNNING;
            irq_restore(flags);
            return -MINIOS_ECHILD;
        }
        switch_to(child);
    }
}

void scheduler_on_tick(void)
{
    struct process *next;
    uint32_t now = pit_ticks();
    size_t index;

    for (index = 1U; index < PROCESS_LIMIT; ++index) {
        struct process *process = &process_table[index];

        if (process->state == PROCESS_BLOCKED &&
            process->wait_node == NULL &&
            (int32_t)(now - process->wake_tick) >= 0) {
            process->wake_tick = 0U;
            process->state = PROCESS_READY;
        }
    }

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

size_t scheduler_process_snapshot(struct minios_process_info *processes,
                                  size_t capacity)
{
    uint32_t flags;
    size_t source;
    size_t count = 0U;

    if (processes == NULL && capacity != 0U) {
        return 0U;
    }
    flags = irq_save_disable();
    for (source = 0U; source < PROCESS_LIMIT && count < capacity; ++source) {
        const struct process *process = &process_table[source];
        size_t character;

        if (process->state == PROCESS_UNUSED ||
            process->state == PROCESS_REAPED) {
            continue;
        }
        processes[count].pid = process->pid;
        processes[count].parent_pid = process->parent_pid;
        processes[count].state = (uint32_t)process->state;
        for (character = 0U; character < MINIOS_PROCESS_NAME_LENGTH;
             ++character) {
            processes[count].name[character] = process->name[character];
        }
        ++count;
    }
    irq_restore(flags);
    return count;
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
        while (preemption_mask != 7U) {
            ++preemption_busy_count;
        }
    }
}

bool scheduler_preemption_self_test(void)
{
    uint32_t flags;
    int32_t first_pid;
    int32_t second_pid;
    int32_t third_pid;
    struct process *first;
    struct process *second;
    struct process *third;

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
    third_pid = kernel_thread_create(
        "preempt-three", scheduler_preemption_thread,
        (void *)(uintptr_t)3U
    );
    first = first_pid < 1 ? NULL : find_process_by_pid((uint32_t)first_pid);
    second = second_pid < 1 ? NULL : find_process_by_pid((uint32_t)second_pid);
    third = third_pid < 1 ? NULL : find_process_by_pid((uint32_t)third_pid);
    if (first != NULL) {
        first->initial_eflags = flags & EFLAGS_INTERRUPT_ENABLE;
    }
    if (second != NULL) {
        second->initial_eflags = flags & EFLAGS_INTERRUPT_ENABLE;
    }
    if (third != NULL) {
        third->initial_eflags = flags & EFLAGS_INTERRUPT_ENABLE;
    }
    irq_restore(flags);
    if (first == NULL || second == NULL || third == NULL) {
        return false;
    }

    scheduler_yield();
    while (first->state != PROCESS_ZOMBIE ||
           second->state != PROCESS_ZOMBIE ||
           third->state != PROCESS_ZOMBIE) {
        scheduler_yield();
    }
    if (preemption_mask != 7U || preemption_busy_count == 0U ||
        first->exit_code != 0 || second->exit_code != 0 ||
        third->exit_code != 0 ||
        !kfree(first->kernel_stack_allocation) ||
        !kfree(second->kernel_stack_allocation) ||
        !kfree(third->kernel_stack_allocation)) {
        return false;
    }
    first->state = PROCESS_REAPED;
    second->state = PROCESS_REAPED;
    third->state = PROCESS_REAPED;
    clear_process(first);
    clear_process(second);
    clear_process(third);
    return current_process == &process_table[0] &&
           current_process->state == PROCESS_RUNNING;
}

static void scheduler_lifecycle_child(void *argument)
{
    scheduler_exit_current((int32_t)(uintptr_t)argument);
}

static bool pid_allocator_self_test(void)
{
    uint32_t flags = irq_save_disable();
    uint32_t saved_next_pid = next_pid;
    struct process *temporary = find_unused_process();
    uint32_t final_pid = 0U;
    uint32_t reused_pid = 0U;
    bool passed = false;

    if (temporary != NULL) {
        next_pid = PID_MAXIMUM;
        if (allocate_pid(&final_pid) && final_pid == PID_MAXIMUM) {
            clear_process(temporary);
            temporary->pid = final_pid;
            temporary->state = PROCESS_NEW;
            passed = allocate_pid(&reused_pid) && reused_pid != 0U &&
                reused_pid != final_pid &&
                find_process_by_pid(reused_pid) == NULL;
            clear_process(temporary);
        }
    }
    next_pid = saved_next_pid;
    irq_restore(flags);
    return passed;
}

bool scheduler_lifecycle_self_test(void)
{
    struct heap_stats before = heap_get_stats();
    int32_t status = 0;
    int32_t pid = kernel_thread_create(
        "wait-child", scheduler_lifecycle_child,
        (void *)(uintptr_t)37U
    );

    if (pid < 1 || scheduler_waitpid(pid, &status) != pid || status != 37 ||
        scheduler_waitpid(pid, NULL) != -MINIOS_ECHILD ||
        scheduler_waitpid(0, NULL) != -MINIOS_EINVAL ||
        !pid_allocator_self_test()) {
        return false;
    }
    return current_process == &process_table[0] &&
        current_process->state == PROCESS_RUNNING &&
        heap_get_stats().allocated_blocks == before.allocated_blocks &&
        heap_get_stats().allocated_bytes == before.allocated_bytes;
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
        if (process->state != PROCESS_ZOMBIE) {
            __asm__ volatile("hlt");
        }
    }
    passed = process->state == PROCESS_ZOMBIE && process->exit_code == 0 &&
        current_process == &process_table[0] &&
        current_process->state == PROCESS_RUNNING &&
        vmm_current_page_directory() == vmm_kernel_page_directory();
    if (!reap_process(process)) {
        return false;
    }
    return passed && heap_get_stats().allocated_blocks ==
        before.allocated_blocks && heap_get_stats().allocated_bytes ==
        before.allocated_bytes;
}

bool user_elf_self_test(void)
{
    static const char *const arguments[] = {
        "/bin/init",
        "--self-test",
        NULL
    };
    struct heap_stats heap_before = heap_get_stats();
    struct pmm_stats pmm_before = pmm_get_stats();
    const uint8_t *image = NULL;
    size_t image_size = 0U;
    int32_t pid;
    struct process *process;
    uint32_t yields = 0U;
    bool passed;

    if (!program_registry_lookup("/bin/init", &image, &image_size) ||
        !elf_loader_validation_self_test(image, image_size)) {
        return false;
    }
    pid = scheduler_spawn_image("init", image, image_size, arguments);
    process = pid < 1 ? NULL : find_process_by_pid((uint32_t)pid);
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
    if (!reap_process(process)) {
        return false;
    }
    return passed &&
        heap_get_stats().allocated_blocks == heap_before.allocated_blocks &&
        heap_get_stats().allocated_bytes == heap_before.allocated_bytes &&
        pmm_get_stats().free_pages == pmm_before.free_pages;
}

bool user_page_fault_self_test(void)
{
    struct heap_stats before = heap_get_stats();
    size_t image_size = (size_t)((uintptr_t)user_fault_test_end -
                                 (uintptr_t)user_fault_test_start);
    int32_t pid;
    struct process *process;
    uint32_t yields = 0U;
    bool passed;

    last_user_fault_pid = 0U;
    last_user_fault_address = 0U;
    last_user_fault_error = 0U;
    last_user_fault_eip = 0U;
    pid = user_process_create("user-fault-test", user_fault_test_start,
                              image_size);
    process = pid < 1 ? NULL : find_process_by_pid((uint32_t)pid);
    if (process == NULL) {
        return false;
    }
    while (process->state != PROCESS_ZOMBIE &&
           yields < USER_SELF_TEST_YIELD_LIMIT) {
        ++yields;
        scheduler_yield();
    }
    passed = process->state == PROCESS_ZOMBIE &&
        process->exit_code == -MINIOS_EFAULT &&
        last_user_fault_pid == (uint32_t)pid &&
        last_user_fault_address == USER_FAULT_TEST_ADDRESS &&
        last_user_fault_error == PAGE_FAULT_USER_FLAG &&
        last_user_fault_eip == USER_CODE_VIRTUAL &&
        current_process == &process_table[0] &&
        current_process->state == PROCESS_RUNNING &&
        vmm_current_page_directory() == vmm_kernel_page_directory();
    if (!reap_process(process)) {
        return false;
    }
    return passed && heap_get_stats().allocated_blocks ==
        before.allocated_blocks && heap_get_stats().allocated_bytes ==
        before.allocated_bytes;
}
