#ifndef MINIOS_BOOT_INFO_H
#define MINIOS_BOOT_INFO_H

#include <stddef.h>
#include <stdint.h>

#define BOOT_INFO_MAGIC 0x534F494DU
#define BOOT_INFO_VERSION 1U
#define BOOT_INFO_MAX_E820_ENTRIES 128U

struct e820_entry {
    uint64_t base;
    uint64_t length;
    uint32_t type;
    uint32_t attributes;
} __attribute__((packed));

struct boot_info {
    uint32_t magic;
    uint32_t version;
    uint32_t size;
    uint32_t checksum;
    uint32_t boot_drive;
    uint32_t kernel_entry;
    uint32_t kernel_physical_entry;
    uint32_t kernel_physical_start;
    uint32_t kernel_physical_end;
    uint32_t e820_count;
    uint32_t e820_address;
    uint32_t loader_start;
    uint32_t loader_end;
    uint32_t kernel_lba;
    uint32_t kernel_sectors;
    uint32_t reserved;
} __attribute__((packed));

_Static_assert(sizeof(struct e820_entry) == 24U, "E820 entry 必须为 24 bytes");
_Static_assert(sizeof(struct boot_info) == 64U, "Boot Info 必须为 64 bytes");
_Static_assert(offsetof(struct boot_info, kernel_physical_start) == 28U,
               "Boot Info kernel start offset 不匹配");
_Static_assert(offsetof(struct boot_info, e820_count) == 36U,
               "Boot Info E820 count offset 不匹配");
_Static_assert(offsetof(struct boot_info, loader_start) == 44U,
               "Boot Info loader offset 不匹配");

#endif
