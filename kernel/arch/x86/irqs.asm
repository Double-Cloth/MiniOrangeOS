BITS 32

%define KERNEL_DATA_SELECTOR 0x10

section .text
extern irq_dispatch

%macro IRQ_STUB 1
global irq_stub_%1
irq_stub_%1:
    push dword 0
    push dword (32 + %1)
    jmp irq_common
%endmacro

; IRQ 使用与 CPU 异常相同的 trap frame，返回前移除 vector/error_code。
irq_common:
    cld
    pushad

    xor eax, eax
    mov ax, ds
    push eax
    xor eax, eax
    mov ax, es
    push eax
    xor eax, eax
    mov ax, fs
    push eax
    xor eax, eax
    mov ax, gs
    push eax

    mov ax, KERNEL_DATA_SELECTOR
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    lea eax, [esp + 16]
    push eax
    call irq_dispatch
    add esp, 4

    pop eax
    mov gs, ax
    pop eax
    mov fs, ax
    pop eax
    mov es, ax
    pop eax
    mov ds, ax
    popad
    add esp, 8
    iretd

IRQ_STUB 0
IRQ_STUB 1
IRQ_STUB 2
IRQ_STUB 3
IRQ_STUB 4
IRQ_STUB 5
IRQ_STUB 6
IRQ_STUB 7
IRQ_STUB 8
IRQ_STUB 9
IRQ_STUB 10
IRQ_STUB 11
IRQ_STUB 12
IRQ_STUB 13
IRQ_STUB 14
IRQ_STUB 15

section .rodata
global irq_stub_table
irq_stub_table:
%assign irq 0
%rep 16
    dd irq_stub_%+irq
%assign irq irq + 1
%endrep
