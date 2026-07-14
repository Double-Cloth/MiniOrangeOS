BITS 32

SECTION .rodata ALIGN=16

GLOBAL embedded_init_start
GLOBAL embedded_init_end

embedded_init_start:
    INCBIN "init.elf"
embedded_init_end:

ALIGN 16
GLOBAL embedded_echo_start
GLOBAL embedded_echo_end

embedded_echo_start:
    INCBIN "echo.elf"
embedded_echo_end:

ALIGN 16
GLOBAL embedded_sh_start
GLOBAL embedded_sh_end

embedded_sh_start:
    INCBIN "sh.elf"
embedded_sh_end:
