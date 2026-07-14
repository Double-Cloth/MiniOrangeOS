#ifndef MINIOS_BLOCK_BLOCK_H
#define MINIOS_BLOCK_BLOCK_H

#include <stdbool.h>
#include <stdint.h>

#define BLOCK_SIZE 4096U

int32_t block_init(void);
uint32_t block_count(void);
int32_t block_read(uint32_t block_number, uint32_t count, void *buffer);
int32_t block_write(uint32_t block_number, uint32_t count,
                    const void *buffer);
bool block_self_test(void);

#endif
