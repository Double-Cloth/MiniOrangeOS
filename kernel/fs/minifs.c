#include <minifs-layout.h>
#include <minios/abi/minifs.h>
#include <minios/arch/x86/irq.h>
#include <minios/block/block.h>
#include <minios/errno.h>
#include <minios/fs/minifs.h>
#include <minios/proc/program_registry.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MINIFS_CRC32_POLYNOMIAL 0xEDB88320U
#define MINIFS_BITMAP_BITS_PER_BLOCK (MINIFS_BLOCK_SIZE * 8U)
#define MINIFS_INODES_PER_BLOCK (MINIFS_BLOCK_SIZE / MINIFS_INODE_SIZE)
#define MINIFS_ENTRIES_PER_BLOCK \
    (MINIFS_BLOCK_SIZE / MINIFS_DIRECTORY_ENTRY_SIZE)
#define MINIFS_MAX_FILE_BLOCKS \
    (MINIFS_DIRECT_COUNT + (MINIFS_BLOCK_SIZE / sizeof(uint32_t)))
#define MINIFS_MAX_FILE_SIZE (MINIFS_MAX_FILE_BLOCKS * MINIFS_BLOCK_SIZE)
#define MINIFS_COMPARE_BUFFER_SIZE MINIFS_BLOCK_SIZE

struct minifs_superblock {
    uint32_t total_blocks;
    uint32_t total_inodes;
    uint32_t block_bitmap_start;
    uint32_t block_bitmap_blocks;
    uint32_t inode_bitmap_start;
    uint32_t inode_bitmap_blocks;
    uint32_t inode_table_start;
    uint32_t inode_table_blocks;
    uint32_t data_start;
    uint32_t root_inode;
};

struct minifs_inode {
    uint16_t mode;
    uint16_t link_count;
    uint32_t size;
    uint32_t direct[MINIFS_DIRECT_COUNT];
    uint32_t indirect;
};

static struct minifs_superblock mounted_superblock;
static uint8_t io_block[MINIFS_BLOCK_SIZE];
static uint8_t compare_buffer[MINIFS_COMPARE_BUFFER_SIZE];
static bool mounted;
static bool operation_busy;

static uint16_t read_le16(const uint8_t *source)
{
    return (uint16_t)source[0] | ((uint16_t)source[1] << 8U);
}

static uint32_t read_le32(const uint8_t *source)
{
    return (uint32_t)source[0] | ((uint32_t)source[1] << 8U) |
        ((uint32_t)source[2] << 16U) | ((uint32_t)source[3] << 24U);
}

static uint32_t divide_round_up(uint32_t value, uint32_t divisor)
{
    return value == 0U ? 0U : (value - 1U) / divisor + 1U;
}

static uint32_t superblock_crc32(const uint8_t *block)
{
    uint32_t crc = UINT32_MAX;
    size_t index;

    for (index = 0U; index < MINIFS_BLOCK_SIZE; ++index) {
        uint8_t value = block[index];
        uint32_t bit;

        if (index >= MINIFS_SUPERBLOCK_CHECKSUM_OFFSET &&
            index < MINIFS_SUPERBLOCK_CHECKSUM_OFFSET + sizeof(uint32_t)) {
            value = 0U;
        }
        crc ^= (uint32_t)value;
        for (bit = 0U; bit < 8U; ++bit) {
            uint32_t mask = 0U - (crc & 1U);

            crc = (crc >> 1U) ^ (MINIFS_CRC32_POLYNOMIAL & mask);
        }
    }
    return ~crc;
}

static bool minifs_acquire(uint32_t *irq_flags)
{
    uint32_t flags;

    if (irq_flags == NULL) {
        return false;
    }
    flags = irq_save_disable();
    if (operation_busy) {
        irq_restore(flags);
        return false;
    }
    operation_busy = true;
    *irq_flags = flags;
    return true;
}

static void minifs_release(uint32_t irq_flags)
{
    operation_busy = false;
    irq_restore(irq_flags);
}

static void clear_superblock(void)
{
    mounted_superblock.total_blocks = 0U;
    mounted_superblock.total_inodes = 0U;
    mounted_superblock.block_bitmap_start = 0U;
    mounted_superblock.block_bitmap_blocks = 0U;
    mounted_superblock.inode_bitmap_start = 0U;
    mounted_superblock.inode_bitmap_blocks = 0U;
    mounted_superblock.inode_table_start = 0U;
    mounted_superblock.inode_table_blocks = 0U;
    mounted_superblock.data_start = 0U;
    mounted_superblock.root_inode = 0U;
}

