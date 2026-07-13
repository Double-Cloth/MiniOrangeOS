BITS 16
ORG 0x8000

%define COM1_BASE 0x03F8
%define COM1_LINE_STATUS (COM1_BASE + 5)
%define COM1_TRANSMIT_READY 0x20
%define DEBUG_EXIT_PORT 0x00F4

stage2_entry:
    mov ax, sp
    cmp ax, 0x7C00
    jne handoff_failed

    push cs
    pop ax
    test ax, ax
    jnz handoff_failed
    mov ax, ds
    test ax, ax
    jnz handoff_failed
    mov ax, es
    test ax, ax
    jnz handoff_failed
    mov ax, ss
    test ax, ax
    jnz handoff_failed

    cmp dl, 0x80
    jne handoff_failed
    pushf
    pop ax
    test ax, 0x0600
    jnz handoff_failed

    mov si, message_suite_begin
    call serial_write_line
    mov si, message_case_pass
    call serial_write_line
    mov si, message_suite_pass
    call serial_write_line
    mov si, message_all_pass
    call serial_write_line
    jmp debug_exit

handoff_failed:
    cli
    xor ax, ax
    mov ds, ax
    cld
    mov si, message_suite_begin
    call serial_write_line
    mov si, message_case_fail
    call serial_write_line

debug_exit:
    mov dx, DEBUG_EXIT_PORT
    mov al, 0x10
    out dx, al
.halt:
    cli
    hlt
    jmp .halt

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
    push dx
    mov ah, al
    mov dx, COM1_LINE_STATUS
.wait:
    in al, dx
    test al, COM1_TRANSMIT_READY
    jz .wait
    mov al, ah
    mov dx, COM1_BASE
    out dx, al
    pop dx
    pop ax
    ret

message_suite_begin: db "[TEST] suite=stage1_handoff begin", 0
message_case_pass: db "[TEST] case=registers PASS", 0
message_suite_pass: db "[TEST] suite=stage1_handoff PASS", 0
message_all_pass: db "[TEST] all PASS", 0
message_case_fail: db "[TEST] case=registers FAIL code=E_HANDOFF", 0
