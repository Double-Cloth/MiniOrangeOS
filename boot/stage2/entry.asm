BITS 16

%define COM1_BASE                   0x03F8
%define COM1_LINE_STATUS            (COM1_BASE + 5)
%define COM1_TRANSMIT_READY         0x20
%define SERIAL_POLL_LIMIT           0xFFFF

section .text16.entry progbits alloc exec nowrite align=1
global stage2_entry

stage2_entry:
    cli

    ; DL 是 Stage 1 交给 Loader 的 BIOS 启动盘号，必须在任何调用前保存。
    mov [cs:stage2_boot_drive], dl

    ; Stage 2 不沿用 Stage 1 的 0x7C00 栈，实模式段基址统一为零。
    xor ax, ax
    mov ss, ax
    mov sp, 0x7000
    mov ds, ax
    mov es, ax
    cld
    sti

    call serial_initialize
    mov si, message_loader_entered
    call serial_write_line

    mov si, message_boot_drive
    call serial_write_string
    mov al, [stage2_boot_drive]
    call serial_write_hex8
    call serial_write_line_ending

    ; T11 到此停止，后续任务再加入 A20、E820 和保护模式切换。
    cli
.halt:
    hlt
    jmp .halt

section .text16 progbits alloc exec nowrite align=1
global bios_write_char
global bios_disk_read_edd

; 输入：AL=字符。使用 BIOS teletype 服务，不依赖调用者的 BX/段寄存器。
bios_write_char:
    push ax
    push bx
    push ds
    push es
    mov ah, 0x0E
    xor bh, bh
    mov bl, 0x07
    int 0x10
    pop es
    pop ds
    pop bx
    pop ax
    ret

; 输入：DS:SI=16-byte EDD DAP。
; 输出：CF 表示成功/失败，AH 保留 BIOS 状态码；其余通用寄存器和段寄存器恢复。
section .text16.edd progbits alloc exec nowrite align=1
bios_disk_read_edd:
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    mov dl, [cs:stage2_boot_drive]
    mov ah, 0x42
    int 0x13
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    ret

section .text16 progbits alloc exec nowrite align=1
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
    jmp serial_write_line_ending

serial_write_line_ending:
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

serial_write_hex8:
    push ax
    mov ah, al
    shr al, 4
    call serial_write_hex_digit
    mov al, ah
    and al, 0x0F
    call serial_write_hex_digit
    pop ax
    ret

serial_write_hex_digit:
    and al, 0x0F
    cmp al, 10
    jb .decimal
    add al, 'A' - 10
    jmp serial_write_byte
.decimal:
    add al, '0'
    jmp serial_write_byte

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

section .rodata16 progbits alloc noexec nowrite align=1
message_loader_entered: db "[S2] loader entered", 0
message_boot_drive: db "[S2] boot drive=0x", 0

section .data16 progbits alloc noexec write align=1
global stage2_boot_drive
stage2_boot_drive: db 0
