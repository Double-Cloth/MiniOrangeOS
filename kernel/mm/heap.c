#include <minios/mm/heap.h>
#include <minios/mm/pmm.h>
#include <minios/mm/vmm.h>
#include <minios/panic.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PAGE_SIZE 4096U
#define HEAP_ALIGNMENT 8U
#define HEAP_MAGIC 0x48454150U
#define HEAP_STATE_FREE 0x46524545U
#define HEAP_STATE_ALLOCATED 0x55534544U
#define HEAP_VIRTUAL_START 0xD1000000U
#define HEAP_MAX_SIZE 0x01000000U
#define HEAP_STRESS_BLOCKS 64U

struct heap_block {
    uint32_t magic;
    uint32_t size;
    struct heap_block *prev;
    struct heap_block *next;
    uint32_t state;
    uint32_t reserved;
};

_Static_assert(sizeof(struct heap_block) % HEAP_ALIGNMENT == 0U,
               "heap header must preserve payload alignment");

static struct heap_block *heap_head;
static uint32_t heap_end;
static uint32_t heap_mapped_pages;
static bool heap_initialized;

static uint32_t block_address(const struct heap_block *block)
{
    return (uint32_t)(uintptr_t)block;
}

static uint32_t payload_address(const struct heap_block *block)
{
    return block_address(block) + (uint32_t)sizeof(struct heap_block);
}

static void initialize_block(struct heap_block *block, uint32_t size,
                             struct heap_block *prev,
                             struct heap_block *next)
{
    block->magic = HEAP_MAGIC;
    block->size = size;
    block->prev = prev;
    block->next = next;
    block->state = HEAP_STATE_FREE;
    block->reserved = 0U;
}

static void validate_block(const struct heap_block *block)
{
    uint32_t address = block_address(block);
    uint32_t payload;
    uint32_t header_size = (uint32_t)sizeof(struct heap_block);

    if (address < HEAP_VIRTUAL_START ||
        address > heap_end - header_size ||
        block->magic != HEAP_MAGIC ||
        (block->state != HEAP_STATE_FREE &&
         block->state != HEAP_STATE_ALLOCATED)) {
        panic("heap metadata corrupted");
    }
    payload = payload_address(block);
    if (block->size > heap_end - payload ||
        (block->size & (HEAP_ALIGNMENT - 1U)) != 0U) {
        panic("heap block bounds corrupted");
    }
    if (block->next != NULL) {
        uint32_t next_address = block_address(block->next);

        if (payload + block->size > heap_end - header_size ||
            next_address != payload + block->size) {
            panic("heap links corrupted");
        }
        if (block->next->prev != block) {
            panic("heap reverse link corrupted");
        }
    } else if (payload + block->size != heap_end) {
        panic("heap tail corrupted");
    }
    if (block->prev != NULL) {
        uint32_t prev_address = block_address(block->prev);

        if (prev_address < HEAP_VIRTUAL_START ||
            prev_address > address - header_size ||
            block->prev->magic != HEAP_MAGIC ||
            block->prev->next != block ||
            payload_address(block->prev) + block->prev->size != address) {
            panic("heap previous link corrupted");
        }
    } else if (block != heap_head) {
        panic("heap head link corrupted");
    }
}

static bool align_request(size_t size, uint32_t *aligned)
{
    uint32_t value;

    if (size == 0U || size > (size_t)(UINT32_MAX - (HEAP_ALIGNMENT - 1U))) {
        return false;
    }
    value = (uint32_t)size;
    value = (value + (HEAP_ALIGNMENT - 1U)) & ~(HEAP_ALIGNMENT - 1U);
    if (value > HEAP_MAX_SIZE - (uint32_t)sizeof(struct heap_block)) {
        return false;
    }
    *aligned = value;
    return true;
}

static struct heap_block *heap_tail(void)
{
    struct heap_block *block = heap_head;

    while (block->next != NULL) {
        validate_block(block);
        block = block->next;
    }
    validate_block(block);
    return block;
}

static struct heap_block *find_first_fit(uint32_t size)
{
    struct heap_block *block = heap_head;

    while (block != NULL) {
        validate_block(block);
        if (block->state == HEAP_STATE_FREE && block->size >= size) {
            return block;
        }
        block = block->next;
    }
    return NULL;
}

