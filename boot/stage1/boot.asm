BITS 16
ORG 0x7C00

%include "image-layout.inc"

%define COM1_BASE                   0x03F8
%define COM1_LINE_STATUS            (COM1_BASE + 5)
%define COM1_TRANSMIT_READY         0x20
%define SERIAL_POLL_LIMIT           0xFFFF

%define STAGE2_FIRST_SECTORS        64
%define STAGE2_SECOND_SECTORS       (STAGE2_MAX_SECTORS - STAGE2_FIRST_SECTORS)
%define STAGE2_SECOND_LBA           (STAGE2_LBA + STAGE2_FIRST_SECTORS)

%if STAGE2_MAX_SECTORS <= STAGE2_FIRST_SECTORS
    %error "Stage 1 的双 DAP 读取要求 Stage 2 区域超过 64 扇区"
%endif
%if STAGE2_MAX_SECTORS > 127
    %error "单次 BIOS EDD 读取的 Stage 2 区域不得超过 127 扇区"
%endif

stage1_entry:
    cli
    jmp 0x0000:stage1_normalized

stage1_normalized:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    cld
    mov [boot_drive], dl
    sti

    call serial_initialize
    mov si, message_boot
    call serial_write_line

    ; BIOS EDD 安装检查。AH=41h 的成功契约由 CF、BX 和 CX bit 0 决定。
    mov dl, [boot_drive]
    mov bx, 0x55AA
    mov ah, 0x41
    int 0x13
    jc disk_error
    cmp bx, 0xAA55
    jne disk_error
    test cx, 0x0001
    jz disk_error

    ; 第一段恰好读到物理 0x10000 边界，不跨越 64 KiB DMA 窗口。
    xor ax, ax
    mov ds, ax
    mov si, stage2_first_dap
    mov dl, [boot_drive]
    mov ah, 0x42
    int 0x13
    jc disk_error
    test ah, ah
    jnz disk_error

    ; 第二段从下一个 64 KiB 窗口起始处继续读取剩余扇区。
    xor ax, ax
    mov ds, ax
    mov si, stage2_second_dap
    mov dl, [boot_drive]
    mov ah, 0x42
    int 0x13
    jc disk_error
    test ah, ah
    jnz disk_error

    xor ax, ax
    mov ds, ax
    cld
    mov si, message_loaded
    call serial_write_line

    ; Stage 2 的实模式交接状态保持确定：中断关闭、段基址为零、DF 清零。
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    cld
    mov dl, [boot_drive]
    jmp 0x0000:0x8000

disk_error:
    cli
    xor ax, ax
    mov ds, ax
    cld
    mov si, message_disk_error
    call serial_write_line

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

align 4
stage2_first_dap:
    db 0x10, 0x00
    dw STAGE2_FIRST_SECTORS
    dw 0x0000
    dw 0x0800
    dq STAGE2_LBA

stage2_second_dap:
    db 0x10, 0x00
    dw STAGE2_SECOND_SECTORS
    dw 0x0000
    dw 0x1000
    dq STAGE2_SECOND_LBA

boot_drive: db 0
message_boot: db "[S1] boot", 0
message_loaded: db "[S1] loader loaded", 0
message_disk_error: db "[S1] disk error", 0

times 510 - ($ - $$) db 0
dw 0xAA55
