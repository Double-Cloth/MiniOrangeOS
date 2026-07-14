#include <minios/errno.h>
#include <minios/mm/pmm.h>
#include <minios/mm/usercopy.h>
#include <minios/mm/vmm.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PAGE_SIZE 4096U
#define PAGE_MASK 0xFFFFF000U
#define KERNEL_BASE 0xC0000000U
#define USERCOPY_TEST_VIRTUAL 0x00800000U

bool validate_user_range(const void *user_pointer, size_t length,
                         enum user_access access)
{
    uint32_t start = (uint32_t)(uintptr_t)user_pointer;
    uint32_t end;
    uint32_t page;

    if (length == 0U) {
        return true;
    }
    if (start >= KERNEL_BASE || length > (size_t)(KERNEL_BASE - start)) {
        return false;
    }
    end = start + (uint32_t)length - 1U;
    page = start & PAGE_MASK;
    for (;;) {
        uint32_t flags = 0U;

        if (!vmm_query(page, NULL, &flags) || (flags & VMM_USER) == 0U ||
            (access == USER_ACCESS_WRITE &&
             (flags & VMM_WRITABLE) == 0U)) {
            return false;
        }
        if (page == (end & PAGE_MASK)) {
            return true;
        }
        page += PAGE_SIZE;
    }
}

int copy_from_user(void *kernel_destination, const void *user_source,
                   size_t length)
{
    uint8_t *destination = (uint8_t *)kernel_destination;
    const uint8_t *source = (const uint8_t *)user_source;
    size_t index;

    if (length == 0U) {
        return 0;
    }
    if (kernel_destination == NULL ||
        !validate_user_range(user_source, length, USER_ACCESS_READ)) {
        return -MINIOS_EFAULT;
    }
    for (index = 0U; index < length; ++index) {
        destination[index] = source[index];
    }
    return 0;
}

int copy_to_user(void *user_destination, const void *kernel_source,
                 size_t length)
{
    uint8_t *destination = (uint8_t *)user_destination;
    const uint8_t *source = (const uint8_t *)kernel_source;
    size_t index;

    if (length == 0U) {
        return 0;
    }
    if (kernel_source == NULL ||
        !validate_user_range(user_destination, length, USER_ACCESS_WRITE)) {
        return -MINIOS_EFAULT;
    }
    for (index = 0U; index < length; ++index) {
        destination[index] = source[index];
    }
    return 0;
}

int copy_user_string(char *kernel_destination, const char *user_source,
                     size_t maximum_length)
{
    uint32_t start = (uint32_t)(uintptr_t)user_source;
    size_t index;

    if (kernel_destination == NULL || maximum_length == 0U ||
        start >= KERNEL_BASE) {
        return -MINIOS_EFAULT;
    }
    for (index = 0U; index < maximum_length; ++index) {
        const char *current;
        char value;

        if (index >= (size_t)(KERNEL_BASE - start)) {
            return -MINIOS_EFAULT;
        }
        current = (const char *)(uintptr_t)(start + (uint32_t)index);
        if (!validate_user_range(current, 1U, USER_ACCESS_READ)) {
            return -MINIOS_EFAULT;
        }
        value = *current;
        kernel_destination[index] = value;
        if (value == '\0') {
            return 0;
        }
    }
    return -MINIOS_EFAULT;
}

