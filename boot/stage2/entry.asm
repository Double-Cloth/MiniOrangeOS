BITS 16

%include "image-layout.inc"
%include "boot_info.inc"

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

%define ATA_DATA_PORT               0x01F0
%define ATA_SECTOR_COUNT_PORT       0x01F2
%define ATA_LBA_LOW_PORT            0x01F3
%define ATA_LBA_MID_PORT            0x01F4
%define ATA_LBA_HIGH_PORT           0x01F5
%define ATA_DRIVE_PORT              0x01F6
%define ATA_STATUS_COMMAND_PORT     0x01F7
%define ATA_ALT_STATUS_PORT         0x03F6
%define ATA_COMMAND_READ_SECTORS    0x20
%define ATA_STATUS_ERROR            0x01
%define ATA_STATUS_DRQ              0x08
%define ATA_STATUS_DEVICE_FAULT     0x20
%define ATA_STATUS_BUSY             0x80
%define ATA_POLL_LIMIT              0x00100000
%define ATA_LBA28_MAX               0x0FFFFFFF

%define SECTOR_SIZE                 512
%define SECTOR_WORD_COUNT           (SECTOR_SIZE / 2)
%define KERNEL_MAX_BYTES            (KERNEL_MAX_SECTORS * SECTOR_SIZE)
%define SECTOR_BUFFER_ADDRESS       0x00020000
%define ELF_HEADER_BUFFER_ADDRESS   0x00020200
%define ELF_PROGRAM_BUFFER_ADDRESS  0x00020240
%define E820_BUFFER_ADDRESS         0x00018000
%define LOADER_RESERVED_START       0x00008000
%define LOADER_RESERVED_END         0x00018000
%define KERNEL_PHYSICAL_MIN         0x00100000
%define KERNEL_VIRTUAL_OFFSET       0xC0000000
%define PAGE_SIZE                   4096
%define PAGE_MASK                   0xFFFFF000

%define ELF_MAGIC                   0x464C457F
%define ELF_CLASS_32                1
%define ELF_DATA_LITTLE_ENDIAN      1
%define ELF_VERSION_CURRENT         1
%define ELF_TYPE_EXECUTABLE         2
%define ELF_MACHINE_386             3
%define ELF_HEADER_SIZE             52
%define ELF_PROGRAM_HEADER_SIZE     32
%define ELF_MAX_PROGRAM_HEADERS     32
%define ELF_PROGRAM_TYPE_LOAD       1
%define ELF_PROGRAM_FLAG_EXECUTE    0x01

%define ELF_IDENT_CLASS_OFFSET      4
%define ELF_IDENT_DATA_OFFSET       5
%define ELF_IDENT_VERSION_OFFSET    6
%define ELF_TYPE_OFFSET             16
%define ELF_MACHINE_OFFSET          18
%define ELF_VERSION_OFFSET          20
%define ELF_ENTRY_OFFSET            24
%define ELF_PROGRAM_OFFSET          28
%define ELF_HEADER_SIZE_OFFSET      40
%define ELF_PROGRAM_SIZE_OFFSET     42
%define ELF_PROGRAM_COUNT_OFFSET    44

%define ELF_PH_TYPE_OFFSET          0
%define ELF_PH_FILE_OFFSET          4
%define ELF_PH_VIRTUAL_OFFSET       8
%define ELF_PH_PHYSICAL_OFFSET      12
%define ELF_PH_FILE_SIZE_OFFSET     16
%define ELF_PH_MEMORY_SIZE_OFFSET   20
%define ELF_PH_FLAGS_OFFSET         24
%define ELF_PH_ALIGN_OFFSET         28

%define LOADER_ERROR_NONE           0
%define LOADER_ERROR_ATA            1
%define LOADER_ERROR_ELF            2

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
message_ata_failure: db "[S2] ATA failure", 0
message_elf_failure: db "[S2] ELF failure", 0
message_kernel_loaded: db "[S2] kernel loaded entry=0x", 0

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