static void split_block(struct heap_block *block, uint32_t size)
{
    uint32_t remaining = block->size - size;
    struct heap_block *new_block;

    if (remaining < (uint32_t)sizeof(struct heap_block) + HEAP_ALIGNMENT) {
        return;
    }
    new_block = (struct heap_block *)(uintptr_t)(payload_address(block) + size);
    initialize_block(new_block,
                     remaining - (uint32_t)sizeof(struct heap_block),
                     block, block->next);
    if (block->next != NULL) {
        block->next->prev = new_block;
    }
    block->next = new_block;
    block->size = size;
}

static void merge_with_next(struct heap_block *block)
{
    struct heap_block *next = block->next;

    validate_block(block);
    if (next == NULL) {
        return;
    }
    validate_block(next);
    if (next->state != HEAP_STATE_FREE) {
        return;
    }
    block->size += (uint32_t)sizeof(struct heap_block) + next->size;
    block->next = next->next;
    if (block->next != NULL) {
        block->next->prev = block;
    }
    next->magic = 0U;
    next->size = 0U;
    next->prev = NULL;
    next->next = NULL;
    next->state = 0U;
}

static struct heap_block *coalesce(struct heap_block *block)
{
    merge_with_next(block);
    if (block->prev != NULL) {
        validate_block(block->prev);
    }
    if (block->prev != NULL && block->prev->state == HEAP_STATE_FREE) {
        block = block->prev;
        merge_with_next(block);
    }
    return block;
}

static bool map_extension(uint32_t start, uint32_t page_count)
{
    uint32_t mapped = 0U;

    while (mapped < page_count) {
        uint32_t physical = pmm_alloc();
        uint32_t virtual_address = start + mapped * PAGE_SIZE;

        if (physical == 0U) {
            break;
        }
        if (!vmm_map(virtual_address, physical, VMM_WRITABLE)) {
            if (!pmm_free(physical)) {
                panic("heap could not release rejected page");
            }
            break;
        }
        ++mapped;
    }
    if (mapped == page_count) {
        return true;
    }
    while (mapped > 0U) {
        uint32_t physical = 0U;
        uint32_t virtual_address;

        --mapped;
        virtual_address = start + mapped * PAGE_SIZE;
        if (!vmm_unmap(virtual_address, &physical) || !pmm_free(physical)) {
            panic("heap extension rollback failed");
        }
    }
    return false;
}

static bool grow_heap(uint32_t size)
{
    struct heap_block *tail = heap_tail();
    uint32_t required = size;
    uint32_t available_size = heap_mapped_pages * PAGE_SIZE;
    uint32_t page_count;
    uint32_t mapped_bytes;
    uint32_t old_end = heap_end;

    if (tail->state == HEAP_STATE_FREE) {
        if (tail->size >= size) {
            return true;
        }
        required -= tail->size;
    } else {
        if (required > UINT32_MAX - (uint32_t)sizeof(struct heap_block)) {
            return false;
        }
        required += (uint32_t)sizeof(struct heap_block);
    }
    page_count = (required + PAGE_SIZE - 1U) / PAGE_SIZE;
    if (page_count > (HEAP_MAX_SIZE - available_size) / PAGE_SIZE) {
        return false;
    }
    if (!map_extension(old_end, page_count)) {
        return false;
    }
    mapped_bytes = page_count * PAGE_SIZE;
    heap_end += mapped_bytes;
    heap_mapped_pages += page_count;
    if (tail->state == HEAP_STATE_FREE) {
        tail->size += mapped_bytes;
    } else {
        struct heap_block *new_block =
            (struct heap_block *)(uintptr_t)old_end;
        initialize_block(new_block,
                         mapped_bytes - (uint32_t)sizeof(struct heap_block),
                         tail, NULL);
        tail->next = new_block;
    }
    return true;
}

void heap_init(void)
{
    uint32_t physical;

    if (heap_initialized) {
        panic("heap initialized twice");
    }
    physical = pmm_alloc();
    if (physical == 0U ||
        !vmm_map(HEAP_VIRTUAL_START, physical, VMM_WRITABLE)) {
        if (physical != 0U && !pmm_free(physical)) {
            panic("heap initial page rollback failed");
        }
        panic("heap initial page unavailable");
    }
    heap_end = HEAP_VIRTUAL_START + PAGE_SIZE;
    heap_mapped_pages = 1U;
    heap_head = (struct heap_block *)(uintptr_t)HEAP_VIRTUAL_START;
    initialize_block(heap_head,
                     PAGE_SIZE - (uint32_t)sizeof(struct heap_block),
                     NULL, NULL);
    heap_initialized = true;
}

