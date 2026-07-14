OUTPUT_FORMAT(elf32-i386)
OUTPUT_ARCH(i386)
ENTRY(kernel_entry)

KERNEL_VIRTUAL_BASE = 0xC0000000;
KERNEL_PHYSICAL_BASE = 0x00100000;

PHDRS
{
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
}

SECTIONS
{
    . = KERNEL_VIRTUAL_BASE + KERNEL_PHYSICAL_BASE;

    .text ALIGN(4096) : AT(ADDR(.text) - KERNEL_VIRTUAL_BASE)
    {
        __text_start = .;
        *(.text*)
        __text_end = .;
    } :text

    .rodata ALIGN(4096) : AT(ADDR(.rodata) - KERNEL_VIRTUAL_BASE)
    {
        __rodata_start = .;
        *(.rodata*)
        __rodata_end = .;
    } :text

    .boot_paging ALIGN(4096) : AT(ADDR(.boot_paging) - KERNEL_VIRTUAL_BASE)
    {
        *(.boot.paging)
    } :data

    .boot_stack ALIGN(4096) : AT(ADDR(.boot_stack) - KERNEL_VIRTUAL_BASE)
    {
        *(.boot.stack)
    } :data

    .data ALIGN(4096) : AT(ADDR(.data) - KERNEL_VIRTUAL_BASE)
    {
        __data_start = .;
        *(.data*)
        __data_end = .;
    } :data

    .bss ALIGN(4096) : AT(ADDR(.bss) - KERNEL_VIRTUAL_BASE)
    {
        __bss_start = .;
        *(COMMON)
        *(.bss*)
        __bss_end = .;
    } :data

    __kernel_virtual_start = KERNEL_VIRTUAL_BASE + KERNEL_PHYSICAL_BASE;
    __kernel_virtual_end = .;

    ASSERT(kernel_entry >= 0xC0000000,
           "Kernel entry must be linked in the high half")
    ASSERT(__kernel_virtual_end <= KERNEL_VIRTUAL_BASE + 0x00400000,
           "Kernel exceeds the 4 MiB early paging window")

    /DISCARD/ :
    {
        *(.comment*)
        *(.note*)
        *(.eh_frame*)
    }
}
