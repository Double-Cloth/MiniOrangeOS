BITS 32

SECTION .text

GLOBAL _start
EXTERN main
EXTERN minios_exit

_start:
    ; 内核按 cdecl 入口栈布局压入 argc/argv，crt0 只负责转交并退出。
    xor ebp, ebp
    mov eax, [esp]
    lea edx, [esp + 4]
    push edx
    push eax
    call main
    add esp, 8
    push eax
    call minios_exit
    ud2
