#ifndef MINIOS_DRIVERS_ATA_H
#define MINIOS_DRIVERS_ATA_H

#include <stdint.h>

int32_t ata_init(void);
uint32_t ata_sector_count(void);
int32_t ata_read_sectors(uint32_t lba, uint32_t count, void *buffer);
int32_t ata_write_sectors(uint32_t lba, uint32_t count,
                          const void *buffer);

#endif
