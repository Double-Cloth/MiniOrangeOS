#ifndef MINIOS_MM_ADDRESS_SPACE_H
#define MINIOS_MM_ADDRESS_SPACE_H

#include <stdbool.h>
#include <stdint.h>

struct vmm_address_space {
    uint32_t page_directory_physical;
};

bool vmm_address_space_create(struct vmm_address_space *space);
bool vmm_address_space_destroy(struct vmm_address_space *space);
bool vmm_address_space_map(struct vmm_address_space *space,
                           uint32_t virtual_address,
                           uint32_t physical_address,
                           uint32_t flags);
bool vmm_address_space_protect(struct vmm_address_space *space,
                               uint32_t virtual_address,
                               uint32_t flags);
bool vmm_address_space_unmap(struct vmm_address_space *space,
                             uint32_t virtual_address,
                             uint32_t *physical_address);
bool vmm_address_space_query(const struct vmm_address_space *space,
                             uint32_t virtual_address,
                             uint32_t *physical_address,
                             uint32_t *flags);
bool vmm_address_space_activate(struct vmm_address_space *space);
bool vmm_address_space_self_test(void);

#endif
