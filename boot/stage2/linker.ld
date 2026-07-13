OUTPUT_FORMAT(elf32-i386)
OUTPUT_ARCH(i386)
ENTRY(stage2_entry)

PHDRS
{
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
    edd  PT_LOAD FLAGS(5);
}

SECTIONS
{
    . = 0x8000;

    .text16.entry :
    {
        KEEP(*(.text16.entry))
    } :text

    .text : ALIGN(16)
    {
        *(.text16)
        *(.text)
        *(.text.*)
    } :text

    .rodata : ALIGN(16)
    {
        *(.rodata16*)
        *(.rodata*)
    } :text

    .data : ALIGN(16)
    {
        *(.data16*)
        *(.data*)
    } :data

    /* 让 EDD 包装器成为最后一段实模式代码，返回路径不会混入数据。 */
    .text16.edd :
    {
        *(.text16.edd)
    } :edd

    .bss : ALIGN(16)
    {
        *(COMMON)
        *(.bss16*)
        *(.bss*)
    } :data

    __stage2_real_mode_end = .;

    ASSERT(stage2_entry == 0x8000,
           "Stage 2 entry must remain at physical address 0x8000")
    ASSERT(__stage2_real_mode_end <= 0x10000,
           "Stage 2 real-mode image exceeds the 16-bit absolute address range")

    /DISCARD/ :
    {
        *(.comment*)
        *(.note*)
        *(.eh_frame*)
    }
}
