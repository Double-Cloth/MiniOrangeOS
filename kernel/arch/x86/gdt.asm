BITS 32

%define KERNEL_CODE_SELECTOR 0x08
%define KERNEL_DATA_SELECTOR 0x10

section .text
global gdt_load

gdt_load:
    mov eax, [esp + 4]
    lgdt [eax]

    mov ax, KERNEL_DATA_SELECTOR
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    jmp 0x08:.reload_cs
.reload_cs:
    ret