align 4
loader_error: db LOADER_ERROR_NONE
align 4
kernel_entry_virtual: dd 0
kernel_entry_physical: dd 0
kernel_physical_start: dd 0
kernel_physical_end: dd 0
kernel_last_physical_end: dd 0
elf_program_offset: dd 0
elf_program_count: dd 0
elf_program_index: dd 0
elf_load_count: dd 0
read_offset: dd 0
read_remaining: dd 0
read_destination: dd 0
range_usable_found: db 0

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

    mov byte [loader_error], LOADER_ERROR_ATA
    cmp byte [stage2_boot_drive], 0x80
    jne kernel_load_failure
    call load_kernel_elf
    jc kernel_load_failure

    mov esi, message_kernel_loaded
    call serial32_write_string
    mov eax, [kernel_entry_virtual]
    call serial32_write_hex32
    call serial32_write_line_ending

    call build_boot_info
    mov edx, [kernel_entry_physical]
    mov eax, BOOT_INFO_MAGIC
    mov ebx, BOOT_INFO_PHYSICAL_ADDRESS
    jmp edx

kernel_load_failure:
    cmp byte [loader_error], LOADER_ERROR_ATA
    jne .elf
    mov esi, message_ata_failure
    call serial32_write_line
    jmp stage2_protected_entry.halt
.elf:
    mov esi, message_elf_failure
    call serial32_write_line

stage2_protected_entry.halt:
    cli
    hlt
    jmp stage2_protected_entry.halt

section .text32 progbits alloc exec nowrite align=1
serial32_write_line:
    call serial32_write_string
    jmp serial32_write_line_ending

serial32_write_line_ending:
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

serial32_write_hex32:
    push eax
    push ebx
    push ecx
    mov ebx, eax
    mov ecx, 8
.next:
    mov eax, ebx
    shr eax, 28
    call serial32_write_hex_digit
    shl ebx, 4
    loop .next
    pop ecx
    pop ebx
    pop eax
    ret

serial32_write_hex_digit:
    and al, 0x0F
    cmp al, 10
    jb .decimal
    add al, 'A' - 10
    jmp serial32_write_byte
.decimal:
    add al, '0'
    jmp serial32_write_byte

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

; 输入：EAX=LBA28，ES:EDI=512-byte 目标缓冲。返回 CF，成功时 EDI 前进 512 字节。
ata_read_sector:
    push eax
    push ebx
    push ecx
    push edx
    cmp eax, ATA_LBA28_MAX
    ja .failure
    mov ebx, eax

    mov dx, ATA_DRIVE_PORT
    shr eax, 24
    and al, 0x0F
    or al, 0xE0
    out dx, al

    mov dx, ATA_SECTOR_COUNT_PORT
    mov al, 1
    out dx, al
    mov eax, ebx
    mov dx, ATA_LBA_LOW_PORT
    out dx, al
    shr eax, 8
    mov dx, ATA_LBA_MID_PORT
    out dx, al
    shr eax, 8
    mov dx, ATA_LBA_HIGH_PORT
    out dx, al

    mov dx, ATA_STATUS_COMMAND_PORT
    mov al, ATA_COMMAND_READ_SECTORS
    out dx, al

    mov dx, ATA_ALT_STATUS_PORT
    in al, dx
    in al, dx
    in al, dx
    in al, dx

    mov ecx, ATA_POLL_LIMIT
    mov dx, ATA_STATUS_COMMAND_PORT
.poll:
    in al, dx
    test al, ATA_STATUS_BUSY
    jnz .continue
    test al, ATA_STATUS_ERROR | ATA_STATUS_DEVICE_FAULT
    jnz .failure
    test al, ATA_STATUS_DRQ
    jnz .ready
.continue:
    loop .poll
    jmp .failure

