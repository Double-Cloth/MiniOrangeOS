#include <minios/abi/syscall.h>
#include <minios/user.h>

static int32_t syscall0(uint32_t number);
static int32_t syscall1(uint32_t number, uint32_t argument0);
static int32_t syscall2(uint32_t number, uint32_t argument0, uint32_t argument1);
static int32_t syscall3(
    uint32_t number,
    uint32_t argument0,
    uint32_t argument1,
    uint32_t argument2
);

static int32_t syscall0(uint32_t number) {
    int32_t result;

    __asm__ volatile("int $0x80" : "=a"(result) : "0"(number) : "memory", "cc");
    return result;
}

static int32_t syscall1(uint32_t number, uint32_t argument0) {
    int32_t result;

    __asm__ volatile(
        "int $0x80"
        : "=a"(result)
        : "0"(number), "b"(argument0)
        : "memory", "cc"
    );
    return result;
}

static int32_t syscall2(uint32_t number, uint32_t argument0, uint32_t argument1) {
    int32_t result;

    __asm__ volatile(
        "int $0x80"
        : "=a"(result)
        : "0"(number), "b"(argument0), "c"(argument1)
        : "memory", "cc"
    );
    return result;
}

static int32_t syscall3(
    uint32_t number,
    uint32_t argument0,
    uint32_t argument1,
    uint32_t argument2
) {
    int32_t result;

    __asm__ volatile(
        "int $0x80"
        : "=a"(result)
        : "0"(number), "b"(argument0), "c"(argument1), "d"(argument2)
        : "memory", "cc"
    );
    return result;
}

_Noreturn void minios_exit(int32_t status) {
    (void)syscall1(SYS_exit, (uint32_t)status);
    for (;;) {
        __asm__ volatile("ud2");
    }
}

int32_t minios_write(int32_t descriptor, const void *buffer, size_t count) {
    return syscall3(
        SYS_write,
        (uint32_t)descriptor,
        (uint32_t)(uintptr_t)buffer,
        (uint32_t)count
    );
}

int32_t minios_spawn(const char *path, char *const argv[]) {
    return syscall2(
        SYS_spawn,
        (uint32_t)(uintptr_t)path,
        (uint32_t)(uintptr_t)argv
    );
}

int32_t minios_waitpid(int32_t pid, int32_t *status) {
    return syscall2(SYS_waitpid, (uint32_t)pid, (uint32_t)(uintptr_t)status);
}

int32_t minios_getpid(void) {
    return syscall0(SYS_getpid);
}

int32_t minios_yield(void) {
    return syscall0(SYS_yield);
}

int32_t minios_sleep(uint32_t ticks) {
    return syscall1(SYS_sleep, ticks);
}

uint32_t minios_getticks(void) {
    return (uint32_t)syscall0(SYS_getticks);
}
