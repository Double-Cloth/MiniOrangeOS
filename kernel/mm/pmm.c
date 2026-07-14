#include <minios/mm/pmm.h>
#include <minios/panic.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PAGE_SIZE 4096U
#define PAGE_SHIFT 12U
#define PMM_MAX_PAGES 1048576U
#define PMM_BITMAP_SIZE (PMM_MAX_PAGES / 8U)
#define E820_USABLE 1U
#define LOW_MEMORY_RESERVED_END 0x00100000U
#define FOUR_GIB 0x100000000ULL

static uint8_t used_bitmap[PMM_BITMAP_SIZE];
static uint8_t allocatable_bitmap[PMM_BITMAP_SIZE];
static uint32_t total_pages;
static uint32_t free_pages;
static uint32_t reserved_pages;

static bool bitmap_get(const uint8_t *bitmap, uint32_t page)
{
    return (bitmap[page >> 3U] & (uint8_t)(1U << (page & 7U))) != 0U;
}

static void bitmap_set(uint8_t *bitmap, uint32_t page, bool value)
{
    uint8_t mask = (uint8_t)(1U << (page & 7U));

    if (value) {
        bitmap[page >> 3U] |= mask;
    } else {
        bitmap[page >> 3U] &= (uint8_t)~mask;
    }
}

static bool range_to_pages(
    uint64_t base,
    uint64_t length,
    uint32_t *first_page,
    uint32_t *limit_page
)
{
    uint64_t end;
    uint64_t aligned_start;

    if (length == 0U || base >= FOUR_GIB) {
        return false;
    }
    end = base + length;
    if (end < base || end > FOUR_GIB) {
        end = FOUR_GIB;
    }
    if (base > FOUR_GIB - (PAGE_SIZE - 1U)) {
        return false;
    }
    aligned_start = (base + (PAGE_SIZE - 1U)) & ~((uint64_t)PAGE_SIZE - 1U);
    end &= ~((uint64_t)PAGE_SIZE - 1U);
    if (aligned_start >= end) {
        return false;
    }
    *first_page = (uint32_t)(aligned_start >> PAGE_SHIFT);
    *limit_page = (uint32_t)(end >> PAGE_SHIFT);
    return true;
}

static void make_range_allocatable(uint64_t base, uint64_t length)
{
    uint32_t first;
    uint32_t limit;
    uint32_t page;

    if (!range_to_pages(base, length, &first, &limit)) {
        return;
    }
    for (page = first; page < limit; ++page) {
        bitmap_set(allocatable_bitmap, page, true);
        bitmap_set(used_bitmap, page, false);
    }
}

static void reserve_range(uint64_t base, uint64_t length)
{
    uint64_t end;
    uint32_t first;
    uint32_t limit;
    uint32_t page;

    if (length == 0U || base >= FOUR_GIB) {
        return;
    }
    end = base + length;
    if (end < base || end > FOUR_GIB) {
        end = FOUR_GIB;
    }
    first = (uint32_t)(base >> PAGE_SHIFT);
    if (end == FOUR_GIB) {
        limit = PMM_MAX_PAGES;
    } else {
        limit = (uint32_t)((end + (PAGE_SIZE - 1U)) >> PAGE_SHIFT);
    }
    for (page = first; page < limit; ++page) {
        bitmap_set(allocatable_bitmap, page, false);
        bitmap_set(used_bitmap, page, true);
    }
}

void pmm_init(const struct boot_info *boot_info)
{
    const struct e820_entry *e820_entries;
    uint32_t index;
    uint32_t page;
    uint32_t maximum_page = 0U;

    if (boot_info == NULL || boot_info->magic != BOOT_INFO_MAGIC ||
        boot_info->version != BOOT_INFO_VERSION ||
        boot_info->size != sizeof(*boot_info) ||
        boot_info->e820_count == 0U ||
        boot_info->e820_count > BOOT_INFO_MAX_E820_ENTRIES ||
        boot_info->kernel_physical_start >= boot_info->kernel_physical_end) {
        panic("invalid Boot Info for PMM");
    }
    e820_entries = (const struct e820_entry *)(uintptr_t)boot_info->e820_address;
    for (index = 0U; index < PMM_BITMAP_SIZE; ++index) {
        used_bitmap[index] = 0xFFU;
        allocatable_bitmap[index] = 0U;
    }

    for (index = 0U; index < boot_info->e820_count; ++index) {
        uint32_t first;
        uint32_t limit;

        if (range_to_pages(e820_entries[index].base, e820_entries[index].length,
                           &first, &limit)) {
            if (limit > maximum_page) {
                maximum_page = limit;
            }
            if (e820_entries[index].type == E820_USABLE) {
                make_range_allocatable(
                    e820_entries[index].base,
                    e820_entries[index].length
                );
            }
        }
    }
    for (index = 0U; index < boot_info->e820_count; ++index) {
        if (e820_entries[index].type != E820_USABLE) {
            reserve_range(e820_entries[index].base, e820_entries[index].length);
        }
    }
    reserve_range(0U, LOW_MEMORY_RESERVED_END);
    reserve_range(
        boot_info->kernel_physical_start,
        (uint64_t)boot_info->kernel_physical_end - boot_info->kernel_physical_start
    );

    total_pages = maximum_page;
    free_pages = 0U;
    for (page = 0U; page < total_pages; ++page) {
        if (bitmap_get(allocatable_bitmap, page) && !bitmap_get(used_bitmap, page)) {
            ++free_pages;
        }
    }
    reserved_pages = total_pages - free_pages;
    if (total_pages == 0U || free_pages == 0U) {
        panic("PMM has no usable pages");
    }
}

uint32_t pmm_alloc(void)
{
    uint32_t page;

    for (page = 0U; page < total_pages; ++page) {
        if (bitmap_get(allocatable_bitmap, page) && !bitmap_get(used_bitmap, page)) {
            bitmap_set(used_bitmap, page, true);
            --free_pages;
            return page << PAGE_SHIFT;
        }
    }
    return 0U;
}

bool pmm_free(uint32_t physical_address)
{
    uint32_t page;

    if ((physical_address & (PAGE_SIZE - 1U)) != 0U) {
        return false;
    }
    page = physical_address >> PAGE_SHIFT;
    if (page >= total_pages || !bitmap_get(allocatable_bitmap, page) ||
        !bitmap_get(used_bitmap, page)) {
        return false;
    }
    bitmap_set(used_bitmap, page, false);
    ++free_pages;
    return true;
}

struct pmm_stats pmm_get_stats(void)
{
    struct pmm_stats stats = {total_pages, free_pages, reserved_pages};
    return stats;
}

bool pmm_self_test(void)
{
    uint32_t initial_free = free_pages;
    uint32_t first = pmm_alloc();
    uint32_t second = pmm_alloc();
    uint32_t recycled;

    if (first == 0U || second == 0U || first == second ||
        (first & (PAGE_SIZE - 1U)) != 0U ||
        (second & (PAGE_SIZE - 1U)) != 0U) {
        return false;
    }
    if (!pmm_free(first)) {
        return false;
    }
    recycled = pmm_alloc();
    if (recycled != first || !pmm_free(recycled) || !pmm_free(second)) {
        return false;
    }
    return free_pages == initial_free;
}
