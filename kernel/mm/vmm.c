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
#define VGA_PHYSICAL_ADDRESS 0x000B8000U
#define VGA_VIRTUAL_ADDRESS (KERNEL_BASE + VGA_PHYSICAL_ADDRESS)
#define SCRATCH_VIRTUAL_ADDRESS 0xC03FF000U
#define RECURSIVE_PAGE_TABLES 0xFFC00000U
#define RECURSIVE_PAGE_DIRECTORY 0xFFFFF000U
#define RECURSIVE_PDE_INDEX 1023U
#define PAGE_PRESENT 0x01U
#define PAGE_WRITABLE VMM_WRITABLE
#define PAGE_USER VMM_USER
#define CR0_WRITE_PROTECT 0x00010000U
#define VMM_TEST_VIRTUAL_ADDRESS 0xD0000000U
#define VMM_TEST_VALUE 0x51A7C0DEU

extern uint8_t boot_page_directory[];
extern uint8_t boot_page_table[];
extern uint8_t __text_start[];
extern uint8_t __text_end[];
extern uint8_t __rodata_start[];
extern uint8_t __rodata_end[];

static bool vmm_initialized;

static void invalidate_page(uint32_t virtual_address)
{
    __asm__ volatile("invlpg (%0)" : : "r"(virtual_address) : "memory");
}

static uint32_t read_cr3(void)
{
    uint32_t value;
    __asm__ volatile("mov %%cr3, %0" : "=r"(value));
    return value;
}

static void reload_cr3(uint32_t value)
{
    __asm__ volatile("mov %0, %%cr3" : : "r"(value) : "memory");
}

static void enable_write_protect(void)
{
    uint32_t value;
    __asm__ volatile("mov %%cr0, %0" : "=r"(value));
    value |= CR0_WRITE_PROTECT;
    __asm__ volatile("mov %0, %%cr0" : : "r"(value) : "memory");
}

static bool page_is_read_only_kernel(uint32_t virtual_address)
{
    uint32_t text_start = (uint32_t)(uintptr_t)__text_start;
    uint32_t text_end = (uint32_t)(uintptr_t)__text_end;
    uint32_t rodata_start = (uint32_t)(uintptr_t)__rodata_start;
    uint32_t rodata_end = (uint32_t)(uintptr_t)__rodata_end;

    return (virtual_address >= text_start && virtual_address < text_end) ||
           (virtual_address >= rodata_start && virtual_address < rodata_end);
}

static volatile uint32_t *recursive_page_directory(void)
{
    return (volatile uint32_t *)(uintptr_t)RECURSIVE_PAGE_DIRECTORY;
}

static volatile uint32_t *recursive_page_tables(void)
{
    return (volatile uint32_t *)(uintptr_t)RECURSIVE_PAGE_TABLES;
}

static void zero_page_through_scratch(uint32_t physical_address)
{
    volatile uint32_t *page_tables = recursive_page_tables();
    uint32_t scratch_index =
        KERNEL_PDE_INDEX * PAGE_ENTRY_COUNT + (PAGE_ENTRY_COUNT - 1U);
    volatile uint32_t *scratch =
        (volatile uint32_t *)(uintptr_t)SCRATCH_VIRTUAL_ADDRESS;
    uint32_t index;

    if ((page_tables[scratch_index] & PAGE_PRESENT) != 0U) {
        panic("VMM scratch mapping is busy");
    }
    page_tables[scratch_index] = physical_address | PAGE_PRESENT | PAGE_WRITABLE;
    invalidate_page(SCRATCH_VIRTUAL_ADDRESS);
    for (index = 0U; index < PAGE_ENTRY_COUNT; ++index) {
        scratch[index] = 0U;
    }
    page_tables[scratch_index] = 0U;
    invalidate_page(SCRATCH_VIRTUAL_ADDRESS);
}

