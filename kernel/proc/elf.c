#include <minios/errno.h>
#include <minios/mm/address_space.h>
#include <minios/mm/pmm.h>
#include <minios/mm/vmm.h>
#include <minios/panic.h>
#include <minios/proc/elf.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ELF_IDENT_SIZE 16U
#define ELF_CLASS_32 1U
#define ELF_DATA_LITTLE_ENDIAN 1U
#define ELF_VERSION_CURRENT 1U
#define ELF_TYPE_EXECUTABLE 2U
#define ELF_MACHINE_I386 3U
#define ELF_PROGRAM_LOAD 1U
#define ELF_PROGRAM_EXECUTABLE 0x01U
#define ELF_PROGRAM_WRITABLE 0x02U
#define ELF_PROGRAM_READABLE 0x04U
#define ELF_PROGRAM_FLAGS 0x07U
#define ELF_PROGRAM_LIMIT 32U
#define PAGE_SIZE 4096U
#define PAGE_MASK 0xFFFFF000U
#define KERNEL_BASE 0xC0000000U
#define ELF_LOAD_WINDOW 0xD0C00000U
#define ELF_SELF_TEST_BYTES \
    (sizeof(struct elf_header) + sizeof(struct elf_program_header))

struct elf_header {
    uint8_t ident[ELF_IDENT_SIZE];
    uint16_t type;
    uint16_t machine;
    uint32_t version;
    uint32_t entry;
    uint32_t program_offset;
    uint32_t section_offset;
    uint32_t flags;
    uint16_t header_size;
    uint16_t program_entry_size;
    uint16_t program_count;
    uint16_t section_entry_size;
    uint16_t section_count;
    uint16_t section_name_index;
} __attribute__((packed));

struct elf_program_header {
    uint32_t type;
    uint32_t file_offset;
    uint32_t virtual_address;
    uint32_t physical_address;
    uint32_t file_size;
    uint32_t memory_size;
    uint32_t flags;
    uint32_t alignment;
} __attribute__((packed));

_Static_assert(sizeof(struct elf_header) == 52U, "ELF32 header size");
_Static_assert(sizeof(struct elf_program_header) == 32U,
               "ELF32 program header size");

static bool range_within(size_t limit, size_t offset, size_t length)
{
    return offset <= limit && length <= limit - offset;
}

static const struct elf_program_header *program_header_at(
    const uint8_t *image, const struct elf_header *header, uint16_t index)
{
    size_t offset = (size_t)header->program_offset +
        (size_t)index * sizeof(struct elf_program_header);

    return (const struct elf_program_header *)(const void *)&image[offset];
}

static bool program_range_valid(const struct elf_program_header *program,
                                size_t image_size)
{
    uint32_t memory_end;

    if (program->type != ELF_PROGRAM_LOAD) {
        return true;
    }
    if (program->memory_size == 0U) {
        return program->file_size == 0U;
    }
    if (program->file_size > program->memory_size ||
        !range_within(image_size, (size_t)program->file_offset,
                      (size_t)program->file_size) ||
        program->virtual_address < PAGE_SIZE ||
        program->virtual_address >= KERNEL_BASE ||
        program->memory_size > KERNEL_BASE - program->virtual_address ||
        (program->flags & ~ELF_PROGRAM_FLAGS) != 0U) {
        return false;
    }
    memory_end = program->virtual_address + program->memory_size;
    if (memory_end > KERNEL_BASE ||
        (program->flags & (ELF_PROGRAM_READABLE | ELF_PROGRAM_EXECUTABLE)) ==
            0U) {
        return false;
    }
    if (program->alignment > 1U &&
        ((program->alignment & (program->alignment - 1U)) != 0U ||
         ((program->virtual_address - program->file_offset) &
          (program->alignment - 1U)) != 0U)) {
        return false;
    }
    return true;
}

static bool load_ranges_overlap(const struct elf_program_header *left,
                                const struct elf_program_header *right)
{
    uint32_t left_end;
    uint32_t right_end;

    if (left->type != ELF_PROGRAM_LOAD || right->type != ELF_PROGRAM_LOAD) {
        return false;
    }
    left_end = left->virtual_address + left->memory_size;
    right_end = right->virtual_address + right->memory_size;
    return left->virtual_address < right_end &&
        right->virtual_address < left_end;
}

