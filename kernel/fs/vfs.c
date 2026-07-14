#include <minios/abi/file.h>
#include <minios/abi/minifs.h>
#include <minios/arch/x86/irq.h>
#include <minios/errno.h>
#include <minios/fs/minifs.h>
#include <minios/fs/vfs.h>
#include <minios/proc/scheduler.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define VFS_FILE_LIMIT 32U
#define VFS_ALLOWED_FLAGS \
    (MINIOS_O_ACCMODE | MINIOS_O_CREAT | MINIOS_O_TRUNC)

enum vfs_file_type {
    VFS_FILE_MINIFS = 1
};

struct vfs_file_ops {
    int32_t (*read)(uint32_t inode, uint32_t offset, void *buffer,
                    size_t length);
    int32_t (*write)(uint32_t inode, uint32_t offset, const void *buffer,
                     size_t length);
    int32_t (*stat)(uint32_t inode, struct minifs_stat *status);
};

struct vfs_file {
    bool used;
    uint32_t refcount;
    enum vfs_file_type type;
    const struct vfs_file_ops *ops;
    uint32_t inode;
    uint32_t offset;
    uint32_t flags;
    uint16_t mode;
};

static const struct vfs_file_ops minifs_file_ops = {
    minifs_read,
    minifs_write,
    minifs_stat_inode
};

static struct vfs_file file_table[VFS_FILE_LIMIT];
static bool vfs_initialized;
static bool vfs_busy;

static bool vfs_acquire(uint32_t *irq_flags)
{
    uint32_t flags;

    if (irq_flags == NULL) {
        return false;
    }
    flags = irq_save_disable();
    if (vfs_busy) {
        irq_restore(flags);
        return false;
    }
    vfs_busy = true;
    *irq_flags = flags;
    return true;
}

static void vfs_release(uint32_t irq_flags)
{
    vfs_busy = false;
    irq_restore(irq_flags);
}

static void clear_file(struct vfs_file *file)
{
    file->used = false;
    file->refcount = 0U;
    file->type = VFS_FILE_MINIFS;
    file->ops = NULL;
    file->inode = 0U;
    file->offset = 0U;
    file->flags = 0U;
    file->mode = 0U;
}

static struct vfs_file *allocate_file(void)
{
    size_t index;

    for (index = 0U; index < VFS_FILE_LIMIT; ++index) {
        if (!file_table[index].used) {
            clear_file(&file_table[index]);
            file_table[index].used = true;
            file_table[index].refcount = 1U;
            return &file_table[index];
        }
    }
    return NULL;
}

static struct vfs_file *file_from_handle(uintptr_t handle)
{
    uintptr_t start = (uintptr_t)&file_table[0];
    uintptr_t end = (uintptr_t)&file_table[VFS_FILE_LIMIT];
    uintptr_t offset;
    struct vfs_file *file;

    if (handle < start || handle >= end) {
        return NULL;
    }
    offset = handle - start;
    if (offset % sizeof(struct vfs_file) != 0U) {
        return NULL;
    }
    file = &file_table[offset / sizeof(struct vfs_file)];
    return file->used && file->refcount > 0U && file->ops != NULL ?
        file : NULL;
}

static bool flags_valid(uint32_t flags)
{
    uint32_t access = flags & MINIOS_O_ACCMODE;

    return (flags & ~VFS_ALLOWED_FLAGS) == 0U &&
        access <= MINIOS_O_RDWR &&
        ((flags & MINIOS_O_TRUNC) == 0U || access != MINIOS_O_RDONLY);
}

static bool file_readable(const struct vfs_file *file)
{
    return (file->flags & MINIOS_O_ACCMODE) != MINIOS_O_WRONLY;
}

static bool file_writable(const struct vfs_file *file)
{
    return (file->flags & MINIOS_O_ACCMODE) != MINIOS_O_RDONLY;
}

void vfs_init(void)
{
    uint32_t flags = irq_save_disable();
    size_t index;

    for (index = 0U; index < VFS_FILE_LIMIT; ++index) {
        clear_file(&file_table[index]);
    }
    vfs_busy = false;
    vfs_initialized = true;
    irq_restore(flags);
}

