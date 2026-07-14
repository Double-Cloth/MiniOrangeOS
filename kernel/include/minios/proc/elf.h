#ifndef MINIOS_PROC_ELF_H
#define MINIOS_PROC_ELF_H

#include <minios/mm/address_space.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

int32_t elf_load_image(struct vmm_address_space *space,
                       const uint8_t *image, size_t image_size,
                       uint32_t *entry_point);
bool elf_loader_validation_self_test(const uint8_t *image,
                                     size_t image_size);

#endif
