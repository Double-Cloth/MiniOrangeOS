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
    uint32_t created_tick;
    uint32_t modified_tick;
};

struct minifs_directory_record {
    uint32_t inode;
    uint32_t offset;
    uint8_t type;
    uint8_t name[MINIFS_DIRECTORY_NAME_BYTES];
};

static struct minifs_superblock mounted_superblock;
static uint8_t io_block[MINIFS_BLOCK_SIZE];
static uint8_t auxiliary_block[MINIFS_BLOCK_SIZE];
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

static void write_le16(uint8_t *destination, uint16_t value)
{
    destination[0] = (uint8_t)value;
    destination[1] = (uint8_t)(value >> 8U);
}

static void write_le32(uint8_t *destination, uint32_t value)
{
    destination[0] = (uint8_t)value;
    destination[1] = (uint8_t)(value >> 8U);
    destination[2] = (uint8_t)(value >> 16U);
    destination[3] = (uint8_t)(value >> 24U);
}

static void clear_bytes(uint8_t *destination, size_t length)
{
    size_t index;

    for (index = 0U; index < length; ++index) {
        destination[index] = 0U;
    }
}

static void copy_bytes(uint8_t *destination, const uint8_t *source,
                       size_t length)
{
    size_t index;

    for (index = 0U; index < length; ++index) {
        destination[index] = source[index];
    }
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

static int32_t read_volume_block_into(uint32_t relative_block, void *buffer)
{
    if (relative_block >= mounted_superblock.total_blocks ||
        relative_block >= MINIFS_VOLUME_BLOCK_COUNT || buffer == NULL) {
        return -MINIOS_EIO;
    }
    return block_read(MINIFS_VOLUME_START_BLOCK + relative_block,
                      1U, buffer);
}

static int32_t read_volume_block(uint32_t relative_block)
{
    return read_volume_block_into(relative_block, io_block);
}

static int32_t write_volume_block_from(uint32_t relative_block,
                                       const void *buffer)
{
    if (relative_block >= mounted_superblock.total_blocks ||
        relative_block >= MINIFS_VOLUME_BLOCK_COUNT || buffer == NULL) {
        return -MINIOS_EIO;
    }
    return block_write(MINIFS_VOLUME_START_BLOCK + relative_block,
                       1U, buffer);
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

static int32_t bitmap_update(uint32_t start_block,
                             uint32_t block_count_value, uint32_t bit,
                             bool value)
{
    uint32_t bitmap_block = bit / MINIFS_BITMAP_BITS_PER_BLOCK;
    uint32_t within_block = bit % MINIFS_BITMAP_BITS_PER_BLOCK;
    uint8_t mask = (uint8_t)(1U << (within_block % 8U));

    if (bitmap_block >= block_count_value ||
        read_volume_block(start_block + bitmap_block) != 0) {
        return -MINIOS_EIO;
    }
    if (value) {
        io_block[within_block / 8U] |= mask;
    } else {
        io_block[within_block / 8U] &= (uint8_t)~mask;
    }
    return write_volume_block_from(start_block + bitmap_block, io_block);
}

static int32_t allocate_bitmap_bit(uint32_t start_block,
                                   uint32_t block_count_value,
                                   uint32_t first, uint32_t limit,
                                   uint32_t *result)
{
    uint32_t bit;
    uint32_t loaded_block = UINT32_MAX;

    if (result == NULL || first >= limit) {
        return -MINIOS_EINVAL;
    }
    for (bit = first; bit < limit; ++bit) {
        uint32_t bitmap_block = bit / MINIFS_BITMAP_BITS_PER_BLOCK;
        uint32_t within_block = bit % MINIFS_BITMAP_BITS_PER_BLOCK;
        uint8_t mask = (uint8_t)(1U << (within_block % 8U));

        if (bitmap_block >= block_count_value) {
            return -MINIOS_EIO;
        }
        if (bitmap_block != loaded_block) {
            if (read_volume_block(start_block + bitmap_block) != 0) {
                return -MINIOS_EIO;
            }
            loaded_block = bitmap_block;
        }
        if ((io_block[within_block / 8U] & mask) == 0U) {
            io_block[within_block / 8U] |= mask;
            if (write_volume_block_from(start_block + bitmap_block,
                                        io_block) != 0) {
                return -MINIOS_EIO;
            }
            *result = bit;
            return 0;
        }
    }
    return -MINIOS_ENOSPC;
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
    result->created_tick =
        read_le32(&source[MINIFS_INODE_CREATED_TICK_OFFSET]);
    result->modified_tick =
        read_le32(&source[MINIFS_INODE_MODIFIED_TICK_OFFSET]);
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

static void encode_inode(const struct minifs_inode *inode, uint8_t *result)
{
    uint32_t index;

    clear_bytes(result, MINIFS_INODE_SIZE);
    write_le16(&result[MINIFS_INODE_MODE_OFFSET], inode->mode);
    write_le16(&result[MINIFS_INODE_LINK_COUNT_OFFSET], inode->link_count);
    write_le32(&result[MINIFS_INODE_SIZE_OFFSET], inode->size);
    for (index = 0U; index < MINIFS_DIRECT_COUNT; ++index) {
        write_le32(
            &result[MINIFS_INODE_DIRECT_OFFSET + index * sizeof(uint32_t)],
            inode->direct[index]
        );
    }
    write_le32(&result[MINIFS_INODE_INDIRECT_OFFSET], inode->indirect);
    write_le32(&result[MINIFS_INODE_CREATED_TICK_OFFSET],
               inode->created_tick);
    write_le32(&result[MINIFS_INODE_MODIFIED_TICK_OFFSET],
               inode->modified_tick);
}

static void clear_inode(struct minifs_inode *inode)
{
    uint32_t index;

    inode->mode = MINIFS_MODE_REGULAR;
    inode->link_count = 1U;
    inode->size = 0U;
    for (index = 0U; index < MINIFS_DIRECT_COUNT; ++index) {
        inode->direct[index] = 0U;
    }
    inode->indirect = 0U;
    inode->created_tick = 0U;
    inode->modified_tick = 0U;
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

static int32_t write_inode_internal(uint32_t number,
                                    const struct minifs_inode *inode)
{
    uint32_t table_block;
    uint32_t inode_index;
    size_t offset;

    if (inode == NULL || number >= mounted_superblock.total_inodes ||
        !inode_pointer_shape_valid(inode)) {
        return -MINIOS_EINVAL;
    }
    table_block = number / MINIFS_INODES_PER_BLOCK;
    inode_index = number % MINIFS_INODES_PER_BLOCK;
    if (table_block >= mounted_superblock.inode_table_blocks ||
        read_volume_block(mounted_superblock.inode_table_start + table_block) !=
            0) {
        return -MINIOS_EIO;
    }
    offset = (size_t)inode_index * MINIFS_INODE_SIZE;
    encode_inode(inode, &io_block[offset]);
    return write_volume_block_from(
        mounted_superblock.inode_table_start + table_block, io_block
    );
}

static int32_t allocate_inode(uint32_t *result)
{
    return allocate_bitmap_bit(
        mounted_superblock.inode_bitmap_start,
        mounted_superblock.inode_bitmap_blocks,
        1U,
        mounted_superblock.total_inodes,
        result
    );
}

static int32_t free_inode(uint32_t inode_number)
{
    if (inode_number == mounted_superblock.root_inode ||
        inode_number >= mounted_superblock.total_inodes) {
        return -MINIOS_EINVAL;
    }
    return bitmap_update(mounted_superblock.inode_bitmap_start,
                         mounted_superblock.inode_bitmap_blocks,
                         inode_number, false);
}

static int32_t clear_inode_record(uint32_t inode_number)
{
    uint32_t table_block;
    uint32_t inode_index;
    size_t offset;

    if (inode_number == mounted_superblock.root_inode ||
        inode_number >= mounted_superblock.total_inodes) {
        return -MINIOS_EINVAL;
    }
    table_block = inode_number / MINIFS_INODES_PER_BLOCK;
    inode_index = inode_number % MINIFS_INODES_PER_BLOCK;
    if (table_block >= mounted_superblock.inode_table_blocks ||
        read_volume_block(mounted_superblock.inode_table_start + table_block) !=
            0) {
        return -MINIOS_EIO;
    }
    offset = (size_t)inode_index * MINIFS_INODE_SIZE;
    clear_bytes(&io_block[offset], MINIFS_INODE_SIZE);
    return write_volume_block_from(
        mounted_superblock.inode_table_start + table_block, io_block
    );
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

static int32_t allocate_block(uint32_t *result)
{
    uint32_t block;
    int32_t status = allocate_bitmap_bit(
        mounted_superblock.block_bitmap_start,
        mounted_superblock.block_bitmap_blocks,
        mounted_superblock.data_start,
        mounted_superblock.total_blocks,
        &block
    );

    if (status < 0) {
        return status;
    }
    clear_bytes(auxiliary_block, sizeof(auxiliary_block));
    if (write_volume_block_from(block, auxiliary_block) != 0) {
        (void)bitmap_update(mounted_superblock.block_bitmap_start,
                            mounted_superblock.block_bitmap_blocks,
                            block, false);
        return -MINIOS_EIO;
    }
    *result = block;
    return 0;
}

static int32_t free_block(uint32_t block)
{
    if (!data_block_valid(block)) {
        return -MINIOS_EINVAL;
    }
    return bitmap_update(mounted_superblock.block_bitmap_start,
                         mounted_superblock.block_bitmap_blocks,
                         block, false);
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

static bool directory_entry_unused(const uint8_t *entry)
{
    size_t index;

    for (index = 0U; index < MINIFS_DIRECTORY_ENTRY_SIZE; ++index) {
        if (entry[index] != 0U) {
            return false;
        }
    }
    return true;
}

static int32_t directory_find_internal(
    const struct minifs_inode *directory,
    const char *component, size_t length,
    struct minifs_directory_record *result
)
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

            if (entry_type == MINIFS_ENTRY_UNUSED) {
                if (!directory_entry_unused(entry)) {
                    return -MINIOS_EIO;
                }
                continue;
            }
            if ((entry_type != MINIFS_ENTRY_REGULAR &&
                 entry_type != MINIFS_ENTRY_DIRECTORY) ||
                child >= mounted_superblock.total_inodes ||
                !directory_name_valid(name)) {
                return -MINIOS_EIO;
            }
            if (directory_name_equal(name, component, length)) {
                struct minifs_inode child_inode;

                copy_bytes(result->name, name, sizeof(result->name));
                if (read_inode_internal(child, &child_inode) != 0 ||
                    (entry_type == MINIFS_ENTRY_DIRECTORY &&
                     child_inode.mode != MINIFS_MODE_DIRECTORY) ||
                    (entry_type == MINIFS_ENTRY_REGULAR &&
                     child_inode.mode != MINIFS_MODE_REGULAR)) {
                    return -MINIOS_EIO;
                }
                result->inode = child;
                result->offset =
                    file_block * MINIFS_BLOCK_SIZE +
                    index * MINIFS_DIRECTORY_ENTRY_SIZE;
                result->type = entry_type;
                return 0;
            }
        }
        remaining_entries -= entries;
        ++file_block;
    }
    return -MINIOS_ENOENT;
}

static int32_t directory_find(const struct minifs_inode *directory,
                              const char *component, size_t length,
                              uint32_t *result)
{
    struct minifs_directory_record record;
    int32_t status;

    if (result == NULL) {
        return -MINIOS_EINVAL;
    }
    status = directory_find_internal(directory, component, length, &record);
    if (status == 0) {
        *result = record.inode;
    }
    return status;
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

static int32_t resolve_parent_locked(const char *path,
                                     uint32_t *parent_number,
                                     struct minifs_inode *parent,
                                     const char **name, size_t *name_length)
{
    uint32_t current = mounted_superblock.root_inode;
    size_t path_length;
    size_t index = 1U;
    int32_t result = bounded_path_length(path, &path_length);

    if (result < 0 || parent_number == NULL || parent == NULL ||
        name == NULL || name_length == NULL || path_length <= 1U ||
        path[path_length - 1U] == '/') {
        return result < 0 ? result : -MINIOS_EINVAL;
    }
    while (index < path_length) {
        size_t component_start;
        size_t component_length;
        size_t next;
        struct minifs_inode directory;

        while (index < path_length && path[index] == '/') {
            ++index;
        }
        if (index == path_length) {
            return -MINIOS_EINVAL;
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
        next = index;
        while (next < path_length && path[next] == '/') {
            ++next;
        }
        result = read_inode_internal(current, &directory);
        if (result < 0) {
            return result;
        }
        if (directory.mode != MINIFS_MODE_DIRECTORY) {
            return -MINIOS_ENOTDIR;
        }
        if (next == path_length) {
            if ((component_length == 1U && path[component_start] == '.') ||
                (component_length == 2U && path[component_start] == '.' &&
                 path[component_start + 1U] == '.')) {
                return -MINIOS_EINVAL;
            }
            *parent_number = current;
            *parent = directory;
            *name = &path[component_start];
            *name_length = component_length;
            return 0;
        }
        if (!(component_length == 1U && path[component_start] == '.')) {
            result = directory_find(&directory, &path[component_start],
                                    component_length, &current);
            if (result < 0) {
                return result;
            }
        }
        index = next;
    }
    return -MINIOS_EINVAL;
}

static int32_t write_chunk_locked(uint32_t inode_number,
                                  struct minifs_inode *inode,
                                  uint32_t offset, const uint8_t *source,
                                  size_t length);

static void encode_directory_entry(uint8_t *entry, uint32_t child_number,
                                   uint8_t entry_type, const char *name,
                                   size_t name_length)
{
    size_t index;

    clear_bytes(entry, MINIFS_DIRECTORY_ENTRY_SIZE);
    write_le32(&entry[MINIFS_DIRECTORY_INODE_OFFSET], child_number);
    entry[MINIFS_DIRECTORY_TYPE_OFFSET] = entry_type;
    for (index = 0U; index < name_length; ++index) {
        entry[MINIFS_DIRECTORY_NAME_OFFSET + index] = (uint8_t)name[index];
    }
}

static int32_t directory_append_locked(uint32_t directory_number,
                                       struct minifs_inode *directory,
                                       uint32_t child_number,
                                       uint8_t entry_type,
                                       const char *name, size_t name_length)
{
    uint8_t entry[MINIFS_DIRECTORY_ENTRY_SIZE];
    uint32_t offset;
    uint16_t old_link_count;
    bool appended;
    int32_t result;

    if (directory == NULL || name == NULL || name_length == 0U ||
        name_length > MINIFS_NAME_MAX ||
        (entry_type != MINIFS_ENTRY_REGULAR &&
         entry_type != MINIFS_ENTRY_DIRECTORY) ||
        directory->size > MINIFS_MAX_FILE_SIZE -
            MINIFS_DIRECTORY_ENTRY_SIZE) {
        return -MINIOS_EINVAL;
    }
    encode_directory_entry(entry, child_number, entry_type,
                           name, name_length);
    offset = 0U;
    while (offset < directory->size) {
        uint32_t disk_block;
        uint32_t file_block = offset / MINIFS_BLOCK_SIZE;
        size_t block_offset = (size_t)(offset % MINIFS_BLOCK_SIZE);

        if (inode_block_at(directory, file_block, &disk_block) != 0 ||
            read_volume_block(disk_block) != 0) {
            return -MINIOS_EIO;
        }
        if (directory_entry_unused(&io_block[block_offset])) {
            break;
        }
        offset += MINIFS_DIRECTORY_ENTRY_SIZE;
    }
    appended = offset == directory->size;
    old_link_count = directory->link_count;
    if (entry_type == MINIFS_ENTRY_DIRECTORY) {
        if (directory->link_count == UINT16_MAX) {
            return -MINIOS_ENOSPC;
        }
        ++directory->link_count;
    }
    result = write_chunk_locked(directory_number, directory, offset,
                                entry, sizeof(entry));
    if (result < 0) {
        directory->link_count = old_link_count;
        return result;
    }
    if (!appended && entry_type == MINIFS_ENTRY_DIRECTORY &&
        write_inode_internal(directory_number, directory) != 0) {
        uint8_t empty[MINIFS_DIRECTORY_ENTRY_SIZE];

        clear_bytes(empty, sizeof(empty));
        (void)write_chunk_locked(directory_number, directory, offset,
                                 empty, sizeof(empty));
        directory->link_count = old_link_count;
        return -MINIOS_EIO;
    }
    return 0;
}

static void rollback_created_inode(uint32_t inode_number)
{
    (void)clear_inode_record(inode_number);
    (void)free_inode(inode_number);
}

static int32_t create_locked(const char *path, struct minifs_stat *status)
{
    struct minifs_inode parent;
    struct minifs_inode inode;
    const char *name;
    size_t name_length;
    uint32_t parent_number;
    uint32_t inode_number;
    uint32_t existing;
    int32_t result = resolve_parent_locked(path, &parent_number, &parent,
                                           &name, &name_length);

    if (result < 0 || status == NULL) {
        return result < 0 ? result : -MINIOS_EINVAL;
    }
    result = directory_find(&parent, name, name_length, &existing);
    if (result == 0) {
        return -MINIOS_EEXIST;
    }
    if (result != -MINIOS_ENOENT) {
        return result;
    }
    result = allocate_inode(&inode_number);
    if (result < 0) {
        return result;
    }
    clear_inode(&inode);
    if (write_inode_internal(inode_number, &inode) != 0) {
        rollback_created_inode(inode_number);
        return -MINIOS_EIO;
    }
    result = directory_append_locked(parent_number, &parent, inode_number,
                                     MINIFS_ENTRY_REGULAR,
                                     name, name_length);
    if (result < 0) {
        rollback_created_inode(inode_number);
        return result;
    }
    status->inode = inode_number;
    status->mode = inode.mode;
    status->link_count = inode.link_count;
    status->size = inode.size;
    return 0;
}

static int32_t directory_empty_locked(const struct minifs_inode *directory)
{
    uint32_t offset;

    if (directory == NULL || directory->mode != MINIFS_MODE_DIRECTORY) {
        return -MINIOS_ENOTDIR;
    }
    for (offset = 0U; offset < directory->size;
         offset += MINIFS_DIRECTORY_ENTRY_SIZE) {
        uint32_t disk_block;
        uint32_t file_block = offset / MINIFS_BLOCK_SIZE;
        size_t block_offset = (size_t)(offset % MINIFS_BLOCK_SIZE);
        const uint8_t *entry;
        const uint8_t *name;
        uint8_t type;

        if (inode_block_at(directory, file_block, &disk_block) != 0 ||
            read_volume_block(disk_block) != 0) {
            return -MINIOS_EIO;
        }
        entry = &io_block[block_offset];
        type = entry[MINIFS_DIRECTORY_TYPE_OFFSET];
        if (type == MINIFS_ENTRY_UNUSED) {
            if (!directory_entry_unused(entry)) {
                return -MINIOS_EIO;
            }
            continue;
        }
        name = &entry[MINIFS_DIRECTORY_NAME_OFFSET];
        if ((type != MINIFS_ENTRY_REGULAR &&
             type != MINIFS_ENTRY_DIRECTORY) ||
            !directory_name_valid(name)) {
            return -MINIOS_EIO;
        }
        if (!directory_name_equal(name, ".", 1U) &&
            !directory_name_equal(name, "..", 2U)) {
            return -MINIOS_ENOTEMPTY;
        }
    }
    return 0;
}

static int32_t release_inode_locked(uint32_t inode_number,
                                    const struct minifs_inode *inode)
{
    uint32_t blocks;
    uint32_t index;

    if (inode == NULL) {
        return -MINIOS_EINVAL;
    }
    blocks = divide_round_up(inode->size, MINIFS_BLOCK_SIZE);
    if (blocks > MINIFS_DIRECT_COUNT &&
        read_volume_block_into(inode->indirect, compare_buffer) != 0) {
        return -MINIOS_EIO;
    }
    for (index = 0U; index < blocks && index < MINIFS_DIRECT_COUNT; ++index) {
        if (free_block(inode->direct[index]) != 0) {
            return -MINIOS_EIO;
        }
    }
    for (index = MINIFS_DIRECT_COUNT; index < blocks; ++index) {
        uint32_t block = read_le32(
            &compare_buffer[(index - MINIFS_DIRECT_COUNT) * sizeof(uint32_t)]
        );

        if (free_block(block) != 0) {
            return -MINIOS_EIO;
        }
    }
    if (inode->indirect != 0U && free_block(inode->indirect) != 0) {
        return -MINIOS_EIO;
    }
    if (clear_inode_record(inode_number) != 0 ||
        free_inode(inode_number) != 0) {
        return -MINIOS_EIO;
    }
    return 0;
}

static int32_t mkdir_locked(const char *path)
{
    struct minifs_inode parent;
    struct minifs_inode inode;
    const char *name;
    size_t name_length;
    uint32_t parent_number;
    uint32_t inode_number;
    uint32_t data_block;
    uint32_t existing;
    int32_t result = resolve_parent_locked(path, &parent_number, &parent,
                                           &name, &name_length);

    if (result < 0) {
        return result;
    }
    result = directory_find(&parent, name, name_length, &existing);
    if (result == 0) {
        return -MINIOS_EEXIST;
    }
    if (result != -MINIOS_ENOENT) {
        return result;
    }
    result = allocate_inode(&inode_number);
    if (result < 0) {
        return result;
    }
    result = allocate_block(&data_block);
    if (result < 0) {
        (void)free_inode(inode_number);
        return result;
    }
    clear_inode(&inode);
    inode.mode = MINIFS_MODE_DIRECTORY;
    inode.link_count = 2U;
    inode.size = 2U * MINIFS_DIRECTORY_ENTRY_SIZE;
    inode.direct[0] = data_block;
    clear_bytes(io_block, sizeof(io_block));
    encode_directory_entry(&io_block[0], inode_number,
                           MINIFS_ENTRY_DIRECTORY, ".", 1U);
    encode_directory_entry(&io_block[MINIFS_DIRECTORY_ENTRY_SIZE],
                           parent_number, MINIFS_ENTRY_DIRECTORY, "..", 2U);
    if (write_volume_block_from(data_block, io_block) != 0 ||
        write_inode_internal(inode_number, &inode) != 0) {
        (void)free_block(data_block);
        rollback_created_inode(inode_number);
        return -MINIOS_EIO;
    }
    result = directory_append_locked(parent_number, &parent, inode_number,
                                     MINIFS_ENTRY_DIRECTORY,
                                     name, name_length);
    if (result < 0) {
        (void)free_block(data_block);
        rollback_created_inode(inode_number);
        return result;
    }
    return 0;
}

static int32_t unlink_locked(const char *path)
{
    struct minifs_inode parent;
    struct minifs_inode inode;
    struct minifs_directory_record record;
    const char *name;
    size_t name_length;
    uint32_t parent_number;
    uint32_t disk_block;
    uint32_t file_block;
    size_t block_offset;
    uint16_t old_link_count;
    int32_t result = resolve_parent_locked(path, &parent_number, &parent,
                                           &name, &name_length);

    if (result < 0) {
        return result;
    }
    result = directory_find_internal(&parent, name, name_length, &record);
    if (result < 0) {
        return result;
    }
    if (record.inode == mounted_superblock.root_inode ||
        read_inode_internal(record.inode, &inode) != 0) {
        return -MINIOS_EIO;
    }
    if (inode.mode == MINIFS_MODE_DIRECTORY) {
        result = directory_empty_locked(&inode);
        if (result < 0) {
            return result;
        }
        if (parent.link_count == 0U) {
            return -MINIOS_EIO;
        }
    }
    file_block = record.offset / MINIFS_BLOCK_SIZE;
    block_offset = (size_t)(record.offset % MINIFS_BLOCK_SIZE);
    if (inode_block_at(&parent, file_block, &disk_block) != 0 ||
        read_volume_block(disk_block) != 0) {
        return -MINIOS_EIO;
    }
    copy_bytes(auxiliary_block, &io_block[block_offset],
               MINIFS_DIRECTORY_ENTRY_SIZE);
    clear_bytes(&io_block[block_offset], MINIFS_DIRECTORY_ENTRY_SIZE);
    if (write_volume_block_from(disk_block, io_block) != 0) {
        return -MINIOS_EIO;
    }
    old_link_count = parent.link_count;
    if (inode.mode == MINIFS_MODE_DIRECTORY) {
        --parent.link_count;
        if (write_inode_internal(parent_number, &parent) != 0) {
            if (read_volume_block(disk_block) == 0) {
                copy_bytes(&io_block[block_offset], auxiliary_block,
                           MINIFS_DIRECTORY_ENTRY_SIZE);
                (void)write_volume_block_from(disk_block, io_block);
            }
            parent.link_count = old_link_count;
            return -MINIOS_EIO;
        }
    }
    return release_inode_locked(record.inode, &inode);
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

int32_t minifs_stat_inode(uint32_t inode_number, struct minifs_stat *status)
{
    struct minifs_inode inode;
    uint32_t irq_flags;
    int32_t result;

    if (!mounted) {
        return -MINIOS_EIO;
    }
    if (status == NULL) {
        return -MINIOS_EINVAL;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = read_inode_internal(inode_number, &inode);
    if (result == 0) {
        status->inode = inode_number;
        status->mode = inode.mode;
        status->link_count = inode.link_count;
        status->size = inode.size;
    }
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

int32_t minifs_create(const char *path, struct minifs_stat *status)
{
    uint32_t irq_flags;
    int32_t result;

    if (!mounted) {
        return -MINIOS_EIO;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = create_locked(path, status);
    minifs_release(irq_flags);
    return result;
}

int32_t minifs_mkdir(const char *path)
{
    uint32_t irq_flags;
    int32_t result;

    if (!mounted) {
        return -MINIOS_EIO;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = mkdir_locked(path);
    minifs_release(irq_flags);
    return result;
}

int32_t minifs_unlink(const char *path)
{
    uint32_t irq_flags;
    int32_t result;

    if (!mounted) {
        return -MINIOS_EIO;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = unlink_locked(path);
    minifs_release(irq_flags);
    return result;
}

int32_t minifs_readdir(uint32_t inode_number, uint32_t *offset,
                       struct minifs_dirent *entry)
{
    struct minifs_inode directory;
    uint32_t cursor;
    uint32_t irq_flags;
    int32_t result;

    if (!mounted || offset == NULL || entry == NULL ||
        *offset % MINIFS_DIRECTORY_ENTRY_SIZE != 0U) {
        return -MINIOS_EINVAL;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = read_inode_internal(inode_number, &directory);
    if (result < 0) {
        goto finish;
    }
    if (directory.mode != MINIFS_MODE_DIRECTORY) {
        result = -MINIOS_ENOTDIR;
        goto finish;
    }
    cursor = *offset;
    while (cursor < directory.size) {
        uint8_t raw_entry[MINIFS_DIRECTORY_ENTRY_SIZE];
        uint32_t disk_block;
        uint32_t file_block = cursor / MINIFS_BLOCK_SIZE;
        size_t block_offset = (size_t)(cursor % MINIFS_BLOCK_SIZE);
        const uint8_t *disk_entry;
        const uint8_t *name;
        struct minifs_inode child;
        uint32_t child_number;
        uint8_t type;
        size_t name_length = 0U;

        if (inode_block_at(&directory, file_block, &disk_block) != 0 ||
            read_volume_block(disk_block) != 0) {
            result = -MINIOS_EIO;
            goto finish;
        }
        copy_bytes(raw_entry, &io_block[block_offset], sizeof(raw_entry));
        disk_entry = raw_entry;
        cursor += MINIFS_DIRECTORY_ENTRY_SIZE;
        type = disk_entry[MINIFS_DIRECTORY_TYPE_OFFSET];
        if (type == MINIFS_ENTRY_UNUSED) {
            if (!directory_entry_unused(disk_entry)) {
                result = -MINIOS_EIO;
                goto finish;
            }
            continue;
        }
        name = &disk_entry[MINIFS_DIRECTORY_NAME_OFFSET];
        child_number = read_le32(
            &disk_entry[MINIFS_DIRECTORY_INODE_OFFSET]
        );
        if ((type != MINIFS_ENTRY_REGULAR &&
             type != MINIFS_ENTRY_DIRECTORY) ||
            !directory_name_valid(name) ||
            read_inode_internal(child_number, &child) != 0 ||
            (type == MINIFS_ENTRY_DIRECTORY &&
             child.mode != MINIFS_MODE_DIRECTORY) ||
            (type == MINIFS_ENTRY_REGULAR &&
             child.mode != MINIFS_MODE_REGULAR)) {
            result = -MINIOS_EIO;
            goto finish;
        }
        while (name_length < MINIFS_NAME_MAX && name[name_length] != 0U) {
            entry->name[name_length] = (char)name[name_length];
            ++name_length;
        }
        entry->name[name_length] = '\0';
        entry->inode = child_number;
        entry->mode = child.mode;
        entry->name_length = (uint16_t)name_length;
        *offset = cursor;
        result = 1;
        goto finish;
    }
    *offset = cursor;
    result = 0;

finish:
    minifs_release(irq_flags);
    return result;
}

static int32_t write_chunk_locked(uint32_t inode_number,
                                  struct minifs_inode *inode,
                                  uint32_t offset, const uint8_t *source,
                                  size_t length)
{
    uint32_t old_size = inode->size;
    uint32_t old_indirect = inode->indirect;
    uint32_t file_block = offset / MINIFS_BLOCK_SIZE;
    size_t block_offset = (size_t)(offset % MINIFS_BLOCK_SIZE);
    uint32_t allocated_blocks = divide_round_up(inode->size,
                                                MINIFS_BLOCK_SIZE);
    uint32_t end = offset + (uint32_t)length;
    uint32_t disk_block;
    uint32_t new_indirect = 0U;
    bool pointer_written = false;

    if (file_block < allocated_blocks) {
        if (inode_block_at(inode, file_block, &disk_block) != 0 ||
            read_volume_block(disk_block) != 0) {
            return -MINIOS_EIO;
        }
        copy_bytes(&io_block[block_offset], source, length);
        if (write_volume_block_from(disk_block, io_block) != 0) {
            return -MINIOS_EIO;
        }
        if (end > inode->size) {
            inode->size = end;
            if (write_inode_internal(inode_number, inode) != 0) {
                inode->size = old_size;
                return -MINIOS_EIO;
            }
        }
        return 0;
    }
    if (file_block != allocated_blocks) {
        return -MINIOS_EINVAL;
    }
    if (file_block >= MINIFS_DIRECT_COUNT && inode->indirect == 0U) {
        int32_t status = allocate_block(&new_indirect);

        if (status < 0) {
            return status;
        }
        inode->indirect = new_indirect;
    }
    {
        int32_t status = allocate_block(&disk_block);

        if (status < 0) {
            if (new_indirect != 0U) {
                inode->indirect = old_indirect;
                (void)free_block(new_indirect);
            }
            return status;
        }
    }
    clear_bytes(io_block, sizeof(io_block));
    copy_bytes(&io_block[block_offset], source, length);
    if (write_volume_block_from(disk_block, io_block) != 0) {
        (void)free_block(disk_block);
        if (new_indirect != 0U) {
            inode->indirect = old_indirect;
            (void)free_block(new_indirect);
        }
        return -MINIOS_EIO;
    }
    if (file_block < MINIFS_DIRECT_COUNT) {
        inode->direct[file_block] = disk_block;
    } else {
        uint32_t indirect_index = file_block - MINIFS_DIRECT_COUNT;

        if (indirect_index >= MINIFS_INDIRECT_COUNT ||
            read_volume_block_into(inode->indirect, auxiliary_block) != 0) {
            (void)free_block(disk_block);
            if (new_indirect != 0U) {
                inode->indirect = old_indirect;
                (void)free_block(new_indirect);
            }
            return -MINIOS_EIO;
        }
        write_le32(&auxiliary_block[indirect_index * sizeof(uint32_t)],
                   disk_block);
        if (write_volume_block_from(inode->indirect, auxiliary_block) != 0) {
            (void)free_block(disk_block);
            if (new_indirect != 0U) {
                inode->indirect = old_indirect;
                (void)free_block(new_indirect);
            }
            return -MINIOS_EIO;
        }
        pointer_written = true;
    }
    inode->size = end;
    if (write_inode_internal(inode_number, inode) != 0) {
        inode->size = old_size;
        if (file_block < MINIFS_DIRECT_COUNT) {
            inode->direct[file_block] = 0U;
        } else if (pointer_written && new_indirect == 0U) {
            uint32_t indirect_index = file_block - MINIFS_DIRECT_COUNT;

            write_le32(
                &auxiliary_block[indirect_index * sizeof(uint32_t)], 0U
            );
            (void)write_volume_block_from(inode->indirect, auxiliary_block);
        }
        (void)free_block(disk_block);
        if (new_indirect != 0U) {
            inode->indirect = old_indirect;
            (void)free_block(new_indirect);
        }
        return -MINIOS_EIO;
    }
    return 0;
}

int32_t minifs_write(uint32_t inode_number, uint32_t offset,
                     const void *buffer, size_t length)
{
    struct minifs_inode inode;
    const uint8_t *source = (const uint8_t *)buffer;
    uint32_t irq_flags;
    size_t completed = 0U;
    int32_t result;

    if (!mounted || (buffer == NULL && length != 0U) ||
        length > (size_t)INT32_MAX || offset > MINIFS_MAX_FILE_SIZE ||
        length > (size_t)(MINIFS_MAX_FILE_SIZE - offset)) {
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
    if (offset > inode.size) {
        result = -MINIOS_EINVAL;
        goto finish;
    }
    while (completed < length) {
        uint32_t position = offset + (uint32_t)completed;
        size_t block_offset = (size_t)(position % MINIFS_BLOCK_SIZE);
        size_t chunk = MINIFS_BLOCK_SIZE - block_offset;

        if (chunk > length - completed) {
            chunk = length - completed;
        }
        result = write_chunk_locked(inode_number, &inode, position,
                                    &source[completed], chunk);
        if (result < 0) {
            if (completed > 0U) {
                result = (int32_t)completed;
            }
            goto finish;
        }
        completed += chunk;
    }
    result = (int32_t)completed;

finish:
    minifs_release(irq_flags);
    return result;
}

static int32_t truncate_locked(uint32_t inode_number, uint32_t new_size)
{
    struct minifs_inode inode;
    struct minifs_inode old_inode;
    uint32_t old_blocks;
    uint32_t new_blocks;
    uint32_t index;

    if (read_inode_internal(inode_number, &inode) != 0) {
        return -MINIOS_EIO;
    }
    if (inode.mode == MINIFS_MODE_DIRECTORY) {
        return -MINIOS_EISDIR;
    }
    if (new_size > inode.size) {
        return -MINIOS_EINVAL;
    }
    if (new_size == inode.size) {
        return 0;
    }
    old_inode = inode;
    old_blocks = divide_round_up(inode.size, MINIFS_BLOCK_SIZE);
    new_blocks = divide_round_up(new_size, MINIFS_BLOCK_SIZE);
    if (old_inode.indirect != 0U) {
        if (read_volume_block_into(old_inode.indirect, auxiliary_block) != 0) {
            return -MINIOS_EIO;
        }
        copy_bytes(compare_buffer, auxiliary_block, sizeof(compare_buffer));
    }
    if (new_blocks > MINIFS_DIRECT_COUNT) {
        uint32_t first = new_blocks - MINIFS_DIRECT_COUNT;
        uint32_t count = old_blocks - MINIFS_DIRECT_COUNT;

        for (index = first; index < count; ++index) {
            write_le32(&auxiliary_block[index * sizeof(uint32_t)], 0U);
        }
        if (write_volume_block_from(old_inode.indirect, auxiliary_block) != 0) {
            return -MINIOS_EIO;
        }
    } else {
        inode.indirect = 0U;
    }
    for (index = new_blocks;
         index < old_blocks && index < MINIFS_DIRECT_COUNT;
         ++index) {
        inode.direct[index] = 0U;
    }
    inode.size = new_size;
    if (write_inode_internal(inode_number, &inode) != 0) {
        if (new_blocks > MINIFS_DIRECT_COUNT) {
            (void)write_volume_block_from(old_inode.indirect, compare_buffer);
        }
        return -MINIOS_EIO;
    }
    for (index = new_blocks;
         index < old_blocks && index < MINIFS_DIRECT_COUNT;
         ++index) {
        if (free_block(old_inode.direct[index]) != 0) {
            return -MINIOS_EIO;
        }
    }
    if (old_blocks > MINIFS_DIRECT_COUNT) {
        uint32_t first = new_blocks;

        if (first < MINIFS_DIRECT_COUNT) {
            first = MINIFS_DIRECT_COUNT;
        }
        for (index = first; index < old_blocks; ++index) {
            uint32_t pointer_index = index - MINIFS_DIRECT_COUNT;
            uint32_t block = read_le32(
                &compare_buffer[pointer_index * sizeof(uint32_t)]
            );

            if (free_block(block) != 0) {
                return -MINIOS_EIO;
            }
        }
        if (new_blocks <= MINIFS_DIRECT_COUNT &&
            free_block(old_inode.indirect) != 0) {
            return -MINIOS_EIO;
        }
    }
    return 0;
}

int32_t minifs_truncate(uint32_t inode_number, uint32_t new_size)
{
    uint32_t irq_flags;
    int32_t result;

    if (!mounted || new_size > MINIFS_MAX_FILE_SIZE) {
        return -MINIOS_EINVAL;
    }
    if (!minifs_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    result = truncate_locked(inode_number, new_size);
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

static uint8_t persistence_pattern(uint32_t position)
{
    return (uint8_t)(position * 37U + 0x5AU);
}

static bool verify_persistence_file(const struct minifs_stat *status)
{
    uint32_t offset = 0U;

    while (offset < status->size) {
        size_t chunk = (size_t)(status->size - offset);
        size_t index;

        if (chunk > sizeof(compare_buffer)) {
            chunk = sizeof(compare_buffer);
        }
        if (minifs_read(status->inode, offset, compare_buffer, chunk) !=
            (int32_t)chunk) {
            return false;
        }
        for (index = 0U; index < chunk; ++index) {
            if (compare_buffer[index] !=
                persistence_pattern(offset + (uint32_t)index)) {
                return false;
            }
        }
        offset += (uint32_t)chunk;
    }
    return minifs_read(status->inode, status->size,
                       compare_buffer, 1U) == 0;
}

#define MINIFS_EXPANSION_FILE_COUNT 65U

static void expansion_file_path(uint32_t index, char *path)
{
    static const char prefix[] = "/p6-expand/f";
    size_t position;

    for (position = 0U; position < sizeof(prefix) - 1U; ++position) {
        path[position] = prefix[position];
    }
    path[position] = (char)('0' + index / 10U);
    path[position + 1U] = (char)('0' + index % 10U);
    path[position + 2U] = '\0';
}

static bool verify_expansion_directory(void)
{
    struct minifs_stat status;
    struct minifs_dirent entry;
    uint32_t offset = 0U;
    uint32_t count = 0U;
    int32_t result;

    if (minifs_lookup("/p6-expand", &status) != 0 ||
        status.mode != MINIFS_MODE_DIRECTORY ||
        status.size <= MINIFS_BLOCK_SIZE) {
        return false;
    }
    while ((result = minifs_readdir(status.inode, &offset, &entry)) == 1) {
        ++count;
    }
    return result == 0 && count == MINIFS_EXPANSION_FILE_COUNT + 2U;
}

static bool create_expansion_directory(void)
{
    struct minifs_stat status;
    char path[32];
    uint32_t index;

    if (minifs_mkdir("/p6-expand") != 0) {
        return false;
    }
    for (index = 0U; index < MINIFS_EXPANSION_FILE_COUNT; ++index) {
        expansion_file_path(index, path);
        if (minifs_create(path, &status) != 0) {
            return false;
        }
    }
    return verify_expansion_directory();
}

static bool remove_expansion_directory(void)
{
    struct minifs_stat status;
    struct minifs_dirent entry;
    char path[32];
    uint32_t index;
    uint32_t offset = 0U;
    uint32_t count = 0U;
    int32_t result;

    if (!verify_expansion_directory()) {
        return false;
    }
    for (index = 0U; index < MINIFS_EXPANSION_FILE_COUNT; ++index) {
        expansion_file_path(index, path);
        if (minifs_unlink(path) != 0) {
            return false;
        }
    }
    if (minifs_lookup("/p6-expand", &status) != 0) {
        return false;
    }
    while ((result = minifs_readdir(status.inode, &offset, &entry)) == 1) {
        ++count;
    }
    return result == 0 && count == 2U &&
        minifs_unlink("/p6-expand") == 0 &&
        minifs_lookup("/p6-expand", &status) == -MINIOS_ENOENT;
}

enum minifs_persistence_result minifs_persistence_self_test(void)
{
    const uint32_t full_size =
        (MINIFS_DIRECT_COUNT + 1U) * MINIFS_BLOCK_SIZE + 123U;
    const uint32_t truncated_size = MINIFS_BLOCK_SIZE + 17U;
    struct minifs_stat status;
    int32_t lookup = minifs_lookup("/p6-persist", &status);

    if (lookup == -MINIOS_ENOENT) {
        uint32_t offset = 0U;

        if (minifs_create("/p6-persist", &status) != 0) {
            return MINIFS_PERSISTENCE_FAILED;
        }
        while (offset < full_size) {
            size_t chunk = (size_t)(full_size - offset);
            size_t index;

            if (chunk > sizeof(compare_buffer)) {
                chunk = sizeof(compare_buffer);
            }
            for (index = 0U; index < chunk; ++index) {
                compare_buffer[index] =
                    persistence_pattern(offset + (uint32_t)index);
            }
            if (minifs_write(status.inode, offset,
                             compare_buffer, chunk) != (int32_t)chunk) {
                return MINIFS_PERSISTENCE_FAILED;
            }
            offset += (uint32_t)chunk;
        }
        if (minifs_lookup("/p6-persist", &status) != 0 ||
            status.size != full_size || !verify_persistence_file(&status) ||
            !create_expansion_directory()) {
            return MINIFS_PERSISTENCE_FAILED;
        }
        return MINIFS_PERSISTENCE_CREATED;
    }
    if (lookup != 0 ||
        (status.size != full_size && status.size != truncated_size) ||
        !verify_persistence_file(&status) ||
        !remove_expansion_directory()) {
        return MINIFS_PERSISTENCE_FAILED;
    }
    if (status.size == full_size &&
        minifs_truncate(status.inode, truncated_size) != 0) {
        return MINIFS_PERSISTENCE_FAILED;
    }
    if (minifs_lookup("/p6-persist", &status) != 0 ||
        status.size != truncated_size || !verify_persistence_file(&status)) {
        return MINIFS_PERSISTENCE_FAILED;
    }
    return MINIFS_PERSISTENCE_VERIFIED_AND_TRUNCATED;
}