int32_t vfs_open(const char *path, uint32_t flags)
{
    struct minifs_stat status;
    struct vfs_file *file;
    uint32_t irq_flags;
    int32_t result;

    if (!vfs_initialized || !flags_valid(flags)) {
        return -MINIOS_EINVAL;
    }
    if (!vfs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    file = allocate_file();
    if (file == NULL) {
        result = -MINIOS_ENFILE;
        goto finish;
    }
    result = minifs_lookup(path, &status);
    if (result == -MINIOS_ENOENT && (flags & MINIOS_O_CREAT) != 0U) {
        result = minifs_create(path, &status);
    }
    if (result < 0) {
        clear_file(file);
        goto finish;
    }
    if (status.mode == MINIFS_MODE_DIRECTORY &&
        ((flags & MINIOS_O_ACCMODE) != MINIOS_O_RDONLY ||
         (flags & MINIOS_O_TRUNC) != 0U)) {
        clear_file(file);
        result = -MINIOS_EISDIR;
        goto finish;
    }
    if ((flags & MINIOS_O_TRUNC) != 0U) {
        result = minifs_truncate(status.inode, 0U);
        if (result < 0) {
            clear_file(file);
            goto finish;
        }
        status.size = 0U;
    }
    file->inode = status.inode;
    file->type = VFS_FILE_MINIFS;
    file->ops = &minifs_file_ops;
    file->offset = 0U;
    file->flags = flags;
    file->mode = status.mode;
    result = scheduler_fd_install((uintptr_t)file);
    if (result < 0) {
        clear_file(file);
    }

finish:
    vfs_release(irq_flags);
    return result;
}

int32_t vfs_close(int32_t descriptor)
{
    struct vfs_file *file;
    uintptr_t handle;
    uint32_t irq_flags;
    int32_t result = 0;

    if (!vfs_initialized || !vfs_acquire(&irq_flags)) {
        return !vfs_initialized ? -MINIOS_EIO : -MINIOS_EAGAIN;
    }
    handle = scheduler_fd_remove(descriptor);
    file = file_from_handle(handle);
    if (file == NULL) {
        result = -MINIOS_EBADF;
    } else {
        --file->refcount;
        if (file->refcount == 0U) {
            clear_file(file);
        }
    }
    vfs_release(irq_flags);
    return result;
}

int32_t vfs_read(int32_t descriptor, void *buffer, size_t length)
{
    struct vfs_file *file;
    uint32_t irq_flags;
    int32_t result;

    if (!vfs_initialized || (buffer == NULL && length != 0U)) {
        return -MINIOS_EINVAL;
    }
    if (!vfs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    file = file_from_handle(scheduler_fd_get(descriptor));
    if (file == NULL || !file_readable(file)) {
        result = -MINIOS_EBADF;
    } else if (file->mode == MINIFS_MODE_DIRECTORY) {
        result = -MINIOS_EISDIR;
    } else {
        result = file->ops->read(
            file->inode, file->offset, buffer, length
        );
        if (result > 0) {
            file->offset += (uint32_t)result;
        }
    }
    vfs_release(irq_flags);
    return result;
}

int32_t vfs_write(int32_t descriptor, const void *buffer, size_t length)
{
    struct vfs_file *file;
    uint32_t irq_flags;
    int32_t result;

    if (!vfs_initialized || (buffer == NULL && length != 0U)) {
        return -MINIOS_EINVAL;
    }
    if (!vfs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    file = file_from_handle(scheduler_fd_get(descriptor));
    if (file == NULL || !file_writable(file)) {
        result = -MINIOS_EBADF;
    } else if (file->mode == MINIFS_MODE_DIRECTORY) {
        result = -MINIOS_EISDIR;
    } else {
        result = file->ops->write(
            file->inode, file->offset, buffer, length
        );
        if (result > 0) {
            file->offset += (uint32_t)result;
        }
    }
    vfs_release(irq_flags);
    return result;
}

int32_t vfs_lseek(int32_t descriptor, int32_t offset, int32_t whence)
{
    struct minifs_stat status;
    struct vfs_file *file;
    int64_t base;
    int64_t target;
    uint32_t irq_flags;
    int32_t result;

    if (!vfs_initialized) {
        return -MINIOS_EIO;
    }
    if (!vfs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    file = file_from_handle(scheduler_fd_get(descriptor));
    if (file == NULL) {
        result = -MINIOS_EBADF;
        goto finish;
    }
    if (whence == MINIOS_SEEK_SET) {
        base = 0;
    } else if (whence == MINIOS_SEEK_CUR) {
        base = (int64_t)file->offset;
    } else if (whence == MINIOS_SEEK_END) {
        result = file->ops->stat(file->inode, &status);
        if (result < 0) {
            goto finish;
        }
        base = (int64_t)status.size;
    } else {
        result = -MINIOS_EINVAL;
        goto finish;
    }
    target = base + (int64_t)offset;
    if (target < 0 || target > INT32_MAX) {
        result = -MINIOS_EINVAL;
        goto finish;
    }
    file->offset = (uint32_t)target;
    result = (int32_t)target;

finish:
    vfs_release(irq_flags);
    return result;
}

int32_t vfs_stat(const char *path, struct minios_stat *status)
{
    struct minifs_stat minifs_status;
    int32_t result;

    if (!vfs_initialized || status == NULL) {
        return -MINIOS_EINVAL;
    }
    result = minifs_lookup(path, &minifs_status);
    if (result < 0) {
        return result;
    }
    status->inode = minifs_status.inode;
    status->mode = minifs_status.mode;
    status->link_count = minifs_status.link_count;
    status->size = minifs_status.size;
    return 0;
}

void vfs_close_all_current(void)
{
    int32_t descriptor;

    if (!vfs_initialized) {
        return;
    }
    for (descriptor = 3;
         descriptor < (int32_t)MINIOS_PROCESS_FD_LIMIT;
         ++descriptor) {
        if (scheduler_fd_get(descriptor) != (uintptr_t)0U) {
            (void)vfs_close(descriptor);
        }
    }
}

bool vfs_self_test(void)
{
    struct minios_stat status;
    uint8_t magic[4];
    int32_t first = -1;
    int32_t second = -1;
    int32_t third = -1;
    bool passed = false;
    size_t index;

    for (index = 0U; index < VFS_FILE_LIMIT; ++index) {
        if (file_table[index].used || file_table[index].refcount != 0U) {
            return false;
        }
    }

    first = vfs_open("/bin/init", MINIOS_O_RDONLY);
    second = vfs_open("/bin/init", MINIOS_O_RDONLY);
    if (first < 3 || second < 3 || first == second ||
        vfs_read(first, magic, sizeof(magic)) != (int32_t)sizeof(magic) ||
        magic[0] != 0x7FU || magic[1] != 'E' || magic[2] != 'L' ||
        magic[3] != 'F' ||
        vfs_read(second, magic, 1U) != 1 || magic[0] != 0x7FU ||
        vfs_lseek(first, 0, MINIOS_SEEK_SET) != 0 ||
        vfs_read(first, magic, 1U) != 1 || magic[0] != 0x7FU ||
        vfs_write(first, magic, 1U) != -MINIOS_EBADF ||
        vfs_stat("/bin/init", &status) != 0 ||
        status.mode != MINIFS_MODE_REGULAR || status.size == 0U ||
        vfs_close(first) != 0 || vfs_close(first) != -MINIOS_EBADF ||
        vfs_close(second) != 0) {
        goto finish;
    }
    first = -1;
    second = -1;
    third = vfs_open("/bin/sh", MINIOS_O_RDONLY);
    if (third < 3) {
        goto finish;
    }
    vfs_close_all_current();
    if (scheduler_fd_get(third) != (uintptr_t)0U) {
        goto finish;
    }
    third = -1;
    passed = true;

finish:
    if (first >= 3) {
        (void)vfs_close(first);
    }
    if (second >= 3) {
        (void)vfs_close(second);
    }
    if (third >= 3) {
        (void)vfs_close(third);
    }
    return passed;
}
