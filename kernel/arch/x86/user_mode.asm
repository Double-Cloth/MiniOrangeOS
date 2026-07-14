BITS 32

%define KERNEL_DATA_SELECTOR 0x10
%define USER_CODE_SELECTOR 0x1B
%define USER_DATA_SELECTOR 0x23
%define USER_TEST_VIRTUAL 0x00400000

section .text
extern syscall_dispatch
global enter_user_mode
global syscall_stub

; cdecl: enter_user_mode(entry, stack_top)，通过 iret 构造首次 Ring 3 上下文。
enter_user_mode:
    mov ecx, [esp + 4]
    mov edx, [esp + 8]
    mov ax, USER_DATA_SELECTOR
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    push dword USER_DATA_SELECTOR
    push edx
    push dword 0x00000202
    push dword USER_CODE_SELECTOR
    push ecx
    iretd

; CPU 已保存用户 SS/ESP/EFLAGS/CS/EIP；统一帧允许 C 修改 EAX 返回值。
syscall_stub:
    push dword 0
    push dword 128
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
    cld
    lea eax, [esp + 16]
    push eax
    call syscall_dispatch
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

section .rodata
align 16
global user_test_start
global user_test_end

user_test_start:
    mov eax, 12
    int 0x80
    test eax, eax
    jle user_test_fail

    mov eax, 0xFFFFFFFF
    int 0x80
    cmp eax, -38
    jne user_test_fail

    mov eax, 1
    mov ebx, 3
    mov ecx, USER_TEST_VIRTUAL + user_test_message - user_test_start
    mov edx, 1
    int 0x80
    cmp eax, -9
    jne user_test_fail

    mov eax, 1
    mov ebx, 1
    mov ecx, 0xC0000000
    mov edx, 1
    int 0x80
    cmp eax, -14
    jne user_test_fail

    mov eax, 1
    mov ebx, 1
    mov ecx, USER_TEST_VIRTUAL + user_test_message - user_test_start
    mov edx, 4097
    int 0x80
    cmp eax, -22
    jne user_test_fail

    mov eax, 1
    mov ebx, 1
    mov ecx, USER_TEST_VIRTUAL + user_test_message - user_test_start
    mov edx, user_test_message_end - user_test_message
    int 0x80
    cmp eax, user_test_message_end - user_test_message
    jne user_test_fail

    mov eax, 13
    int 0x80
    test eax, eax
    jne user_test_fail

    mov eax, 0
    xor ebx, ebx
    int 0x80
    ud2

user_test_fail:
    mov eax, 0
    mov ebx, 1
    int 0x80
    ud2

user_test_message:
    db "[USER] ring3 syscall PASS", 10
user_test_message_end:
user_test_end:

align 16
global user_fault_test_start
global user_fault_test_end

user_fault_test_start:
    mov eax, [0x0BADF000]
    mov eax, 0
    mov ebx, 1
    int 0x80
    ud2
user_fault_test_end:
