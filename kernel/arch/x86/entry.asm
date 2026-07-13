BITS 32

section .text
global kernel_entry
extern kernel_main

kernel_entry:
    cli
    call kernel_main

.halt:
    hlt
    jmp .halt