static int32_t read_volume_block(uint32_t relative_block)
{
    if (relative_block >= mounted_superblock.total_blocks ||
        relative_block >= MINIFS_VOLUME_BLOCK_COUNT) {
        return -MINIOS_EIO;
    }
    return block_read(MINIFS_VOLUME_START_BLOCK + relative_block,
                      1U, io_block);
}

static bool superblock_reserved_zero(const uint8_t *block)
{
    size_t index;

    for (index = MINIFS_SUPERBLOCK_HEADER_SIZE;
         index < MINIFS_BLOCK_SIZE;
         ++index) {
        if (block[index] != 0U) {
            return false;
        }
    }
    return true;
}

static bool decode_superblock(const uint8_t *block,
                              struct minifs_superblock *result)
{
    uint32_t total_blocks;
    uint32_t total_inodes;
    uint32_t block_bitmap_blocks;
    uint32_t inode_bitmap_blocks;
    uint32_t inode_table_blocks;
    uint32_t inode_bytes;
    uint32_t expected_inode_bitmap_start;
    uint32_t expected_inode_table_start;
    uint32_t expected_data_start;

    if (block == NULL || result == NULL ||
        read_le32(&block[MINIFS_SUPERBLOCK_MAGIC_OFFSET]) != MINIFS_MAGIC ||
        read_le32(&block[MINIFS_SUPERBLOCK_VERSION_OFFSET]) !=
            MINIFS_VERSION ||
        read_le32(&block[MINIFS_SUPERBLOCK_BLOCK_SIZE_OFFSET]) !=
            MINIFS_BLOCK_SIZE ||
        read_le32(&block[MINIFS_SUPERBLOCK_CHECKSUM_OFFSET]) !=
            superblock_crc32(block) ||
        !superblock_reserved_zero(block)) {
        return false;
    }
    total_blocks = read_le32(&block[MINIFS_SUPERBLOCK_TOTAL_BLOCKS_OFFSET]);
    total_inodes = read_le32(&block[MINIFS_SUPERBLOCK_TOTAL_INODES_OFFSET]);
    if (total_blocks != MINIFS_VOLUME_BLOCK_COUNT || total_inodes == 0U ||
        total_inodes > UINT32_MAX / MINIFS_INODE_SIZE) {
        return false;
    }
    block_bitmap_blocks = divide_round_up(
        total_blocks, MINIFS_BITMAP_BITS_PER_BLOCK
    );
    inode_bitmap_blocks = divide_round_up(
        total_inodes, MINIFS_BITMAP_BITS_PER_BLOCK
    );
    inode_bytes = total_inodes * MINIFS_INODE_SIZE;
    inode_table_blocks = divide_round_up(inode_bytes, MINIFS_BLOCK_SIZE);
    expected_inode_bitmap_start = 1U + block_bitmap_blocks;
    if (expected_inode_bitmap_start < block_bitmap_blocks) {
        return false;
    }
    expected_inode_table_start =
        expected_inode_bitmap_start + inode_bitmap_blocks;
    if (expected_inode_table_start < expected_inode_bitmap_start) {
        return false;
    }
    expected_data_start = expected_inode_table_start + inode_table_blocks;
    if (expected_data_start < expected_inode_table_start ||
        expected_data_start >= total_blocks ||
        read_le32(&block[MINIFS_SUPERBLOCK_BLOCK_BITMAP_START_OFFSET]) != 1U ||
        read_le32(&block[MINIFS_SUPERBLOCK_BLOCK_BITMAP_BLOCKS_OFFSET]) !=
            block_bitmap_blocks ||
        read_le32(&block[MINIFS_SUPERBLOCK_INODE_BITMAP_START_OFFSET]) !=
            expected_inode_bitmap_start ||
        read_le32(&block[MINIFS_SUPERBLOCK_INODE_BITMAP_BLOCKS_OFFSET]) !=
            inode_bitmap_blocks ||
        read_le32(&block[MINIFS_SUPERBLOCK_INODE_TABLE_START_OFFSET]) !=
            expected_inode_table_start ||
        read_le32(&block[MINIFS_SUPERBLOCK_INODE_TABLE_BLOCKS_OFFSET]) !=
            inode_table_blocks ||
        read_le32(&block[MINIFS_SUPERBLOCK_DATA_START_OFFSET]) !=
            expected_data_start ||
        read_le32(&block[MINIFS_SUPERBLOCK_ROOT_INODE_OFFSET]) >=
            total_inodes) {
        return false;
    }
    result->total_blocks = total_blocks;
    result->total_inodes = total_inodes;
    result->block_bitmap_start = 1U;
    result->block_bitmap_blocks = block_bitmap_blocks;
    result->inode_bitmap_start = expected_inode_bitmap_start;
    result->inode_bitmap_blocks = inode_bitmap_blocks;
    result->inode_table_start = expected_inode_table_start;
    result->inode_table_blocks = inode_table_blocks;
    result->data_start = expected_data_start;
    result->root_inode =
        read_le32(&block[MINIFS_SUPERBLOCK_ROOT_INODE_OFFSET]);
    return true;
}

