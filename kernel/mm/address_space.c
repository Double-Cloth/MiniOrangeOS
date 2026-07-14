#include <minios/mm/address_space.h>
#include <minios/mm/pmm.h>
#include <minios/mm/vmm.h>
#include <minios/panic.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PAGE_SIZE 4096U
#define PAGE_MASK 0xFFFFF000U
#define PAGE_ENTRY_COUNT 1024U
#define KERNEL_BASE 0xC0000000U
#define KERNEL_PDE_INDEX 768U
#define RECURSIVE_PDE_INDEX 1023U
#define CURRENT_PAGE_DIRECTORY 0xFFFFF000U
#define ADDRESS_SPACE_DIRECTORY_WINDOW 0xD0800000U
#define ADDRESS_SPACE_TABLE_WINDOW 0xD0801000U
#define ADDRESS_SPACE_WINDOW_PDE (ADDRESS_SPACE_DIRECTORY_WINDOW >> 22U)
#define PAGE_PRESENT 0x01U
#define PAGE_WRITABLE VMM_WRITABLE
#define PAGE_USER VMM_USER
#define ADDRESS_SPACE_TEST_VIRTUAL 0x00400000U

static bool address_space_window_busy;

static bool valid_space(const struct vmm_address_space *space)
{
    return space != NULL && space->page_directory_physical != 0U &&
           (space->page_directory_physical & (PAGE_SIZE - 1U)) == 0U;
}

static bool acquire_window(void)
{
    if (address_space_window_busy) {
        return false;
    }
    address_space_window_busy = true;
    return true;
}

static void release_window(void)
{
    address_space_window_busy = false;
}

static bool map_window(uint32_t virtual_address, uint32_t physical_address)
{
    return vmm_map(virtual_address, physical_address, VMM_WRITABLE);
}

static void unmap_window(uint32_t virtual_address, uint32_t expected_physical)
{
    uint32_t physical = 0U;

    if (!vmm_unmap(virtual_address, &physical) ||
        physical != expected_physical) {
        panic("address-space window invariant failed");
    }
}

static void zero_page(volatile uint32_t *page)
{
    uint32_t index;

    for (index = 0U; index < PAGE_ENTRY_COUNT; ++index) {
        page[index] = 0U;
    }
}

bool vmm_address_space_create(struct vmm_address_space *space)
{
    volatile uint32_t *directory =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_DIRECTORY_WINDOW;
    volatile uint32_t *current =
        (volatile uint32_t *)(uintptr_t)CURRENT_PAGE_DIRECTORY;
    uint32_t physical;
    uint32_t index;

    if (space == NULL || space->page_directory_physical != 0U ||
        !acquire_window()) {
        return false;
    }
    physical = pmm_alloc();
    if (physical == 0U) {
        release_window();
        return false;
    }
    if (!map_window(ADDRESS_SPACE_DIRECTORY_WINDOW, physical)) {
        if (!pmm_free(physical)) {
            panic("address-space directory rollback failed");
        }
        release_window();
        return false;
    }
    zero_page(directory);
    for (index = KERNEL_PDE_INDEX; index < RECURSIVE_PDE_INDEX; ++index) {
        if (index != ADDRESS_SPACE_WINDOW_PDE) {
            directory[index] = current[index];
        }
    }
    directory[RECURSIVE_PDE_INDEX] =
        physical | PAGE_PRESENT | PAGE_WRITABLE;
    unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW, physical);
    space->page_directory_physical = physical;
    release_window();
    return true;
}

