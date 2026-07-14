#include <minios/block/block.h>
#include <minios/drivers/ata.h>
#include <minios/errno.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SECTOR_SIZE 512U
#define SECTORS_PER_BLOCK 8U
#define KERNEL_ELF_BLOCK 16U

_Static_assert(BLOCK_SIZE == SECTOR_SIZE * SECTORS_PER_BLOCK,
               "block size must contain exactly eight ATA sectors");

static uint32_t device_block_count;
static uint8_t block_test_buffer[BLOCK_SIZE];

static bool block_request_valid(uint32_t block_number, uint32_t count,
                                const void *buffer)
{
    return device_block_count != 0U && buffer != NULL && count > 0U &&
        count <= SIZE_MAX / BLOCK_SIZE &&
        count <= device_block_count &&
        block_number <= device_block_count - count;
}

int32_t block_init(void)
{
    uint32_t sectors = ata_sector_count();

    if (sectors < SECTORS_PER_BLOCK) {
        device_block_count = 0U;
        return -MINIOS_EIO;
    }
    device_block_count = sectors / SECTORS_PER_BLOCK;
    return 0;
}

uint32_t block_count(void)
{
    return device_block_count;
}

int32_t block_read(uint32_t block_number, uint32_t count, void *buffer)
{
    uint8_t *bytes = (uint8_t *)buffer;
    uint32_t index;

    if (!block_request_valid(block_number, count, buffer)) {
        return -MINIOS_EINVAL;
    }
    for (index = 0U; index < count; ++index) {
        int32_t result = ata_read_sectors(
            (block_number + index) * SECTORS_PER_BLOCK,
            SECTORS_PER_BLOCK,
            &bytes[(size_t)index * BLOCK_SIZE]
        );

        if (result < 0) {
            return result;
        }
    }
    return 0;
}

int32_t block_write(uint32_t block_number, uint32_t count,
                    const void *buffer)
{
    const uint8_t *bytes = (const uint8_t *)buffer;
    uint32_t index;

    if (!block_request_valid(block_number, count, buffer)) {
        return -MINIOS_EINVAL;
    }
    for (index = 0U; index < count; ++index) {
        int32_t result = ata_write_sectors(
            (block_number + index) * SECTORS_PER_BLOCK,
            SECTORS_PER_BLOCK,
            &bytes[(size_t)index * BLOCK_SIZE]
        );

        if (result < 0) {
            return result;
        }
    }
    return 0;
}

bool block_self_test(void)
{
    if (device_block_count <= KERNEL_ELF_BLOCK ||
        block_read(0U, 1U, block_test_buffer) != 0 ||
        block_test_buffer[510U] != 0x55U ||
        block_test_buffer[511U] != 0xAAU ||
        block_read(KERNEL_ELF_BLOCK, 1U, block_test_buffer) != 0 ||
        block_test_buffer[0] != 0x7FU ||
        block_test_buffer[1] != 'E' || block_test_buffer[2] != 'L' ||
        block_test_buffer[3] != 'F' ||
        block_read(device_block_count, 1U, block_test_buffer) >= 0 ||
        block_read(UINT32_MAX, 1U, block_test_buffer) >= 0) {
        return false;
    }
    return true;
}