.ready:
    mov dx, ATA_DATA_PORT
    mov ecx, SECTOR_WORD_COUNT
    cld
    rep insw
    pop edx
    pop ecx
    pop ebx
    pop eax
    clc
    ret

.failure:
    pop edx
    pop ecx
    pop ebx
    pop eax
    stc
    ret

; 输入：EAX=Kernel ELF 文件偏移，ECX=长度，EDI=目标物理地址。返回 CF。
kernel_read_bytes:
    mov byte [loader_error], LOADER_ERROR_ELF
    mov [read_offset], eax
    mov [read_remaining], ecx
    mov [read_destination], edi
    mov edx, eax
    add edx, ecx
    jc .failure
    cmp edx, KERNEL_MAX_BYTES
    ja .failure

.next:
    mov ecx, [read_remaining]
    test ecx, ecx
    jz .success

    mov eax, [read_offset]
    mov edx, eax
    and edx, SECTOR_SIZE - 1
    shr eax, 9
    add eax, KERNEL_LBA
    jc .failure
    mov edi, SECTOR_BUFFER_ADDRESS
    call ata_read_sector
    jc .ata_failure

    mov ebx, SECTOR_SIZE
    sub ebx, edx
    cmp ebx, [read_remaining]
    jbe .copy
    mov ebx, [read_remaining]
.copy:
    mov esi, SECTOR_BUFFER_ADDRESS
    add esi, edx
    mov edi, [read_destination]
    mov ecx, ebx
    rep movsb
    add [read_offset], ebx
    sub [read_remaining], ebx
    mov [read_destination], edi
    jmp .next

.ata_failure:
    mov byte [loader_error], LOADER_ERROR_ATA
.failure:
    stc
    ret
.success:
    clc
    ret

load_kernel_elf:
    mov byte [loader_error], LOADER_ERROR_ELF
    xor eax, eax
    mov ecx, ELF_HEADER_SIZE
    mov edi, ELF_HEADER_BUFFER_ADDRESS
    call kernel_read_bytes
    jc .failure

    cmp dword [ELF_HEADER_BUFFER_ADDRESS], ELF_MAGIC
    jne .failure
    cmp byte [ELF_HEADER_BUFFER_ADDRESS + ELF_IDENT_CLASS_OFFSET], ELF_CLASS_32
    jne .failure
    cmp byte [ELF_HEADER_BUFFER_ADDRESS + ELF_IDENT_DATA_OFFSET], ELF_DATA_LITTLE_ENDIAN
    jne .failure
    cmp byte [ELF_HEADER_BUFFER_ADDRESS + ELF_IDENT_VERSION_OFFSET], ELF_VERSION_CURRENT
    jne .failure
    cmp word [ELF_HEADER_BUFFER_ADDRESS + ELF_TYPE_OFFSET], ELF_TYPE_EXECUTABLE
    jne .failure
    cmp word [ELF_HEADER_BUFFER_ADDRESS + ELF_MACHINE_OFFSET], ELF_MACHINE_386
    jne .failure
    cmp dword [ELF_HEADER_BUFFER_ADDRESS + ELF_VERSION_OFFSET], ELF_VERSION_CURRENT
    jne .failure
    cmp word [ELF_HEADER_BUFFER_ADDRESS + ELF_HEADER_SIZE_OFFSET], ELF_HEADER_SIZE
    jne .failure
    cmp word [ELF_HEADER_BUFFER_ADDRESS + ELF_PROGRAM_SIZE_OFFSET], ELF_PROGRAM_HEADER_SIZE
    jne .failure

    mov eax, [ELF_HEADER_BUFFER_ADDRESS + ELF_ENTRY_OFFSET]
    cmp eax, KERNEL_VIRTUAL_OFFSET
    jb .failure
    mov [kernel_entry_virtual], eax
    mov eax, [ELF_HEADER_BUFFER_ADDRESS + ELF_PROGRAM_OFFSET]
    mov [elf_program_offset], eax
    movzx ecx, word [ELF_HEADER_BUFFER_ADDRESS + ELF_PROGRAM_COUNT_OFFSET]
    test ecx, ecx
    jz .failure
    cmp ecx, ELF_MAX_PROGRAM_HEADERS
    ja .failure
    mov [elf_program_count], ecx
    shl ecx, 5
    add eax, ecx
    jc .failure
    cmp eax, KERNEL_MAX_BYTES
    ja .failure

    mov dword [elf_program_index], 0
    mov dword [elf_load_count], 0
    mov dword [kernel_entry_physical], 0
    mov dword [kernel_physical_start], 0xFFFFFFFF
    mov dword [kernel_physical_end], 0
    mov dword [kernel_last_physical_end], 0

