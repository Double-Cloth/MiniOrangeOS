#include <minios/arch/x86/io.h>
#include <minios/arch/x86/irq.h>
#include <minios/drivers/ata.h>
#include <minios/errno.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATA_DATA_PORT 0x01F0U
#define ATA_SECTOR_COUNT_PORT 0x01F2U
#define ATA_LBA_LOW_PORT 0x01F3U
#define ATA_LBA_MID_PORT 0x01F4U
#define ATA_LBA_HIGH_PORT 0x01F5U
#define ATA_DRIVE_PORT 0x01F6U
#define ATA_STATUS_COMMAND_PORT 0x01F7U
#define ATA_ALT_STATUS_PORT 0x03F6U
#define ATA_COMMAND_READ_SECTORS 0x20U
#define ATA_COMMAND_WRITE_SECTORS 0x30U
#define ATA_COMMAND_CACHE_FLUSH 0xE7U
#define ATA_COMMAND_IDENTIFY 0xECU
#define ATA_STATUS_ERROR 0x01U
#define ATA_STATUS_DRQ 0x08U
#define ATA_STATUS_DEVICE_FAULT 0x20U
#define ATA_STATUS_BUSY 0x80U
#define ATA_DRIVE_MASTER 0xE0U
#define ATA_IDENTIFY_MASTER 0xA0U
#define ATA_POLL_LIMIT 0x00100000U
#define ATA_WORDS_PER_SECTOR 256U
#define ATA_MAX_COMMAND_SECTORS 255U
#define ATA_LBA28_MAX 0x0FFFFFFFU
#define ATA_IDENTIFY_CAPABILITIES 49U
#define ATA_CAPABILITY_LBA 0x0200U
#define ATA_IDENTIFY_CAPACITY_LOW 60U
#define ATA_IDENTIFY_CAPACITY_HIGH 61U

static uint32_t device_sector_count;
static bool device_ready;
static bool operation_busy;

static void ata_delay_400ns(void)
{
    (void)io_in8(ATA_ALT_STATUS_PORT);
    (void)io_in8(ATA_ALT_STATUS_PORT);
    (void)io_in8(ATA_ALT_STATUS_PORT);
    (void)io_in8(ATA_ALT_STATUS_PORT);
}

static bool ata_wait(bool require_drq)
{
    uint32_t remaining = ATA_POLL_LIMIT;

    while (remaining > 0U) {
        uint8_t status = io_in8(ATA_STATUS_COMMAND_PORT);

        if (status == 0U) {
            return false;
        }
        if ((status & ATA_STATUS_BUSY) == 0U) {
            if ((status & (ATA_STATUS_ERROR | ATA_STATUS_DEVICE_FAULT)) !=
                0U) {
                return false;
            }
            if (!require_drq || (status & ATA_STATUS_DRQ) != 0U) {
                return true;
            }
        }
        --remaining;
    }
    return false;
}

static bool ata_acquire(uint32_t *irq_flags)
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

static void ata_release(uint32_t irq_flags)
{
    operation_busy = false;
    irq_restore(irq_flags);
}

static bool ata_request_valid(uint32_t lba, uint32_t count,
                              const void *buffer)
{
    return device_ready && buffer != NULL && count > 0U &&
        count <= ATA_MAX_COMMAND_SECTORS && lba <= ATA_LBA28_MAX &&
        count <= device_sector_count && lba <= device_sector_count - count &&
        count - 1U <= ATA_LBA28_MAX - lba;
}

static void ata_issue_lba28(uint32_t lba, uint32_t count, uint8_t command)
{
    io_out8(ATA_DRIVE_PORT,
            (uint8_t)(ATA_DRIVE_MASTER | ((lba >> 24U) & 0x0FU)));
    ata_delay_400ns();
    io_out8(ATA_SECTOR_COUNT_PORT, (uint8_t)count);
    io_out8(ATA_LBA_LOW_PORT, (uint8_t)lba);
    io_out8(ATA_LBA_MID_PORT, (uint8_t)(lba >> 8U));
    io_out8(ATA_LBA_HIGH_PORT, (uint8_t)(lba >> 16U));
    io_out8(ATA_STATUS_COMMAND_PORT, command);
    ata_delay_400ns();
}

