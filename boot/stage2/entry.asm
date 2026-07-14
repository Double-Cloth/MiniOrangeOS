BITS 16

%define COM1_BASE                   0x03F8
%define COM1_LINE_STATUS            (COM1_BASE + 5)
%define COM1_TRANSMIT_READY         0x20
%define SERIAL_POLL_LIMIT           0xFFFF

%define A20_TEST_LOW_OFFSET         0x0500
%define A20_TEST_HIGH_SEGMENT       0xFFFF
%define A20_TEST_HIGH_OFFSET        0x0510
%define A20_FAST_GATE_PORT          0x0092
%define A20_FAST_GATE_ENABLE        0x02
%define A20_FAST_GATE_RESET_MASK    0xFE

%define E820_FUNCTION               0xE820
%define E820_SIGNATURE              0x534D4150
%define E820_BUFFER_SEGMENT         0x1800
%define E820_ENTRY_SIZE             24
%define E820_MIN_ENTRY_SIZE         20
%define E820_MAX_ENTRIES            128

%define GDT_CODE_SELECTOR           0x08
%define GDT_DATA_SELECTOR           0x10
%define PROTECTED_MODE_STACK_TOP    0x00007000

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

    call enable_a20
    jc a20_failure
    mov si, message_a20_enabled
    call serial_write_line

    call collect_e820
    jc e820_failure
    mov si, message_e820_entries
    call serial_write_string
    mov ax, [e820_entry_count]
    call serial_write_hex16
    call serial_write_line_ending

    ; BIOS 服务到此结束。加载临时 GDT 后，通过远跳转进入 32 位平坦代码段。
    cli
    lgdt [gdt_descriptor]
    mov eax, cr0
    or eax, 0x00000001
    mov cr0, eax
    jmp dword GDT_CODE_SELECTOR:stage2_protected_entry

a20_failure:
    mov si, message_a20_failure
    call serial_write_line
    jmp halt16

e820_failure:
    mov si, message_e820_failure
    call serial_write_line

halt16:
    cli
.halt:
    hlt
    jmp .halt

section .text16 progbits alloc exec nowrite align=1
global bios_write_char
global bios_disk_read_edd

; 输入：AL=字符。使用 BIOS teletype 服务并保留所有通用/段寄存器；flags 未定义。
bios_write_char:
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    mov ah, 0x0E
    xor bh, bh
    mov bl, 0x07
    int 0x10
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
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
; 返回：AX=1 表示 0x00000500 与 0x00100500 不再别名；AX=0 表示 A20 关闭。
; 函数在关中断窗口内恢复两个探测字节，并恢复调用者 flags 与除 AX 外的寄存器。
a20_is_enabled:
    pushf
    cli
    push bx
    push si
    push di
    push ds
    push es

    xor ax, ax
    mov ds, ax
    mov ax, A20_TEST_HIGH_SEGMENT
    mov es, ax
    mov si, A20_TEST_LOW_OFFSET
    mov di, A20_TEST_HIGH_OFFSET

    mov bl, [ds:si]
    mov bh, [es:di]
    mov byte [ds:si], 0x00
    mov byte [es:di], 0xFF
    cmp byte [ds:si], 0xFF
    mov byte [es:di], bh
    mov byte [ds:si], bl

    mov ax, 0
    je .restore
    mov ax, 1
.restore:
    pop es
    pop ds
    pop di
    pop si
    pop bx
    popf
    ret

; 返回：CF=0 表示 A20 已验证开启；CF=1 表示 BIOS 与 Fast A20 路径均失败。
enable_a20:
    call a20_is_enabled
    test ax, ax
    jnz .success

    mov ax, 0x2401
    int 0x15
    xor ax, ax
    mov ds, ax
    call a20_is_enabled
    test ax, ax
    jnz .success

    in al, A20_FAST_GATE_PORT
    or al, A20_FAST_GATE_ENABLE
    and al, A20_FAST_GATE_RESET_MASK
    out A20_FAST_GATE_PORT, al
    call a20_is_enabled
    test ax, ax
    jnz .success

    stc
    ret
.success:
    clc
    ret

; 返回：CF=0 且 e820_entry_count>0 表示成功；CF=1 表示 BIOS 数据无效或缓冲已满。
; 每个保留条目固定占 24 字节，目标物理缓冲为 0x00018000。
collect_e820:
    push es
    mov ax, E820_BUFFER_SEGMENT
    mov es, ax
    xor di, di
    xor ebx, ebx
    xor bp, bp

.next:
    cmp bp, E820_MAX_ENTRIES
    jae .failure
    mov dword [es:di + 20], 1
    mov eax, E820_FUNCTION
    mov edx, E820_SIGNATURE
    mov ecx, E820_ENTRY_SIZE
    push ds
    push es
    push di
    push bp
    int 0x15
    pop bp
    pop di
    pop es
    pop ds
    jc .failure
    cmp eax, E820_SIGNATURE
    jne .failure
    cmp ecx, E820_MIN_ENTRY_SIZE
    jb .failure

    ; 24-byte ACPI 3.x 条目若明确标记为无效，则不计入交付缓冲。
    cmp ecx, E820_ENTRY_SIZE
    jb .validate_range
    test dword [es:di + 20], 1
    jz .continue

    ; 忽略空区间；对非空区间拒绝 64 位 base+length 回绕。
.validate_range:
    mov eax, [es:di + 8]
    mov edx, [es:di + 12]
    or eax, edx
    jz .continue
    mov eax, [es:di]
    mov edx, [es:di + 4]
    add eax, [es:di + 8]
    adc edx, [es:di + 12]
    jc .failure

    cmp ecx, E820_ENTRY_SIZE
    jae .store
    mov dword [es:di + 20], 1
.store:
    inc bp
    add di, E820_ENTRY_SIZE

.continue:
    test ebx, ebx
    jnz .next
    test bp, bp
    jz .failure
    mov [cs:e820_entry_count], bp
    pop es
    clc
    ret

.failure:
    mov word [cs:e820_entry_count], 0
    pop es
    stc
    ret

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

serial_write_hex16:
    push ax
    mov al, ah
    call serial_write_hex8
    pop ax
    jmp serial_write_hex8

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
message_a20_enabled: db "[S2] A20 enabled", 0
message_a20_failure: db "[S2] A20 failure", 0
message_e820_entries: db "[S2] E820 entries=0x", 0
message_e820_failure: db "[S2] E820 failure", 0
message_protected_mode: db "[S2] protected mode entered", 0

align 8
gdt_start:
    dq 0x0000000000000000
    dq 0x00CF9A000000FFFF
    dq 0x00CF92000000FFFF
gdt_end:

gdt_descriptor:
    dw gdt_end - gdt_start - 1
    dd gdt_start

section .data16 progbits alloc noexec write align=1
global stage2_boot_drive
stage2_boot_drive: db 0
global e820_entry_count
e820_entry_count: dw 0

BITS 32

section .text32.entry progbits alloc exec nowrite align=16
global stage2_protected_entry

stage2_protected_entry:
    mov ax, GDT_DATA_SELECTOR
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov esp, PROTECTED_MODE_STACK_TOP
    cld

    mov esi, message_protected_mode
    call serial32_write_line

    cli
.halt:
    hlt
    jmp .halt

section .text32 progbits alloc exec nowrite align=1
serial32_write_line:
    call serial32_write_string
    mov al, 0x0D
    call serial32_write_byte
    mov al, 0x0A
    jmp serial32_write_byte

serial32_write_string:
    lodsb
    test al, al
    jz .done
    call serial32_write_byte
    jmp serial32_write_string
.done:
    ret

serial32_write_byte:
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