void *kmalloc(size_t size)
{
    struct heap_block *block;
    uint32_t aligned;

    if (!heap_initialized || !align_request(size, &aligned)) {
        return NULL;
    }
    block = find_first_fit(aligned);
    if (block == NULL) {
        if (!grow_heap(aligned)) {
            return NULL;
        }
        block = find_first_fit(aligned);
        if (block == NULL) {
            panic("heap growth produced no fitting block");
        }
    }
    split_block(block, aligned);
    block->state = HEAP_STATE_ALLOCATED;
    return (void *)(uintptr_t)payload_address(block);
}

bool kfree(void *pointer)
{
    struct heap_block *block;
    uint32_t address;

    if (pointer == NULL) {
        return true;
    }
    if (!heap_initialized) {
        return false;
    }
    address = (uint32_t)(uintptr_t)pointer;
    if (address < HEAP_VIRTUAL_START + (uint32_t)sizeof(struct heap_block) ||
        address >= heap_end || (address & (HEAP_ALIGNMENT - 1U)) != 0U) {
        return false;
    }
    block = heap_head;
    while (block != NULL) {
        validate_block(block);
        if (payload_address(block) == address) {
            if (block->state != HEAP_STATE_ALLOCATED) {
                return false;
            }
            block->state = HEAP_STATE_FREE;
            (void)coalesce(block);
            return true;
        }
        block = block->next;
    }
    return false;
}

struct heap_stats heap_get_stats(void)
{
    struct heap_stats stats = {0U, 0U, 0U, 0U, 0U};
    struct heap_block *block;

    if (!heap_initialized) {
        return stats;
    }
    stats.mapped_pages = heap_mapped_pages;
    block = heap_head;
    while (block != NULL) {
        validate_block(block);
        if (block->state == HEAP_STATE_FREE) {
            ++stats.free_blocks;
            stats.free_bytes += block->size;
        } else {
            ++stats.allocated_blocks;
            stats.allocated_bytes += block->size;
        }
        block = block->next;
    }
    return stats;
}

bool heap_self_test(void)
{
    void *small[HEAP_STRESS_BLOCKS];
    void *first = kmalloc(24U);
    void *middle = kmalloc(40U);
    void *last = kmalloc(24U);
    void *replacement;
    void *merged;
    void *large;
    struct heap_stats stats;
    uint32_t index;

    if (first == NULL || middle == NULL || last == NULL ||
        ((uint32_t)(uintptr_t)first & (HEAP_ALIGNMENT - 1U)) != 0U ||
        !kfree(middle)) {
        return false;
    }
    replacement = kmalloc(32U);
    if (replacement != middle || !kfree(replacement) ||
        !kfree(first) || !kfree(last)) {
        return false;
    }
    merged = kmalloc(96U);
    if (merged != first || !kfree(merged) || kfree(merged)) {
        return false;
    }
    for (index = 0U; index < HEAP_STRESS_BLOCKS; ++index) {
        volatile uint8_t *bytes;
        uint32_t size = 8U + (index % 7U) * 8U;

        small[index] = kmalloc(size);
        if (small[index] == NULL) {
            return false;
        }
        bytes = (volatile uint8_t *)small[index];
        bytes[0] = (uint8_t)index;
        bytes[size - 1U] = (uint8_t)(index ^ 0x5AU);
    }
    for (index = 0U; index < HEAP_STRESS_BLOCKS; index += 2U) {
        if (!kfree(small[index])) {
            return false;
        }
    }
    for (index = 1U; index < HEAP_STRESS_BLOCKS; index += 2U) {
        if (!kfree(small[index])) {
            return false;
        }
    }
    large = kmalloc(PAGE_SIZE * 2U);
    if (large == NULL || !kfree(large) || kmalloc(HEAP_MAX_SIZE) != NULL) {
        return false;
    }
    stats = heap_get_stats();
    return stats.mapped_pages >= 3U && stats.allocated_blocks == 0U &&
           stats.free_blocks == 1U && kfree(NULL);
}
