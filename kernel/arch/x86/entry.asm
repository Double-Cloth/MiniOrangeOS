BITS 32

%include "boot_info.inc"

%define COM1_BASE                   0x03F8
%define COM1_LINE_STATUS            (COM1_BASE + 5)
%define COM1_TRANSMIT_READY         0x20
%define SERIAL_POLL_LIMIT           0x0000FFFF
%define KERNEL_VIRTUAL_BASE         0xC0000000
%define PAGE_PRESENT                0x00000001
%define PAGE_WRITABLE               0x00000002
%define PAGE_FLAGS                  (PAGE_PRESENT | PAGE_WRITABLE)
%define PAGE_SIZE                   4096
%define PAGE_ENTRY_COUNT            1024
%define HIGH_HALF_PAGE_DIRECTORY    (KERNEL_VIRTUAL_BASE >> 22)
%define BSS_PROBE_DIRTY             0xA5A5A5A5

section .text
global kernel_entry
global kernel_high_entry
extern kernel_main
extern __bss_start
extern __bss_end

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

    mov edi, boot_page_table - KERNEL_VIRTUAL_BASE
    mov eax, PAGE_FLAGS
    mov ecx, PAGE_ENTRY_COUNT
.fill_page_table:
    mov [edi], eax
    add eax, PAGE_SIZE
    add edi, 4
    loop .fill_page_table

    mov edi, boot_page_directory - KERNEL_VIRTUAL_BASE
    xor eax, eax
    mov ecx, PAGE_ENTRY_COUNT
    rep stosd

    mov eax, boot_page_table - KERNEL_VIRTUAL_BASE
    or eax, PAGE_FLAGS
    mov edi, boot_page_directory - KERNEL_VIRTUAL_BASE
    mov [edi], eax
    mov [edi + HIGH_HALF_PAGE_DIRECTORY * 4], eax

    mov dword [kernel_bss_probe - KERNEL_VIRTUAL_BASE], BSS_PROBE_DIRTY

    mov eax, boot_page_directory - KERNEL_VIRTUAL_BASE
    mov cr3, eax
    mov eax, cr0
    or eax, 0x80000000
    mov cr0, eax

    mov eax, kernel_high_entry
    jmp eax

kernel_high_entry:
    mov edi, __bss_start
    mov ecx, __bss_end
    sub ecx, edi
    xor eax, eax
    rep stosb

    mov esp, boot_stack_top
    xor ebp, ebp

    mov esi, message_paging_enabled
    call serial_write_line
    cmp dword [kernel_bss_probe], 0
    jne bss_clear_failed
    mov esi, message_bss_cleared
    call serial_write_line
    call kernel_main

kernel_halt:
    hlt
    jmp kernel_halt

boot_info_invalid:
    call .failure_message_address
.failure_message_address:
    pop esi
    add esi, message_boot_info_invalid - .failure_message_address
    call serial_write_line
    jmp kernel_halt

bss_clear_failed:
    mov esi, message_bss_clear_failed
    call serial_write_line
    jmp kernel_halt

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
message_paging_enabled: db "[KERN] paging enabled", 0
message_bss_cleared: db "[KERN] bss cleared", 0
message_bss_clear_failed: db "[KERN] bss clear failed", 0

section .boot.paging nobits alloc noexec write align=4096
global boot_page_directory
global boot_page_table
boot_page_directory:
    resb PAGE_SIZE
boot_page_table:
    resb PAGE_SIZE

section .boot.stack nobits alloc noexec write align=4096
boot_stack_bottom:
    resb PAGE_SIZE * 4
boot_stack_top:

section .bss
align 4
kernel_bss_probe:
    resd 1
