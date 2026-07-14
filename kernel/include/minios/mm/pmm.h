#ifndef MINIOS_MM_PMM_H
#define MINIOS_MM_PMM_H

#include <minios/boot_info.h>

#include <stdbool.h>
#include <stdint.h>

struct pmm_stats {
    uint32_t total_pages;
    uint32_t free_pages;
    uint32_t reserved_pages;
};

void pmm_init(const struct boot_info *boot_info);
uint32_t pmm_alloc(void);
bool pmm_free(uint32_t physical_address);
struct pmm_stats pmm_get_stats(void);
bool pmm_self_test(void);

#endif
