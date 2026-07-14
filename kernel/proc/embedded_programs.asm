BITS 32

SECTION .rodata ALIGN=16

GLOBAL embedded_init_start
GLOBAL embedded_init_end

embedded_init_start:
    INCBIN "init.elf"
embedded_init_end:
