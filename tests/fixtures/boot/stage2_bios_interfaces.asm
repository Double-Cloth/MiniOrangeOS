BITS 16

%define COM1_BASE 0x03F8
%define COM1_LINE_STATUS (COM1_BASE + 5)
%define COM1_TRANSMIT_READY 0x20
%define SERIAL_POLL_LIMIT 0xFFFF
%define EDD_BUFFER 0x5000

extern bios_write_char
extern bios_disk_read_edd
extern stage2_boot_drive

section .fixture.entry progbits alloc exec nowrite align=1
global fixture_entry

fixture_entry:
    cli
    mov [cs:stage2_boot_drive], dl
    xor ax, ax
    mov ss, ax
    mov sp, 0x7000
    mov ds, ax
    mov es, ax
    cld

    call serial_initialize
    mov si, message_suite_begin
    call serial_write_line

    ; AL 是 teletype 字符，正式接口承诺恢复所有通用寄存器和段寄存器。
    mov ax, 0x5142
    mov bx, 0x1234
    mov cx, 0x5678
    mov dx, 0x789A
    mov si, 0x3456
    mov di, 0x4567
    mov bp, 0x5A5A
    mov [expected_sp], sp
    call bios_write_char
    cmp ax, 0x5142
    jne character_failed
    cmp bx, 0x1234
    jne character_failed
    cmp cx, 0x5678
    jne character_failed
    cmp dx, 0x789A
    jne character_failed
    cmp si, 0x3456
    jne character_failed
    cmp di, 0x4567
    jne character_failed
    cmp bp, 0x5A5A
    jne character_failed
    cmp sp, [expected_sp]
    jne character_failed
    push ds
    pop ax
    test ax, ax
    jne character_failed
    push es
    pop ax
    test ax, ax
    jne character_failed

    mov si, message_character_pass
    call serial_write_line

    ; 通过正式 EDD wrapper 把 LBA0 读到不会覆盖 Loader/栈的缓冲区。
    mov si, edd_dap
    mov bx, 0x1357
    mov cx, 0x2468
    mov dx, 0x369A
    mov di, 0x47AB
    mov bp, 0x58BC
    mov ax, 0x2345
    mov es, ax
    mov [expected_sp], sp
    call bios_disk_read_edd
    pushf
    pop word [edd_flags]
    mov [edd_status], ah

    test word [edd_flags], 0x0001
    jnz disk_failed
    cmp byte [edd_status], 0
    jne disk_failed
    cmp bx, 0x1357
    jne disk_failed
    cmp cx, 0x2468
    jne disk_failed
    cmp dx, 0x369A
    jne disk_failed
    cmp si, edd_dap
    jne disk_failed
    cmp di, 0x47AB
    jne disk_failed
    cmp bp, 0x58BC
    jne disk_failed
    cmp sp, [expected_sp]
    jne disk_failed
    push ds
    pop ax
    test ax, ax
    jne disk_failed
    push es
    pop ax
    cmp ax, 0x2345
    jne disk_failed
    cmp word [EDD_BUFFER + 510], 0xAA55
    jne disk_failed

    mov si, message_disk_pass
    call serial_write_line
    mov si, message_suite_pass
    call serial_write_line
    mov si, message_all_pass
    call serial_write_line
    jmp debug_exit

character_failed:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov si, message_character_fail
    call serial_write_line
    jmp debug_exit

disk_failed:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov si, message_disk_fail
    call serial_write_line

debug_exit:
    mov dx, 0x00F4
    mov al, 0x10
    out dx, al
    cli
.halt:
    hlt
    jmp .halt

serial_initialize:
    mov dx, COM1_BASE + 1
    xor al, al
    out dx, al
    mov dx, COM1_BASE + 3
    mov al, 0x80
    out dx, al
    mov dx, COM1_BASE
    mov al, 0x03
    out dx, al
    mov dx, COM1_BASE + 1
    xor al, al
    out dx, al
    mov dx, COM1_BASE + 3
    mov al, 0x03
    out dx, al
    mov dx, COM1_BASE + 2
    mov al, 0xC7
    out dx, al
    mov dx, COM1_BASE + 4
    mov al, 0x0B
    out dx, al
    ret

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
    push ax
    push cx
    push dx
    mov ah, al
    mov cx, SERIAL_POLL_LIMIT
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
    pop dx
    pop cx
    pop ax
    ret

section .fixture.data progbits alloc noexec write align=4
expected_sp: dw 0
edd_flags: dw 0
edd_status: db 0

align 4
edd_dap:
    db 0x10, 0x00
    dw 1
    dw EDD_BUFFER
    dw 0x0000
    dq 0

message_suite_begin: db "[TEST] suite=t11_bios_interfaces begin", 0
message_character_pass: db "[TEST] case=bios_write_char PASS", 0
message_character_fail: db "[TEST] case=bios_write_char FAIL", 0
message_disk_pass: db "[TEST] case=bios_disk_read_edd PASS", 0
message_disk_fail: db "[TEST] case=bios_disk_read_edd FAIL", 0
message_suite_pass: db "[TEST] suite=t11_bios_interfaces PASS", 0
message_all_pass: db "[TEST] all PASS", 0