bool vmm_address_space_map(struct vmm_address_space *space,
                           uint32_t virtual_address,
                           uint32_t physical_address,
                           uint32_t flags)
{
    volatile uint32_t *directory =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_DIRECTORY_WINDOW;
    volatile uint32_t *table =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_TABLE_WINDOW;
    uint32_t directory_index;
    uint32_t table_index;
    uint32_t table_physical;
    bool new_table = false;

    if (!valid_space(space) || virtual_address >= KERNEL_BASE ||
        (virtual_address & (PAGE_SIZE - 1U)) != 0U ||
        (physical_address & (PAGE_SIZE - 1U)) != 0U ||
        physical_address == 0U || !acquire_window()) {
        return false;
    }
    if (!map_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                    space->page_directory_physical)) {
        release_window();
        return false;
    }
    directory_index = virtual_address >> 22U;
    table_index = (virtual_address >> 12U) & 0x3FFU;
    if ((directory[directory_index] & PAGE_PRESENT) == 0U) {
        table_physical = pmm_alloc();
        if (table_physical == 0U) {
            unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                         space->page_directory_physical);
            release_window();
            return false;
        }
        new_table = true;
    } else {
        table_physical = directory[directory_index] & PAGE_MASK;
    }
    if (!map_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical)) {
        if (new_table && !pmm_free(table_physical)) {
            panic("address-space page-table rollback failed");
        }
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        release_window();
        return false;
    }
    if (new_table) {
        zero_page(table);
        directory[directory_index] =
            table_physical | PAGE_PRESENT | PAGE_WRITABLE | PAGE_USER;
    }
    if ((table[table_index] & PAGE_PRESENT) != 0U) {
        if (new_table) {
            directory[directory_index] = 0U;
        }
        unmap_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical);
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        if (new_table && !pmm_free(table_physical)) {
            panic("address-space empty table rollback failed");
        }
        release_window();
        return false;
    }
    table[table_index] = physical_address | PAGE_PRESENT | PAGE_USER |
        (flags & PAGE_WRITABLE);
    unmap_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical);
    unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                 space->page_directory_physical);
    release_window();
    return true;
}

bool vmm_address_space_unmap(struct vmm_address_space *space,
                             uint32_t virtual_address,
                             uint32_t *physical_address)
{
    volatile uint32_t *directory =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_DIRECTORY_WINDOW;
    volatile uint32_t *table =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_TABLE_WINDOW;
    uint32_t directory_index;
    uint32_t table_index;
    uint32_t table_physical;
    uint32_t entry;
    uint32_t index;
    bool empty = true;

    if (!valid_space(space) || virtual_address >= KERNEL_BASE ||
        (virtual_address & (PAGE_SIZE - 1U)) != 0U || !acquire_window()) {
        return false;
    }
    if (!map_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                    space->page_directory_physical)) {
        release_window();
        return false;
    }
    directory_index = virtual_address >> 22U;
    table_index = (virtual_address >> 12U) & 0x3FFU;
    if ((directory[directory_index] & PAGE_PRESENT) == 0U) {
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        release_window();
        return false;
    }
    table_physical = directory[directory_index] & PAGE_MASK;
    if (!map_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical)) {
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        release_window();
        return false;
    }
    entry = table[table_index];
    if ((entry & PAGE_PRESENT) == 0U) {
        unmap_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical);
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        release_window();
        return false;
    }
    table[table_index] = 0U;
    for (index = 0U; index < PAGE_ENTRY_COUNT; ++index) {
        if ((table[index] & PAGE_PRESENT) != 0U) {
            empty = false;
            break;
        }
    }
    if (physical_address != NULL) {
        *physical_address = entry & PAGE_MASK;
    }
    unmap_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical);
    if (empty) {
        directory[directory_index] = 0U;
        if (!pmm_free(table_physical)) {
            panic("address-space could not release empty page table");
        }
    }
    unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                 space->page_directory_physical);
    release_window();
    return true;
}

bool vmm_address_space_query(const struct vmm_address_space *space,
                             uint32_t virtual_address,
                             uint32_t *physical_address,
                             uint32_t *flags)
{
    volatile uint32_t *directory =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_DIRECTORY_WINDOW;
    volatile uint32_t *table =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_TABLE_WINDOW;
    uint32_t directory_index;
    uint32_t table_index;
    uint32_t table_physical;
    uint32_t entry;

    if (!valid_space(space) || virtual_address >= KERNEL_BASE ||
        !acquire_window()) {
        return false;
    }
    if (!map_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                    space->page_directory_physical)) {
        release_window();
        return false;
    }
    directory_index = virtual_address >> 22U;
    table_index = (virtual_address >> 12U) & 0x3FFU;
    if ((directory[directory_index] & PAGE_PRESENT) == 0U) {
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        release_window();
        return false;
    }
    table_physical = directory[directory_index] & PAGE_MASK;
    if (!map_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical)) {
        unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                     space->page_directory_physical);
        release_window();
        return false;
    }
    entry = table[table_index];
    if ((entry & PAGE_PRESENT) != 0U) {
        if (physical_address != NULL) {
            *physical_address = (entry & PAGE_MASK) |
                (virtual_address & (PAGE_SIZE - 1U));
        }
        if (flags != NULL) {
            *flags = entry & (PAGE_WRITABLE | PAGE_USER);
            if ((directory[directory_index] & PAGE_WRITABLE) == 0U) {
                *flags &= ~PAGE_WRITABLE;
            }
            if ((directory[directory_index] & PAGE_USER) == 0U) {
                *flags &= ~PAGE_USER;
            }
        }
    }
    unmap_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical);
    unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                 space->page_directory_physical);
    release_window();
    return (entry & PAGE_PRESENT) != 0U;
}