static bool validate_image(const uint8_t *image, size_t image_size,
                           uint32_t *entry_point)
{
    const struct elf_header *header;
    uint16_t index;
    bool has_load = false;
    bool entry_is_executable = false;

    if (image == NULL || entry_point == NULL ||
        image_size < sizeof(struct elf_header)) {
        return false;
    }
    header = (const struct elf_header *)(const void *)image;
    if (header->ident[0] != 0x7FU || header->ident[1] != 'E' ||
        header->ident[2] != 'L' || header->ident[3] != 'F' ||
        header->ident[4] != ELF_CLASS_32 ||
        header->ident[5] != ELF_DATA_LITTLE_ENDIAN ||
        header->ident[6] != ELF_VERSION_CURRENT ||
        header->type != ELF_TYPE_EXECUTABLE ||
        header->machine != ELF_MACHINE_I386 ||
        header->version != ELF_VERSION_CURRENT ||
        header->header_size != sizeof(struct elf_header) ||
        header->program_entry_size != sizeof(struct elf_program_header) ||
        header->program_count == 0U ||
        header->program_count > ELF_PROGRAM_LIMIT ||
        !range_within(image_size, (size_t)header->program_offset,
                      (size_t)header->program_count *
                          sizeof(struct elf_program_header))) {
        return false;
    }
    for (index = 0U; index < header->program_count; ++index) {
        const struct elf_program_header *program =
            program_header_at(image, header, index);
        uint16_t previous;

        if (!program_range_valid(program, image_size)) {
            return false;
        }
        if (program->type != ELF_PROGRAM_LOAD) {
            continue;
        }
        if (program->memory_size == 0U) {
            continue;
        }
        has_load = true;
        if ((program->flags & ELF_PROGRAM_EXECUTABLE) != 0U &&
            header->entry >= program->virtual_address &&
            header->entry - program->virtual_address < program->memory_size) {
            entry_is_executable = true;
        }
        for (previous = 0U; previous < index; ++previous) {
            if (load_ranges_overlap(
                    program, program_header_at(image, header, previous))) {
                return false;
            }
        }
    }
    if (!has_load || !entry_is_executable) {
        return false;
    }
    *entry_point = header->entry;
    return true;
}

static bool zero_physical_page(uint32_t physical_address)
{
    volatile uint8_t *page =
        (volatile uint8_t *)(uintptr_t)ELF_LOAD_WINDOW;
    uint32_t unmapped = 0U;
    size_t index;

    if (!vmm_map(ELF_LOAD_WINDOW, physical_address, VMM_WRITABLE)) {
        return false;
    }
    for (index = 0U; index < PAGE_SIZE; ++index) {
        page[index] = 0U;
    }
    if (!vmm_unmap(ELF_LOAD_WINDOW, &unmapped) ||
        unmapped != physical_address) {
        panic("ELF load window invariant failed");
    }
    return true;
}

static int32_t ensure_user_page(struct vmm_address_space *space,
                                uint32_t virtual_address, bool writable,
                                uint32_t *physical_address)
{
    uint32_t physical = 0U;
    uint32_t flags = 0U;

    if (vmm_address_space_query(space, virtual_address, &physical, &flags)) {
        if (writable && (flags & VMM_WRITABLE) == 0U &&
            !vmm_address_space_protect(space, virtual_address, VMM_WRITABLE)) {
            return -MINIOS_EIO;
        }
        *physical_address = physical & PAGE_MASK;
        return 0;
    }
    physical = pmm_alloc();
    if (physical == 0U) {
        return -MINIOS_ENOMEM;
    }
    if (!zero_physical_page(physical) ||
        !vmm_address_space_map(space, virtual_address, physical,
                               writable ? VMM_WRITABLE : 0U)) {
        if (!pmm_free(physical)) {
            panic("ELF page rollback failed");
        }
        return -MINIOS_ENOMEM;
    }
    *physical_address = physical;
    return 0;
}

static bool copy_to_physical(uint32_t physical_address, size_t page_offset,
                             const uint8_t *source, size_t length)
{
    volatile uint8_t *page =
        (volatile uint8_t *)(uintptr_t)ELF_LOAD_WINDOW;
    uint32_t unmapped = 0U;
    size_t index;

    if (page_offset > PAGE_SIZE || length > PAGE_SIZE - page_offset ||
        !vmm_map(ELF_LOAD_WINDOW, physical_address, VMM_WRITABLE)) {
        return false;
    }
    for (index = 0U; index < length; ++index) {
        page[page_offset + index] = source[index];
    }
    if (!vmm_unmap(ELF_LOAD_WINDOW, &unmapped) ||
        unmapped != physical_address) {
        panic("ELF copy window invariant failed");
    }
    return true;
}

