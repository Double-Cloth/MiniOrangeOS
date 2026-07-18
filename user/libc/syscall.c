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

_Noreturn void minios_shutdown(void) {
    (void)syscall0(SYS_shutdown);
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

int32_t minios_read(int32_t descriptor, void *buffer, size_t count) {
    return syscall3(
        SYS_read,
        (uint32_t)descriptor,
        (uint32_t)(uintptr_t)buffer,
        (uint32_t)count
    );
}

int32_t minios_open(const char *path, uint32_t flags) {
    return syscall2(SYS_open, (uint32_t)(uintptr_t)path, flags);
}

int32_t minios_close(int32_t descriptor) {
    return syscall1(SYS_close, (uint32_t)descriptor);
}

int32_t minios_lseek(int32_t descriptor, int32_t offset, int32_t whence) {
    return syscall3(
        SYS_lseek,
        (uint32_t)descriptor,
        (uint32_t)offset,
        (uint32_t)whence
    );
}

int32_t minios_create(const char *path) {
    return syscall1(SYS_create, (uint32_t)(uintptr_t)path);
}

int32_t minios_unlink(const char *path) {
    return syscall1(SYS_unlink, (uint32_t)(uintptr_t)path);
}

int32_t minios_mkdir(const char *path) {
    return syscall1(SYS_mkdir, (uint32_t)(uintptr_t)path);
}

int32_t minios_readdir(int32_t descriptor, struct minios_dirent *entry,
                       size_t length) {
    return syscall3(
        SYS_readdir,
        (uint32_t)descriptor,
        (uint32_t)(uintptr_t)entry,
        (uint32_t)length
    );
}

int32_t minios_stat(const char *path, struct minios_stat *status) {
    return syscall2(
        SYS_stat,
        (uint32_t)(uintptr_t)path,
        (uint32_t)(uintptr_t)status
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

int32_t minios_chdir(const char *path) {
    return syscall1(SYS_chdir, (uint32_t)(uintptr_t)path);
}

int32_t minios_getcwd(char *buffer, size_t capacity) {
    return syscall2(
        SYS_getcwd,
        (uint32_t)(uintptr_t)buffer,
        (uint32_t)capacity
    );
}

uint32_t minios_getticks(void) {
    return (uint32_t)syscall0(SYS_getticks);
}

int32_t minios_ps(struct minios_process_info *processes, size_t capacity) {
    return syscall2(
        SYS_ps,
        (uint32_t)(uintptr_t)processes,
        (uint32_t)capacity
    );
}