static bool bitmap_bit_set(uint32_t start_block, uint32_t block_count_value,
                           uint32_t bit)
{
    uint32_t bitmap_block = bit / MINIFS_BITMAP_BITS_PER_BLOCK;
    uint32_t within_block = bit % MINIFS_BITMAP_BITS_PER_BLOCK;

    if (bitmap_block >= block_count_value ||
        read_volume_block(start_block + bitmap_block) != 0) {
        return false;
    }
    return (io_block[within_block / 8U] &
            (uint8_t)(1U << (within_block % 8U))) != 0U;
}

static bool decode_inode(const uint8_t *source, struct minifs_inode *result)
{
    uint32_t index;
    uint32_t reserved;

    if (source == NULL || result == NULL) {
        return false;
    }
    result->mode = read_le16(&source[MINIFS_INODE_MODE_OFFSET]);
    result->link_count =
        read_le16(&source[MINIFS_INODE_LINK_COUNT_OFFSET]);
    result->size = read_le32(&source[MINIFS_INODE_SIZE_OFFSET]);
    for (index = 0U; index < MINIFS_DIRECT_COUNT; ++index) {
        result->direct[index] = read_le32(
            &source[MINIFS_INODE_DIRECT_OFFSET + index * sizeof(uint32_t)]
        );
    }
    result->indirect = read_le32(&source[MINIFS_INODE_INDIRECT_OFFSET]);
    reserved = read_le32(&source[MINIFS_INODE_RESERVED_OFFSET]);
    if ((result->mode != MINIFS_MODE_REGULAR &&
         result->mode != MINIFS_MODE_DIRECTORY) ||
        result->link_count == 0U || result->size > MINIFS_MAX_FILE_SIZE ||
        reserved != 0U ||
        (result->mode == MINIFS_MODE_DIRECTORY &&
         (result->size == 0U ||
          result->size % MINIFS_DIRECTORY_ENTRY_SIZE != 0U))) {
        return false;
    }
    return true;
}

static bool inode_pointer_shape_valid(const struct minifs_inode *inode)
{
    uint32_t required_blocks = divide_round_up(
        inode->size, MINIFS_BLOCK_SIZE
    );
    uint32_t direct_required = required_blocks;
    uint32_t index;

    if (direct_required > MINIFS_DIRECT_COUNT) {
        direct_required = MINIFS_DIRECT_COUNT;
    }
    for (index = 0U; index < MINIFS_DIRECT_COUNT; ++index) {
        if ((index < direct_required && inode->direct[index] == 0U) ||
            (index >= direct_required && inode->direct[index] != 0U)) {
            return false;
        }
    }
    return (required_blocks > MINIFS_DIRECT_COUNT && inode->indirect != 0U) ||
        (required_blocks <= MINIFS_DIRECT_COUNT && inode->indirect == 0U);
}

static int32_t read_inode_internal(uint32_t number,
                                   struct minifs_inode *result)
{
    uint32_t table_block;
    uint32_t inode_index;
    size_t offset;

    if (result == NULL || number >= mounted_superblock.total_inodes) {
        return -MINIOS_EINVAL;
    }
    if (!bitmap_bit_set(mounted_superblock.inode_bitmap_start,
                        mounted_superblock.inode_bitmap_blocks, number)) {
        return -MINIOS_EIO;
    }
    table_block = number / MINIFS_INODES_PER_BLOCK;
    inode_index = number % MINIFS_INODES_PER_BLOCK;
    if (table_block >= mounted_superblock.inode_table_blocks ||
        read_volume_block(mounted_superblock.inode_table_start + table_block) !=
            0) {
        return -MINIOS_EIO;
    }
    offset = (size_t)inode_index * MINIFS_INODE_SIZE;
    return decode_inode(&io_block[offset], result) &&
        inode_pointer_shape_valid(result) ? 0 : -MINIOS_EIO;
}

