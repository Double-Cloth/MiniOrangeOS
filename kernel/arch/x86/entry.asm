BITS 32

%include "boot_info.inc"

%define COM1_BASE                   0x03F8
%define COM1_LINE_STATUS            (COM1_BASE + 5)
%define COM1_TRANSMIT_READY         0x20
%define SERIAL_POLL_LIMIT           0x0000FFFF

section .text
global kernel_entry
extern kernel_main

kernel_entry:
    cli
    cmp eax, BOOT_INFO_MAGIC
    jne boot_info_invalid
    cmp ebx, BOOT_INFO_PHYSICAL_ADDRESS
    jne boot_info_invalid
    cmp dword [ebx + BOOT_INFO_MAGIC_OFFSET], BOOT_INFO_MAGIC
    jne boot_info_invalid
    cmp dword [ebx + BOOT_INFO_VERSION_OFFSET], BOOT_INFO_VERSION
    jne boot_info_invalid
    cmp dword [ebx + BOOT_INFO_SIZE_OFFSET], BOOT_INFO_SIZE
    jne boot_info_invalid

    xor edx, edx
    mov esi, ebx
    mov ecx, BOOT_INFO_SIZE / 4
.checksum:
    add edx, [esi]
    add esi, 4
    loop .checksum
    test edx, edx
    jnz boot_info_invalid

    call .success_message_address
.success_message_address:
    pop esi
    add esi, message_boot_info_valid - .success_message_address
    call serial_write_line
    call kernel_main

.halt:
    hlt
    jmp .halt

boot_info_invalid:
    call .failure_message_address
.failure_message_address:
    pop esi
    add esi, message_boot_info_invalid - .failure_message_address
    call serial_write_line
    jmp kernel_entry.halt

serial_write_line:
    call serial_write_string
    mov al, 0x0D
    call serial_write_byte
    mov al, 0x0A
    jmp serial_write_byte

serial_write_string:
    lodsb
    test al, al
    jz .done
    call serial_write_byte
    jmp serial_write_string
.done:
    ret

serial_write_byte:
    push eax
    push ecx
    push edx
    mov ah, al
    mov ecx, SERIAL_POLL_LIMIT
    mov dx, COM1_LINE_STATUS
.wait:
    in al, dx
    test al, COM1_TRANSMIT_READY
    jnz .ready
    loop .wait
    jmp .done
.ready:
    mov al, ah
    mov dx, COM1_BASE
    out dx, al
.done:
    pop edx
    pop ecx
    pop eax
    ret

section .rodata
message_boot_info_valid: db "[KERN] boot info valid", 0
message_boot_info_invalid: db "[KERN] boot info invalid", 0