bool vmm_address_space_destroy(struct vmm_address_space *space)
{
    volatile uint32_t *directory =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_DIRECTORY_WINDOW;
    volatile uint32_t *table =
        (volatile uint32_t *)(uintptr_t)ADDRESS_SPACE_TABLE_WINDOW;
    uint32_t directory_index;

    if (!valid_space(space) || !acquire_window()) {
        return false;
    }
    if (!map_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                    space->page_directory_physical)) {
        release_window();
        return false;
    }
    for (directory_index = 0U; directory_index < KERNEL_PDE_INDEX;
         ++directory_index) {
        uint32_t table_physical;
        uint32_t table_index;

        if ((directory[directory_index] & PAGE_PRESENT) == 0U) {
            continue;
        }
        table_physical = directory[directory_index] & PAGE_MASK;
        if (!map_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical)) {
            panic("address-space destroy could not map page table");
        }
        for (table_index = 0U; table_index < PAGE_ENTRY_COUNT;
             ++table_index) {
            if ((table[table_index] & PAGE_PRESENT) != 0U) {
                uint32_t physical = table[table_index] & PAGE_MASK;
                table[table_index] = 0U;
                if (!pmm_free(physical)) {
                    panic("address-space destroy found invalid user page");
                }
            }
        }
        unmap_window(ADDRESS_SPACE_TABLE_WINDOW, table_physical);
        directory[directory_index] = 0U;
        if (!pmm_free(table_physical)) {
            panic("address-space destroy found invalid page table");
        }
    }
    unmap_window(ADDRESS_SPACE_DIRECTORY_WINDOW,
                 space->page_directory_physical);
    if (!pmm_free(space->page_directory_physical)) {
        panic("address-space destroy found invalid directory");
    }
    space->page_directory_physical = 0U;
    release_window();
    return true;
}

bool vmm_address_space_self_test(void)
{
    struct pmm_stats before = pmm_get_stats();
    struct vmm_address_space space = {0U};
    uint32_t first = 0U;
    uint32_t second = 0U;
    uint32_t queried = 0U;
    uint32_t flags = 0U;
    uint32_t unmapped = 0U;

    if (!vmm_address_space_create(&space)) {
        return false;
    }
    first = pmm_alloc();
    second = pmm_alloc();
    if (first == 0U || second == 0U ||
        !vmm_address_space_map(&space, ADDRESS_SPACE_TEST_VIRTUAL,
                               first, VMM_WRITABLE) ||
        !vmm_address_space_map(&space,
                               ADDRESS_SPACE_TEST_VIRTUAL + PAGE_SIZE,
                               second, 0U) ||
        vmm_address_space_map(&space, ADDRESS_SPACE_TEST_VIRTUAL,
                              first, VMM_WRITABLE) ||
        !vmm_address_space_query(&space,
                                 ADDRESS_SPACE_TEST_VIRTUAL + 17U,
                                 &queried, &flags) ||
        queried != first + 17U ||
        flags != (VMM_USER | VMM_WRITABLE) ||
        vmm_address_space_map(&space, KERNEL_BASE, first, VMM_WRITABLE) ||
        !vmm_address_space_unmap(&space, ADDRESS_SPACE_TEST_VIRTUAL,
                                 &unmapped) ||
        unmapped != first || !pmm_free(first) ||
        !vmm_address_space_destroy(&space)) {
        return false;
    }
    return pmm_get_stats().free_pages == before.free_pages;
}
