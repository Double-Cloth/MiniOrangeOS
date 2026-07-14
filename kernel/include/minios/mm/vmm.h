#ifndef MINIOS_MM_VMM_H
#define MINIOS_MM_VMM_H

#include <minios/boot_info.h>

#include <stdbool.h>
#include <stdint.h>

#define VMM_WRITABLE 0x02U
#define VMM_USER 0x04U

void vmm_init(const struct boot_info *boot_info);
uint32_t vmm_kernel_page_directory(void);
uint32_t vmm_current_page_directory(void);
bool vmm_activate_page_directory(uint32_t physical_address);
bool vmm_activate_kernel_address_space(void);
bool vmm_map(uint32_t virtual_address, uint32_t physical_address, uint32_t flags);
bool vmm_unmap(uint32_t virtual_address, uint32_t *physical_address);
bool vmm_query(uint32_t virtual_address, uint32_t *physical_address, uint32_t *flags);
bool vmm_self_test(void);

#endif