bool usercopy_self_test(void)
{
    struct pmm_stats before = pmm_get_stats();
    volatile char *writable =
        (volatile char *)(uintptr_t)USERCOPY_TEST_VIRTUAL;
    volatile char *writable_second =
        (volatile char *)(uintptr_t)(USERCOPY_TEST_VIRTUAL + PAGE_SIZE);
    volatile char *boundary =
        (volatile char *)(uintptr_t)(KERNEL_BASE - PAGE_SIZE);
    char source[] = {'O', 'S', '\0'};
    char copied[8] = {0};
    char string[8] = {0};
    uint32_t writable_physical = pmm_alloc();
    uint32_t writable_second_physical = pmm_alloc();
    uint32_t readonly_physical = pmm_alloc();
    uint32_t boundary_physical = pmm_alloc();
    uint32_t unmapped = 0U;
    bool passed;

    if (writable_physical == 0U || writable_second_physical == 0U ||
        readonly_physical == 0U || boundary_physical == 0U ||
        !vmm_map(USERCOPY_TEST_VIRTUAL, writable_physical,
                 VMM_USER | VMM_WRITABLE) ||
        !vmm_map(USERCOPY_TEST_VIRTUAL + PAGE_SIZE,
                 writable_second_physical, VMM_USER | VMM_WRITABLE) ||
        !vmm_map(USERCOPY_TEST_VIRTUAL + 3U * PAGE_SIZE, readonly_physical,
                 VMM_USER) ||
        !vmm_map(KERNEL_BASE - PAGE_SIZE, boundary_physical,
                 VMM_USER | VMM_WRITABLE)) {
        return false;
    }
    writable[0] = 'o';
    writable[1] = 'r';
    writable[2] = 'a';
    writable[3] = 'n';
    writable[4] = 'g';
    writable[5] = 'e';
    writable[6] = '\0';
    writable[PAGE_SIZE - 2U] = 'A';
    writable[PAGE_SIZE - 1U] = 'B';
    writable_second[0] = 'C';
    writable_second[1] = 'D';
    writable_second[PAGE_SIZE - 1U] = '\0';
    boundary[PAGE_SIZE - 1U] = '\0';
    passed =
        copy_from_user(copied, (const void *)writable, 7U) == 0 &&
        copied[0] == 'o' && copied[5] == 'e' && copied[6] == '\0' &&
        copy_to_user((void *)(uintptr_t)(USERCOPY_TEST_VIRTUAL + 16U),
                     source, sizeof(source)) == 0 &&
        writable[16] == 'O' && writable[17] == 'S' &&
        copy_user_string(string, (const char *)writable,
                         sizeof(string)) == 0 &&
        string[0] == 'o' && string[6] == '\0' &&
        copy_from_user(copied,
                       (const void *)(uintptr_t)(USERCOPY_TEST_VIRTUAL +
                                                 PAGE_SIZE - 2U),
                       4U) == 0 &&
        copied[0] == 'A' && copied[1] == 'B' &&
        copied[2] == 'C' && copied[3] == 'D' &&
        copy_to_user((void *)(uintptr_t)(USERCOPY_TEST_VIRTUAL +
                                         PAGE_SIZE - 1U),
                     source, sizeof(source)) == 0 &&
        writable[PAGE_SIZE - 1U] == 'O' && writable_second[0] == 'S' &&
        writable_second[1] == '\0' &&
        copy_user_string(string,
                         (const char *)(uintptr_t)(USERCOPY_TEST_VIRTUAL +
                                                   2U * PAGE_SIZE - 1U),
                         sizeof(string)) == 0 && string[0] == '\0' &&
        copy_user_string(string,
                         (const char *)(uintptr_t)(KERNEL_BASE - 1U),
                         sizeof(string)) == 0 && string[0] == '\0' &&
        copy_to_user((void *)(uintptr_t)(USERCOPY_TEST_VIRTUAL +
                                         3U * PAGE_SIZE),
                     source, sizeof(source)) == -MINIOS_EFAULT &&
        copy_from_user(copied,
                       (const void *)(uintptr_t)(USERCOPY_TEST_VIRTUAL +
                                                 4U * PAGE_SIZE),
                       1U) == -MINIOS_EFAULT &&
        !validate_user_range((const void *)(uintptr_t)0xBFFFFFF0U, 32U,
                             USER_ACCESS_READ) &&
        copy_from_user(NULL, NULL, 0U) == 0;
    if (!vmm_unmap(USERCOPY_TEST_VIRTUAL, &unmapped) ||
        unmapped != writable_physical || !pmm_free(writable_physical) ||
        !vmm_unmap(USERCOPY_TEST_VIRTUAL + PAGE_SIZE, &unmapped) ||
        unmapped != writable_second_physical ||
        !pmm_free(writable_second_physical) ||
        !vmm_unmap(USERCOPY_TEST_VIRTUAL + 3U * PAGE_SIZE, &unmapped) ||
        unmapped != readonly_physical || !pmm_free(readonly_physical) ||
        !vmm_unmap(KERNEL_BASE - PAGE_SIZE, &unmapped) ||
        unmapped != boundary_physical || !pmm_free(boundary_physical)) {
        return false;
    }
    return passed && pmm_get_stats().free_pages == before.free_pages;
}
