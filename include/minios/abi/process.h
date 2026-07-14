#ifndef MINIOS_ABI_PROCESS_H
#define MINIOS_ABI_PROCESS_H

#include <stdint.h>

#define MINIOS_PROCESS_NAME_LENGTH 32U
#define MINIOS_PROCESS_LIMIT 16U

struct minios_process_info {
    uint32_t pid;
    uint32_t parent_pid;
    uint32_t state;
    char name[MINIOS_PROCESS_NAME_LENGTH];
};

#endif
