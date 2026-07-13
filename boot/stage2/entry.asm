BITS 32

section .text
global stage2_entry

stage2_entry:
    cli

.halt:
    hlt
    jmp .halt