static bool data_block_valid(uint32_t block)
{
    return block >= mounted_superblock.data_start &&
        block < mounted_superblock.total_blocks;
}

static bool data_block_allocated(uint32_t block)
{
    return data_block_valid(block) &&
        bitmap_bit_set(mounted_superblock.block_bitmap_start,
                       mounted_superblock.block_bitmap_blocks, block);
}

static int32_t inode_block_at(const struct minifs_inode *inode,
                              uint32_t file_block, uint32_t *disk_block)
{
    uint32_t required_blocks;
    uint32_t block;

    if (inode == NULL || disk_block == NULL) {
        return -MINIOS_EINVAL;
    }
    required_blocks = divide_round_up(inode->size, MINIFS_BLOCK_SIZE);
    if (file_block >= required_blocks) {
        return -MINIOS_EINVAL;
    }
    if (file_block < MINIFS_DIRECT_COUNT) {
        block = inode->direct[file_block];
    } else {
        uint32_t indirect_index = file_block - MINIFS_DIRECT_COUNT;

        if (!data_block_allocated(inode->indirect) ||
            indirect_index >= MINIFS_INDIRECT_COUNT ||
            read_volume_block(inode->indirect) != 0) {
            return -MINIOS_EIO;
        }
        block = read_le32(&io_block[indirect_index * sizeof(uint32_t)]);
    }
    if (!data_block_allocated(block)) {
        return -MINIOS_EIO;
    }
    *disk_block = block;
    return 0;
}

static bool directory_name_valid(const uint8_t *name)
{
    size_t index;
    bool terminated = false;

    for (index = 0U; index < MINIFS_DIRECTORY_NAME_BYTES; ++index) {
        uint8_t value = name[index];

        if (!terminated) {
            if (value == 0U) {
                if (index == 0U) {
                    return false;
                }
                terminated = true;
            } else if (value > 0x7FU || value == '/') {
                return false;
            }
        } else if (value != 0U) {
            return false;
        }
    }
    return terminated;
}

static bool directory_name_equal(const uint8_t *entry_name,
                                 const char *component, size_t length)
{
    size_t index;

    if (length > MINIFS_NAME_MAX || entry_name[length] != 0U) {
        return false;
    }
    for (index = 0U; index < length; ++index) {
        if (entry_name[index] != (uint8_t)component[index]) {
            return false;
        }
    }
    return true;
}

static int32_t directory_find(const struct minifs_inode *directory,
                              const char *component, size_t length,
                              uint32_t *result)
{
    uint32_t remaining_entries;
    uint32_t file_block = 0U;

    if (directory == NULL || component == NULL || result == NULL ||
        directory->mode != MINIFS_MODE_DIRECTORY || length == 0U ||
        length > MINIFS_NAME_MAX) {
        return -MINIOS_EINVAL;
    }
    remaining_entries = directory->size / MINIFS_DIRECTORY_ENTRY_SIZE;
    while (remaining_entries > 0U) {
        uint32_t disk_block;
        uint32_t entries = remaining_entries;
        uint32_t index;
        int32_t status = inode_block_at(directory, file_block, &disk_block);

        if (status < 0 || read_volume_block(disk_block) != 0) {
            return -MINIOS_EIO;
        }
        if (entries > MINIFS_ENTRIES_PER_BLOCK) {
            entries = MINIFS_ENTRIES_PER_BLOCK;
        }
        for (index = 0U; index < entries; ++index) {
            const uint8_t *entry =
                &io_block[index * MINIFS_DIRECTORY_ENTRY_SIZE];
            uint32_t child = read_le32(
                &entry[MINIFS_DIRECTORY_INODE_OFFSET]
            );
            uint8_t entry_type = entry[MINIFS_DIRECTORY_TYPE_OFFSET];
            const uint8_t *name = &entry[MINIFS_DIRECTORY_NAME_OFFSET];

            if ((entry_type != MINIFS_ENTRY_REGULAR &&
                 entry_type != MINIFS_ENTRY_DIRECTORY) ||
                child >= mounted_superblock.total_inodes ||
                !directory_name_valid(name)) {
                return -MINIOS_EIO;
            }
            if (directory_name_equal(name, component, length)) {
                struct minifs_inode child_inode;

                if (read_inode_internal(child, &child_inode) != 0 ||
                    (entry_type == MINIFS_ENTRY_DIRECTORY &&
                     child_inode.mode != MINIFS_MODE_DIRECTORY) ||
                    (entry_type == MINIFS_ENTRY_REGULAR &&
                     child_inode.mode != MINIFS_MODE_REGULAR)) {
                    return -MINIOS_EIO;
                }
                *result = child;
                return 0;
            }
        }
        remaining_entries -= entries;
        ++file_block;
    }
    return -MINIOS_ENOENT;
}