.program_loop:
    mov eax, [elf_program_index]
    cmp eax, [elf_program_count]
    jae .program_done
    shl eax, 5
    add eax, [elf_program_offset]
    jc .failure
    mov ecx, ELF_PROGRAM_HEADER_SIZE
    mov edi, ELF_PROGRAM_BUFFER_ADDRESS
    call kernel_read_bytes
    jc .failure
    cmp dword [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_TYPE_OFFSET], ELF_PROGRAM_TYPE_LOAD
    jne .program_next
    call load_kernel_segment
    jc .failure
.program_next:
    inc dword [elf_program_index]
    jmp .program_loop

.program_done:
    cmp dword [elf_load_count], 0
    je .failure
    cmp dword [kernel_entry_physical], 0
    je .failure
    cmp dword [kernel_physical_start], 0xFFFFFFFF
    je .failure
    clc
    ret
.failure:
    stc
    ret

load_kernel_segment:
    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_SIZE_OFFSET]
    cmp eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET]
    ja .failure
    cmp dword [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET], 0
    je .ignored

    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    cmp eax, KERNEL_PHYSICAL_MIN
    jb .failure
    cmp eax, [kernel_last_physical_end]
    jb .failure
    mov edx, eax
    add edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET]
    jc .failure
    mov [kernel_last_physical_end], edx
    call physical_range_is_usable
    jc .failure

    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_VIRTUAL_OFFSET]
    mov edx, eax
    add edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET]
    jc .failure
    sub eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    cmp eax, KERNEL_VIRTUAL_OFFSET
    jne .failure

    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_OFFSET]
    mov edx, eax
    add edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_SIZE_OFFSET]
    jc .failure
    cmp edx, KERNEL_MAX_BYTES
    ja .failure

    mov ecx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_ALIGN_OFFSET]
    cmp ecx, 1
    jbe .aligned
    mov ebx, ecx
    dec ebx
    test ecx, ebx
    jnz .failure
    mov edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_VIRTUAL_OFFSET]
    sub edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_OFFSET]
    test edx, ebx
    jnz .failure
    mov edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    sub edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_OFFSET]
    test edx, ebx
    jnz .failure
.aligned:

    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_OFFSET]
    mov ecx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_SIZE_OFFSET]
    mov edi, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    call kernel_read_bytes
    jc .failure

    mov edi, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    add edi, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_SIZE_OFFSET]
    mov ecx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET]
    sub ecx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FILE_SIZE_OFFSET]
    xor eax, eax
    rep stosb

    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    and eax, PAGE_MASK
    cmp eax, [kernel_physical_start]
    jae .start_done
    mov [kernel_physical_start], eax
.start_done:
    mov eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    add eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET]
    add eax, PAGE_SIZE - 1
    jc .failure
    and eax, PAGE_MASK
    cmp eax, [kernel_physical_end]
    jbe .end_done
    mov [kernel_physical_end], eax
