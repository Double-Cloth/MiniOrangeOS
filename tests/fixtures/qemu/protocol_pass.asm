bits 16
org 0x7c00

start:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7c00

    mov dx, 0x3f9
    xor al, al
    out dx, al
    mov dx, 0x3fb
    mov al, 0x80
    out dx, al
    mov dx, 0x3f8
    mov al, 1
    out dx, al
    mov dx, 0x3f9
    xor al, al
    out dx, al
    mov dx, 0x3fb
    mov al, 0x03
    out dx, al
    mov dx, 0x3fa
    mov al, 0xc7
    out dx, al
    mov dx, 0x3fc
    mov al, 0x0b
    out dx, al

    mov si, protocol
.next:
    lodsb
    test al, al
    jz .done
    mov ah, al
.wait:
    mov dx, 0x3fd
    in al, dx
    test al, 0x20
    jz .wait
    mov dx, 0x3f8
    mov al, ah
    out dx, al
    jmp .next
.done:
    cli
.halt:
    hlt
    jmp .halt

protocol:
    db "[TEST] suite=t03_framework begin", 13, 10
    db "[TEST] case=serial_protocol PASS", 13, 10
    db "[TEST] suite=t03_framework PASS", 13, 10
    db "[TEST] all PASS", 13, 10, 0

times 510 - ($ - $$) db 0
dw 0xaa55