static int32_t bounded_path_length(const char *path, size_t *length)
{
    size_t index;

    if (path == NULL || length == NULL || path[0] != '/') {
        return -MINIOS_EINVAL;
    }
    for (index = 0U; index < MINIFS_PATH_MAX; ++index) {
        if (path[index] == '\0') {
            *length = index;
            return index == 0U ? -MINIOS_EINVAL : 0;
        }
    }
    return -MINIOS_EINVAL;
}

static int32_t lookup_locked(const char *path, struct minifs_stat *status)
{
    uint32_t current = mounted_superblock.root_inode;
    size_t path_length;
    size_t index = 1U;
    bool trailing_slash;
    int32_t result = bounded_path_length(path, &path_length);

    if (result < 0 || status == NULL) {
        return result < 0 ? result : -MINIOS_EINVAL;
    }
    trailing_slash = path_length > 1U && path[path_length - 1U] == '/';
    while (index < path_length) {
        size_t component_start;
        size_t component_length;
        struct minifs_inode directory;

        while (index < path_length && path[index] == '/') {
            ++index;
        }
        if (index == path_length) {
            break;
        }
        component_start = index;
        while (index < path_length && path[index] != '/') {
            if ((uint8_t)path[index] > 0x7FU) {
                return -MINIOS_EINVAL;
            }
            ++index;
        }
        component_length = index - component_start;
        if (component_length == 0U || component_length > MINIFS_NAME_MAX) {
            return -MINIOS_EINVAL;
        }
        result = read_inode_internal(current, &directory);
        if (result < 0) {
            return result;
        }
        if (directory.mode != MINIFS_MODE_DIRECTORY) {
            return -MINIOS_ENOTDIR;
        }
        if (component_length == 1U && path[component_start] == '.') {
            continue;
        }
        result = directory_find(
            &directory, &path[component_start], component_length, &current
        );
        if (result < 0) {
            return result;
        }
    }
    {
        struct minifs_inode inode;

        result = read_inode_internal(current, &inode);
        if (result < 0) {
            return result;
        }
        if (trailing_slash && inode.mode != MINIFS_MODE_DIRECTORY) {
            return -MINIOS_ENOTDIR;
        }
        status->inode = current;
        status->mode = inode.mode;
        status->link_count = inode.link_count;
        status->size = inode.size;
    }
    return 0;
}

int32_t minifs_mount(void)
{
    struct minifs_superblock candidate;
    struct minifs_inode root;
    uint32_t irq_flags;
    uint32_t block;
    int32_t result = -MINIOS_EIO;

    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    mounted = false;
    clear_superblock();
    if (MINIFS_VOLUME_START_BLOCK > block_count() ||
        MINIFS_VOLUME_BLOCK_COUNT >
            block_count() - MINIFS_VOLUME_START_BLOCK ||
        block_read(MINIFS_VOLUME_START_BLOCK, 1U, io_block) != 0 ||
        !decode_superblock(io_block, &candidate)) {
        minifs_release(irq_flags);
        return -MINIOS_EIO;
    }
    mounted_superblock = candidate;
    for (block = 0U; block < mounted_superblock.data_start; ++block) {
        if (!bitmap_bit_set(mounted_superblock.block_bitmap_start,
                            mounted_superblock.block_bitmap_blocks,
                            block)) {
            goto finish;
        }
    }
    if (!bitmap_bit_set(mounted_superblock.inode_bitmap_start,
                        mounted_superblock.inode_bitmap_blocks,
                        mounted_superblock.root_inode) ||
        read_inode_internal(mounted_superblock.root_inode, &root) != 0 ||
        root.mode != MINIFS_MODE_DIRECTORY) {
        goto finish;
    }
    mounted = true;
    result = 0;

finish:
    if (result < 0) {
        clear_superblock();
    }
    minifs_release(irq_flags);
    return result;
}