void vmm_init(const struct boot_info *boot_info)
{
    volatile uint32_t *page_directory = (volatile uint32_t *)boot_page_directory;
    volatile uint32_t *page_table = (volatile uint32_t *)boot_page_table;
    uint32_t directory_physical = read_cr3() & PAGE_MASK;
    uint32_t index;

    if (boot_info == NULL || boot_info->kernel_physical_start >=
        boot_info->kernel_physical_end) {
        panic("invalid Boot Info for VMM");
    }
    for (index = 0U; index < PAGE_ENTRY_COUNT; ++index) {
        uint32_t physical = index * PAGE_SIZE;
        uint32_t virtual_address = KERNEL_BASE + physical;

        if (physical == VGA_PHYSICAL_ADDRESS ||
            (physical >= boot_info->kernel_physical_start &&
             physical < boot_info->kernel_physical_end)) {
            uint32_t flags = PAGE_PRESENT;
            if (physical == VGA_PHYSICAL_ADDRESS ||
                !page_is_read_only_kernel(virtual_address)) {
                flags |= PAGE_WRITABLE;
            }
            page_table[index] = physical | flags;
        } else {
            page_table[index] = 0U;
        }
    }
    page_directory[KERNEL_PDE_INDEX] =
        ((uint32_t)(uintptr_t)boot_page_table - KERNEL_BASE) |
        PAGE_PRESENT | PAGE_WRITABLE;
    page_directory[RECURSIVE_PDE_INDEX] =
        directory_physical | PAGE_PRESENT | PAGE_WRITABLE;
    page_directory[0] = 0U;
    enable_write_protect();
    reload_cr3(directory_physical);
    vmm_initialized = true;
}

bool vmm_map(uint32_t virtual_address, uint32_t physical_address, uint32_t flags)
{
    volatile uint32_t *page_directory = recursive_page_directory();
    volatile uint32_t *page_tables = recursive_page_tables();
    uint32_t directory_index;
    uint32_t table_index;
    uint32_t page_table_physical;
    uint32_t entry_index;

    if (!vmm_initialized ||
        (virtual_address & (PAGE_SIZE - 1U)) != 0U ||
        (physical_address & (PAGE_SIZE - 1U)) != 0U ||
        virtual_address == SCRATCH_VIRTUAL_ADDRESS ||
        virtual_address >= RECURSIVE_PAGE_TABLES ||
        ((flags & PAGE_USER) != 0U && virtual_address >= KERNEL_BASE) ||
        ((flags & PAGE_USER) == 0U && virtual_address < KERNEL_BASE)) {
        return false;
    }
    directory_index = virtual_address >> 22U;
    table_index = (virtual_address >> 12U) & 0x3FFU;
    if ((page_directory[directory_index] & PAGE_PRESENT) == 0U) {
        page_table_physical = pmm_alloc();
        if (page_table_physical == 0U) {
            return false;
        }
        zero_page_through_scratch(page_table_physical);
        page_directory[directory_index] =
            page_table_physical | PAGE_PRESENT | PAGE_WRITABLE |
            (flags & PAGE_USER);
        invalidate_page(RECURSIVE_PAGE_TABLES + directory_index * PAGE_SIZE);
    } else if ((flags & PAGE_USER) != 0U) {
        page_directory[directory_index] |= PAGE_USER;
    }
    entry_index = directory_index * PAGE_ENTRY_COUNT + table_index;
    if ((page_tables[entry_index] & PAGE_PRESENT) != 0U) {
        return false;
    }
    page_tables[entry_index] = physical_address | PAGE_PRESENT |
        (flags & (PAGE_WRITABLE | PAGE_USER));
    invalidate_page(virtual_address);
    return true;
}

