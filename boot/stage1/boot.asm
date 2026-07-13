BITS 16
ORG 0x7C00

stage1_entry:
    cli

.halt:
    hlt
    jmp .halt

times 512 - ($ - $$) db 0
