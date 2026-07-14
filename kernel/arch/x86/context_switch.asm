BITS 32

section .text
global context_switch

; cdecl: context_switch(&old_saved_stack, new_saved_stack)
; 新旧栈都以 EDI、ESI、EBX、EBP、返回地址为固定布局。
context_switch:
    push ebp
    push ebx
    push esi
    push edi

    mov eax, [esp + 20]
    mov edx, [esp + 24]
    mov [eax], esp
    mov esp, edx

    pop edi
    pop esi
    pop ebx
    pop ebp
    ret