.end_done:

    test dword [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_FLAGS_OFFSET], ELF_PROGRAM_FLAG_EXECUTE
    jz .loaded
    mov eax, [kernel_entry_virtual]
    cmp eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_VIRTUAL_OFFSET]
    jb .loaded
    mov edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_VIRTUAL_OFFSET]
    add edx, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_MEMORY_SIZE_OFFSET]
    cmp eax, edx
    jae .loaded
    cmp dword [kernel_entry_physical], 0
    jne .failure
    sub eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_VIRTUAL_OFFSET]
    add eax, [ELF_PROGRAM_BUFFER_ADDRESS + ELF_PH_PHYSICAL_OFFSET]
    jc .failure
    mov [kernel_entry_physical], eax
.loaded:
    inc dword [elf_load_count]
.ignored:
    clc
    ret
.failure:
    stc
    ret

; 输入：EAX=物理起始，EDX=物理结束（exclusive）。成功时 CF=0。
physical_range_is_usable:
    push eax
    push ebx
    push ecx
    push edx
    push esi
    push edi
    push ebp
    mov edi, eax
    mov ebp, edx
    mov esi, E820_BUFFER_ADDRESS
    movzx ebx, word [e820_entry_count]
    mov byte [range_usable_found], 0
.next:
    test ebx, ebx
    jz .done
    cmp dword [esi + 4], 0
    jne .continue
    mov eax, [esi]
    mov ecx, [esi + 8]
    mov edx, [esi + 12]
    add ecx, eax
    adc edx, 0
    cmp dword [esi + 16], 1
    jne .reserved
    cmp eax, edi
    ja .continue
    test edx, edx
    jnz .usable
    cmp ecx, ebp
    jb .continue
.usable:
    mov byte [range_usable_found], 1
    jmp .continue

.reserved:
    cmp eax, ebp
    jae .continue
    test edx, edx
    jnz .failure
    cmp ecx, edi
    ja .failure
.continue:
    add esi, E820_ENTRY_SIZE
    dec ebx
    jmp .next
.done:
    cmp byte [range_usable_found], 1
    jne .failure
.success:
    pop ebp
    pop edi
    pop esi
    pop edx
    pop ecx
    pop ebx
    pop eax
    clc
    ret
.failure:
    pop ebp
    pop edi
    pop esi
    pop edx
    pop ecx
    pop ebx
    pop eax
    stc
    ret

build_boot_info:
    mov edi, BOOT_INFO_PHYSICAL_ADDRESS
    xor eax, eax
    mov ecx, BOOT_INFO_SIZE / 4
    rep stosd
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_MAGIC_OFFSET], BOOT_INFO_MAGIC
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_VERSION_OFFSET], BOOT_INFO_VERSION
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_SIZE_OFFSET], BOOT_INFO_SIZE
    movzx eax, byte [stage2_boot_drive]
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_BOOT_DRIVE_OFFSET], eax
    mov eax, [kernel_entry_virtual]
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_KERNEL_ENTRY_OFFSET], eax
    mov eax, [kernel_entry_physical]
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_KERNEL_PHYS_ENTRY_OFFSET], eax
    mov eax, [kernel_physical_start]
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_KERNEL_PHYS_START_OFFSET], eax
    mov eax, [kernel_physical_end]
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_KERNEL_PHYS_END_OFFSET], eax
    movzx eax, word [e820_entry_count]
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_E820_COUNT_OFFSET], eax
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_E820_ADDRESS_OFFSET], E820_BUFFER_ADDRESS
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_LOADER_START_OFFSET], LOADER_RESERVED_START
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_LOADER_END_OFFSET], LOADER_RESERVED_END
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_KERNEL_LBA_OFFSET], KERNEL_LBA
    mov dword [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_KERNEL_SECTORS_OFFSET], KERNEL_MAX_SECTORS

    xor eax, eax
    mov esi, BOOT_INFO_PHYSICAL_ADDRESS
    mov ecx, BOOT_INFO_SIZE / 4
.checksum:
    add eax, [esi]
    add esi, 4
    loop .checksum
    neg eax
    mov [BOOT_INFO_PHYSICAL_ADDRESS + BOOT_INFO_CHECKSUM_OFFSET], eax
    ret