bool vmm_unmap(uint32_t virtual_address, uint32_t *physical_address)
{
    volatile uint32_t *page_directory = recursive_page_directory();
    volatile uint32_t *page_tables = recursive_page_tables();
    uint32_t directory_index;
    uint32_t table_index;
    uint32_t entry_index;
    uint32_t entry;
    uint32_t index;
    bool empty = true;

    if (!vmm_initialized ||
        (virtual_address & (PAGE_SIZE - 1U)) != 0U ||
        virtual_address >= RECURSIVE_PAGE_TABLES) {
        return false;
    }
    directory_index = virtual_address >> 22U;
    table_index = (virtual_address >> 12U) & 0x3FFU;
    if ((page_directory[directory_index] & PAGE_PRESENT) == 0U) {
        return false;
    }
    entry_index = directory_index * PAGE_ENTRY_COUNT + table_index;
    entry = page_tables[entry_index];
    if ((entry & PAGE_PRESENT) == 0U) {
        return false;
    }
    page_tables[entry_index] = 0U;
    invalidate_page(virtual_address);
    if (physical_address != NULL) {
        *physical_address = entry & PAGE_MASK;
    }
    if (directory_index == KERNEL_PDE_INDEX) {
        return true;
    }
    for (index = 0U; index < PAGE_ENTRY_COUNT; ++index) {
        if ((page_tables[directory_index * PAGE_ENTRY_COUNT + index] &
             PAGE_PRESENT) != 0U) {
            empty = false;
            break;
        }
    }
    if (empty) {
        uint32_t table_physical = page_directory[directory_index] & PAGE_MASK;
        page_directory[directory_index] = 0U;
        invalidate_page(RECURSIVE_PAGE_TABLES + directory_index * PAGE_SIZE);
        if (!pmm_free(table_physical)) {
            panic("VMM could not release empty page table");
        }
    }
    return true;
}

bool vmm_query(uint32_t virtual_address, uint32_t *physical_address, uint32_t *flags)
{
    volatile uint32_t *page_directory = recursive_page_directory();
    volatile uint32_t *page_tables = recursive_page_tables();
    uint32_t directory_index = virtual_address >> 22U;
    uint32_t table_index = (virtual_address >> 12U) & 0x3FFU;
    uint32_t entry;

    if (!vmm_initialized || virtual_address >= RECURSIVE_PAGE_TABLES ||
        (page_directory[directory_index] & PAGE_PRESENT) == 0U) {
        return false;
    }
    entry = page_tables[directory_index * PAGE_ENTRY_COUNT + table_index];
    if ((entry & PAGE_PRESENT) == 0U) {
        return false;
    }
    if (physical_address != NULL) {
        *physical_address = (entry & PAGE_MASK) | (virtual_address & ~PAGE_MASK);
    }
    if (flags != NULL) {
        *flags = entry & (PAGE_WRITABLE | PAGE_USER);
        if ((page_directory[directory_index] & PAGE_WRITABLE) == 0U) {
            *flags &= ~PAGE_WRITABLE;
        }
        if ((page_directory[directory_index] & PAGE_USER) == 0U) {
            *flags &= ~PAGE_USER;
        }
    }
    return true;
}

bool vmm_self_test(void)
{
    struct pmm_stats before = pmm_get_stats();
    volatile uint32_t *test_page =
        (volatile uint32_t *)(uintptr_t)VMM_TEST_VIRTUAL_ADDRESS;
    uint32_t physical = pmm_alloc();
    uint32_t queried = 0U;
    uint32_t unmapped = 0U;

    if (physical == 0U ||
        !vmm_map(VMM_TEST_VIRTUAL_ADDRESS, physical, VMM_WRITABLE) ||
        !vmm_query(VMM_TEST_VIRTUAL_ADDRESS, &queried, NULL) ||
        queried != physical ||
        vmm_map(VMM_TEST_VIRTUAL_ADDRESS, physical, VMM_WRITABLE)) {
        return false;
    }
    test_page[0] = VMM_TEST_VALUE;
    if (test_page[0] != VMM_TEST_VALUE ||
        !vmm_unmap(VMM_TEST_VIRTUAL_ADDRESS, &unmapped) ||
        unmapped != physical ||
        vmm_query(VMM_TEST_VIRTUAL_ADDRESS, NULL, NULL) ||
        !pmm_free(physical)) {
        return false;
    }
    return pmm_get_stats().free_pages == before.free_pages;
}