uint32_t minifs_total_blocks(void)
{
    return mounted ? mounted_superblock.total_blocks : 0U;
}

uint32_t minifs_total_inodes(void)
{
    return mounted ? mounted_superblock.total_inodes : 0U;
}

int32_t minifs_lookup(const char *path, struct minifs_stat *status)
{
    uint32_t irq_flags;
    int32_t result;

    if (!mounted) {
        return -MINIOS_EIO;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = lookup_locked(path, status);
    minifs_release(irq_flags);
    return result;
}

int32_t minifs_read(uint32_t inode_number, uint32_t offset, void *buffer,
                    size_t length)
{
    struct minifs_inode inode;
    uint8_t *destination = (uint8_t *)buffer;
    uint32_t irq_flags;
    size_t completed = 0U;
    int32_t result;

    if (!mounted || (buffer == NULL && length != 0U)) {
        return -MINIOS_EINVAL;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = read_inode_internal(inode_number, &inode);
    if (result < 0) {
        goto finish;
    }
    if (inode.mode == MINIFS_MODE_DIRECTORY) {
        result = -MINIOS_EISDIR;
        goto finish;
    }
    if (offset >= inode.size || length == 0U) {
        result = 0;
        goto finish;
    }
    if (length > (size_t)(inode.size - offset)) {
        length = (size_t)(inode.size - offset);
    }
    while (completed < length) {
        uint32_t position = offset + (uint32_t)completed;
        uint32_t file_block = position / MINIFS_BLOCK_SIZE;
        size_t block_offset = (size_t)(position % MINIFS_BLOCK_SIZE);
        size_t chunk = MINIFS_BLOCK_SIZE - block_offset;
        uint32_t disk_block;
        size_t index;

        if (chunk > length - completed) {
            chunk = length - completed;
        }
        result = inode_block_at(&inode, file_block, &disk_block);
        if (result < 0 || read_volume_block(disk_block) != 0) {
            result = -MINIOS_EIO;
            goto finish;
        }
        for (index = 0U; index < chunk; ++index) {
            destination[completed + index] = io_block[block_offset + index];
        }
        completed += chunk;
    }
    result = (int32_t)completed;

finish:
    minifs_release(irq_flags);
    return result;
}

bool minifs_self_test(void)
{
    static const char *const paths[] = {
        "/bin/init",
        "/bin/echo",
        "/bin/sh",
        "/bin/ps",
        "/bin/memtest",
        "/bin/fault"
    };
    struct minifs_stat root;
    struct minifs_stat normalized;
    size_t program;

    if (minifs_lookup("/", &root) != 0 ||
        root.mode != MINIFS_MODE_DIRECTORY ||
        minifs_lookup("//bin/./init", &normalized) != 0 ||
        minifs_lookup("/bin/../bin/init", &root) != 0 ||
        normalized.inode != root.inode ||
        minifs_lookup("relative", &root) != -MINIOS_EINVAL ||
        minifs_lookup("/bin/missing", &root) != -MINIOS_ENOENT ||
        minifs_lookup("/bin/init/child", &root) != -MINIOS_ENOTDIR ||
        minifs_read(mounted_superblock.root_inode, 0U, compare_buffer, 1U) !=
            -MINIOS_EISDIR) {
        return false;
    }
    for (program = 0U; program < sizeof(paths) / sizeof(paths[0]); ++program) {
        const uint8_t *embedded;
        size_t embedded_size;
        struct minifs_stat status;
        size_t offset = 0U;

        if (!program_registry_lookup(paths[program], &embedded,
                                     &embedded_size) ||
            minifs_lookup(paths[program], &status) != 0 ||
            status.mode != MINIFS_MODE_REGULAR ||
            status.size != embedded_size) {
            return false;
        }
        while (offset < embedded_size) {
            size_t chunk = embedded_size - offset;
            size_t index;

            if (chunk > sizeof(compare_buffer)) {
                chunk = sizeof(compare_buffer);
            }
            if (minifs_read(status.inode, (uint32_t)offset,
                            compare_buffer, chunk) != (int32_t)chunk) {
                return false;
            }
            for (index = 0U; index < chunk; ++index) {
                if (compare_buffer[index] != embedded[offset + index]) {
                    return false;
                }
            }
            offset += chunk;
        }
        if (minifs_read(status.inode, status.size, compare_buffer, 1U) != 0) {
            return false;
        }
    }
    return true;
}
