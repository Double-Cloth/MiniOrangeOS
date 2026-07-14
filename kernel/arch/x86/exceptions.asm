BITS 32

%define KERNEL_DATA_SELECTOR 0x10

section .text
extern exception_dispatch
global idt_load

; 输入为指向 6-byte IDTR operand 的 cdecl 参数；只修改 EAX。
idt_load:
    mov eax, [esp + 4]
    lidt [eax]
    ret

%macro EXCEPTION_NO_ERROR 1
global exception_stub_%1
exception_stub_%1:
    push dword 0
    push dword %1
    jmp exception_common
%endmacro

%macro EXCEPTION_ERROR 1
global exception_stub_%1
exception_stub_%1:
    push dword %1
    jmp exception_common
%endmacro

; CPU 已保存 EIP/CS/EFLAGS；宏统一补齐 vector/error_code。
; pushad 后另存用户段寄存器，C 始终在 Ring 0 data selector 下运行。
exception_common:
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
    call exception_dispatch
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

EXCEPTION_NO_ERROR 0
EXCEPTION_NO_ERROR 1
EXCEPTION_NO_ERROR 2
EXCEPTION_NO_ERROR 3
EXCEPTION_NO_ERROR 4
EXCEPTION_NO_ERROR 5
EXCEPTION_NO_ERROR 6
EXCEPTION_NO_ERROR 7
EXCEPTION_ERROR 8
EXCEPTION_NO_ERROR 9
EXCEPTION_ERROR 10
EXCEPTION_ERROR 11
EXCEPTION_ERROR 12
EXCEPTION_ERROR 13
EXCEPTION_ERROR 14
EXCEPTION_NO_ERROR 15
EXCEPTION_NO_ERROR 16
EXCEPTION_ERROR 17
EXCEPTION_NO_ERROR 18
EXCEPTION_NO_ERROR 19
EXCEPTION_NO_ERROR 20
EXCEPTION_ERROR 21
EXCEPTION_NO_ERROR 22
EXCEPTION_NO_ERROR 23
EXCEPTION_NO_ERROR 24
EXCEPTION_NO_ERROR 25
EXCEPTION_NO_ERROR 26
EXCEPTION_NO_ERROR 27
EXCEPTION_NO_ERROR 28
EXCEPTION_ERROR 29
EXCEPTION_ERROR 30
EXCEPTION_NO_ERROR 31

section .rodata
global exception_stub_table
exception_stub_table:
%assign vector 0
%rep 32
    dd exception_stub_%+vector
%assign vector vector + 1
%endrep