static int32_t load_program(struct vmm_address_space *space,
                            const uint8_t *image,
                            const struct elf_program_header *program)
{
    uint32_t first_page = program->virtual_address & PAGE_MASK;
    uint32_t last_page = (program->virtual_address +
                          program->memory_size - 1U) & PAGE_MASK;
    uint32_t page = first_page;
    uint32_t virtual_cursor = program->virtual_address;
    size_t file_cursor = (size_t)program->file_offset;
    uint32_t remaining = program->file_size;
    bool writable = (program->flags & ELF_PROGRAM_WRITABLE) != 0U;

    for (;;) {
        uint32_t physical;
        int32_t result = ensure_user_page(space, page, writable, &physical);

        if (result < 0) {
            return result;
        }
        if (page == last_page) {
            break;
        }
        page += PAGE_SIZE;
    }
    while (remaining != 0U) {
        uint32_t page_base = virtual_cursor & PAGE_MASK;
        size_t page_offset = (size_t)(virtual_cursor & (PAGE_SIZE - 1U));
        size_t chunk = PAGE_SIZE - page_offset;
        uint32_t physical = 0U;

        if (chunk > (size_t)remaining) {
            chunk = (size_t)remaining;
        }
        if (!vmm_address_space_query(space, page_base, &physical, NULL) ||
            !copy_to_physical(physical & PAGE_MASK, page_offset,
                              &image[file_cursor], chunk)) {
            return -MINIOS_EIO;
        }
        virtual_cursor += (uint32_t)chunk;
        file_cursor += chunk;
        remaining -= (uint32_t)chunk;
    }
    return 0;
}

int32_t elf_load_image(struct vmm_address_space *space,
                       const uint8_t *image, size_t image_size,
                       uint32_t *entry_point)
{
    const struct elf_header *header;
    uint32_t validated_entry;
    uint16_t index;

    if (space == NULL || space->page_directory_physical == 0U ||
        !validate_image(image, image_size, &validated_entry)) {
        return -MINIOS_ENOEXEC;
    }
    header = (const struct elf_header *)(const void *)image;
    for (index = 0U; index < header->program_count; ++index) {
        const struct elf_program_header *program =
            program_header_at(image, header, index);
        int32_t result;

        if (program->type != ELF_PROGRAM_LOAD ||
            program->memory_size == 0U) {
            continue;
        }
        result = load_program(space, image, program);
        if (result < 0) {
            return result;
        }
    }
    *entry_point = validated_entry;
    return 0;
}

bool elf_loader_validation_self_test(const uint8_t *image,
                                     size_t image_size)
{
    uint8_t malformed[ELF_SELF_TEST_BYTES];
    struct elf_header *header = (struct elf_header *)(void *)malformed;
    struct elf_program_header *program =
        (struct elf_program_header *)(void *)&malformed[sizeof(*header)];
    uint32_t entry = 0U;
    size_t index;

    if (!validate_image(image, image_size, &entry) ||
        image_size < sizeof(malformed)) {
        return false;
    }
    for (index = 0U; index < sizeof(malformed); ++index) {
        malformed[index] = image[index];
    }
    header->program_offset = sizeof(*header);
    header->program_count = 1U;
    header->entry = 0x00400000U;
    program->type = ELF_PROGRAM_LOAD;
    program->file_offset = 0U;
    program->virtual_address = header->entry;
    program->file_size = 0U;
    program->memory_size = PAGE_SIZE;
    program->flags = ELF_PROGRAM_READABLE | ELF_PROGRAM_EXECUTABLE;
    program->alignment = PAGE_SIZE;
    if (!validate_image(malformed, sizeof(malformed), &entry)) {
        return false;
    }
    header->type = 3U;
    if (validate_image(malformed, sizeof(malformed), &entry)) {
        return false;
    }
    header->type = ELF_TYPE_EXECUTABLE;
    program->memory_size = 0U;
    program->file_size = 1U;
    if (validate_image(malformed, sizeof(malformed), &entry)) {
        return false;
    }
    program->file_size = 0U;
    program->memory_size = PAGE_SIZE;
    program->virtual_address = KERNEL_BASE;
    header->entry = KERNEL_BASE;
    return !validate_image(malformed, sizeof(malformed), &entry);
}
