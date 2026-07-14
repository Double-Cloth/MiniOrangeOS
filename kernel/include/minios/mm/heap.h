#ifndef MINIOS_MM_HEAP_H
#define MINIOS_MM_HEAP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct heap_stats {
    uint32_t mapped_pages;
    uint32_t allocated_blocks;
    uint32_t free_blocks;
    uint32_t allocated_bytes;
    uint32_t free_bytes;
};

void heap_init(void);
void *kmalloc(size_t size);
bool kfree(void *pointer);
struct heap_stats heap_get_stats(void);
bool heap_self_test(void);

#endif