int32_t ata_init(void)
{
    uint16_t identify[ATA_WORDS_PER_SECTOR];
    uint32_t irq_flags;
    size_t index;

    device_ready = false;
    device_sector_count = 0U;
    operation_busy = false;
    if (!ata_acquire(&irq_flags)) {
        return -MINIOS_EIO;
    }
    io_out8(ATA_DRIVE_PORT, ATA_IDENTIFY_MASTER);
    ata_delay_400ns();
    io_out8(ATA_SECTOR_COUNT_PORT, 0U);
    io_out8(ATA_LBA_LOW_PORT, 0U);
    io_out8(ATA_LBA_MID_PORT, 0U);
    io_out8(ATA_LBA_HIGH_PORT, 0U);
    io_out8(ATA_STATUS_COMMAND_PORT, ATA_COMMAND_IDENTIFY);
    ata_delay_400ns();
    if (!ata_wait(true)) {
        ata_release(irq_flags);
        return -MINIOS_EIO;
    }
    for (index = 0U; index < ATA_WORDS_PER_SECTOR; ++index) {
        identify[index] = io_in16(ATA_DATA_PORT);
    }
    device_sector_count = (uint32_t)identify[ATA_IDENTIFY_CAPACITY_LOW] |
        ((uint32_t)identify[ATA_IDENTIFY_CAPACITY_HIGH] << 16U);
    if ((identify[ATA_IDENTIFY_CAPABILITIES] & ATA_CAPABILITY_LBA) == 0U ||
        device_sector_count == 0U) {
        ata_release(irq_flags);
        return -MINIOS_EIO;
    }
    if (device_sector_count > ATA_LBA28_MAX + 1U) {
        device_sector_count = ATA_LBA28_MAX + 1U;
    }
    device_ready = true;
    ata_release(irq_flags);
    return 0;
}

uint32_t ata_sector_count(void)
{
    return device_ready ? device_sector_count : 0U;
}

int32_t ata_read_sectors(uint32_t lba, uint32_t count, void *buffer)
{
    uint8_t *bytes = (uint8_t *)buffer;
    uint32_t irq_flags;
    uint32_t sector;

    if (!ata_request_valid(lba, count, buffer)) {
        return -MINIOS_EINVAL;
    }
    if (!ata_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    if (!ata_wait(false)) {
        ata_release(irq_flags);
        return -MINIOS_EIO;
    }
    ata_issue_lba28(lba, count, ATA_COMMAND_READ_SECTORS);
    for (sector = 0U; sector < count; ++sector) {
        uint32_t word;

        if (!ata_wait(true)) {
            ata_release(irq_flags);
            return -MINIOS_EIO;
        }
        for (word = 0U; word < ATA_WORDS_PER_SECTOR; ++word) {
            uint16_t value = io_in16(ATA_DATA_PORT);
            size_t offset = ((size_t)sector * ATA_WORDS_PER_SECTOR + word) * 2U;

            bytes[offset] = (uint8_t)value;
            bytes[offset + 1U] = (uint8_t)(value >> 8U);
        }
    }
    ata_release(irq_flags);
    return 0;
}

int32_t ata_write_sectors(uint32_t lba, uint32_t count,
                          const void *buffer)
{
    const uint8_t *bytes = (const uint8_t *)buffer;
    uint32_t irq_flags;
    uint32_t sector;

    if (!ata_request_valid(lba, count, buffer)) {
        return -MINIOS_EINVAL;
    }
    if (!ata_acquire(&irq_flags)) {
        return -MINIOS_EAGAIN;
    }
    if (!ata_wait(false)) {
        ata_release(irq_flags);
        return -MINIOS_EIO;
    }
    ata_issue_lba28(lba, count, ATA_COMMAND_WRITE_SECTORS);
    for (sector = 0U; sector < count; ++sector) {
        uint32_t word;

        if (!ata_wait(true)) {
            ata_release(irq_flags);
            return -MINIOS_EIO;
        }
        for (word = 0U; word < ATA_WORDS_PER_SECTOR; ++word) {
            size_t offset = ((size_t)sector * ATA_WORDS_PER_SECTOR + word) * 2U;
            uint16_t value = (uint16_t)bytes[offset] |
                ((uint16_t)bytes[offset + 1U] << 8U);

            io_out16(ATA_DATA_PORT, value);
        }
    }
    if (!ata_wait(false)) {
        ata_release(irq_flags);
        return -MINIOS_EIO;
    }
    io_out8(ATA_STATUS_COMMAND_PORT, ATA_COMMAND_CACHE_FLUSH);
    ata_delay_400ns();
    if (!ata_wait(false)) {
        ata_release(irq_flags);
        return -MINIOS_EIO;
    }
    ata_release(irq_flags);
    return 0;
}
