.DELETE_ON_ERROR:
.DEFAULT_GOAL := all

CROSS_COMPILE ?= i686-elf-
NASM ?= nasm
PYTHON ?= python3
BUILD_DIR ?= build
QEMU ?= qemu-system-i386
GDB ?= gdb
QEMU_TIMEOUT ?= 10
QEMU_LOG_MAX_BYTES ?= 1048576
GDB_ENDPOINT ?= tcp:127.0.0.1:1234
KERNEL_TEST_BREAKPOINT ?= 0
KERNEL_TEST_PAGE_FAULT ?= 0
KERNEL_TEST_MINIFS_WRITE ?= 0

# GNU Make 会递归展开命令行变量，Shell 还会解释命令替换和控制字符。
# 必须只检查未展开原值，并在展开任何目标路径或执行任何配方前拒绝。
override make_dollar := $$
override left_parenthesis := (
override right_parenthesis := )
override unsafe_make_value = $(findstring $(make_dollar),$(value $(1)))$(findstring `,$(value $(1)))$(findstring ;,$(value $(1)))$(findstring ",$(value $(1)))$(findstring ',$(value $(1)))$(findstring &,$(value $(1)))$(findstring |,$(value $(1)))$(findstring <,$(value $(1)))$(findstring >,$(value $(1)))$(findstring $(left_parenthesis),$(value $(1)))$(findstring $(right_parenthesis),$(value $(1)))

ifneq ($(call unsafe_make_value,CURDIR),)
$(error CURDIR 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value CURDIR)),1)
$(error CURDIR 含空格路径不支持)
endif
ifneq ($(strip $(value CURDIR)),$(value CURDIR))
$(error CURDIR 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,BUILD_DIR),)
$(error BUILD_DIR 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value BUILD_DIR)),1)
$(error BUILD_DIR 含空格路径不支持)
endif
ifneq ($(strip $(value BUILD_DIR)),$(value BUILD_DIR))
$(error BUILD_DIR 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,CROSS_COMPILE),)
$(error CROSS_COMPILE 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value CROSS_COMPILE)),1)
$(error CROSS_COMPILE 含空格路径不支持)
endif
ifneq ($(strip $(value CROSS_COMPILE)),$(value CROSS_COMPILE))
$(error CROSS_COMPILE 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,NASM),)
$(error NASM 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value NASM)),1)
$(error NASM 含空格路径不支持)
endif
ifneq ($(strip $(value NASM)),$(value NASM))
$(error NASM 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,PYTHON),)
$(error PYTHON 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value PYTHON)),1)
$(error PYTHON 含空格路径不支持)
endif
ifneq ($(strip $(value PYTHON)),$(value PYTHON))
$(error PYTHON 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,QEMU),)
$(error QEMU 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value QEMU)),1)
$(error QEMU 含空格路径不支持)
endif
ifneq ($(strip $(value QEMU)),$(value QEMU))
$(error QEMU 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,GDB),)
$(error GDB 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(words $(value GDB)),1)
$(error GDB 含空格路径不支持)
endif
ifneq ($(strip $(value GDB)),$(value GDB))
$(error GDB 含空格路径不支持)
endif
ifneq ($(call unsafe_make_value,QEMU_TIMEOUT),)
$(error QEMU_TIMEOUT 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(call unsafe_make_value,QEMU_LOG_MAX_BYTES),)
$(error QEMU_LOG_MAX_BYTES 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(call unsafe_make_value,GDB_ENDPOINT),)
$(error GDB_ENDPOINT 含危险字符，不支持作为 Make/Shell 变量)
endif
ifneq ($(call unsafe_make_value,KERNEL_TEST_BREAKPOINT),)
$(error KERNEL_TEST_BREAKPOINT 含危险字符)
endif
ifneq ($(value KERNEL_TEST_BREAKPOINT),0)
ifneq ($(value KERNEL_TEST_BREAKPOINT),1)
$(error KERNEL_TEST_BREAKPOINT 只允许 0 或 1)
endif
endif
ifneq ($(call unsafe_make_value,KERNEL_TEST_PAGE_FAULT),)
$(error KERNEL_TEST_PAGE_FAULT 含危险字符)
endif
ifneq ($(value KERNEL_TEST_PAGE_FAULT),0)
ifneq ($(value KERNEL_TEST_PAGE_FAULT),1)
$(error KERNEL_TEST_PAGE_FAULT 只允许 0 或 1)
endif
endif
ifneq ($(call unsafe_make_value,KERNEL_TEST_MINIFS_WRITE),)
$(error KERNEL_TEST_MINIFS_WRITE 含危险字符)
endif
ifneq ($(value KERNEL_TEST_MINIFS_WRITE),0)
ifneq ($(value KERNEL_TEST_MINIFS_WRITE),1)
$(error KERNEL_TEST_MINIFS_WRITE 只允许 0 或 1)
endif
endif

CC := $(CROSS_COMPILE)gcc
LD := $(CROSS_COMPILE)ld
OBJCOPY := $(CROSS_COMPILE)objcopy
NM := $(CROSS_COMPILE)nm

ROOT_DIR := $(CURDIR)
BUILD_ABS := $(abspath $(BUILD_DIR))

BOOT_BUILD_DIR := $(BUILD_ABS)/boot
BOOT_INCLUDE_DIR := $(ROOT_DIR)/boot/include
STAGE2_BUILD_DIR := $(BOOT_BUILD_DIR)/stage2
KERNEL_BUILD_DIR := $(BUILD_ABS)/kernel
KERNEL_ARCH_BUILD_DIR := $(KERNEL_BUILD_DIR)/arch/x86
KERNEL_BLOCK_BUILD_DIR := $(KERNEL_BUILD_DIR)/block
KERNEL_CORE_BUILD_DIR := $(KERNEL_BUILD_DIR)/core
KERNEL_DRIVERS_BUILD_DIR := $(KERNEL_BUILD_DIR)/drivers
KERNEL_FS_BUILD_DIR := $(KERNEL_BUILD_DIR)/fs
KERNEL_MM_BUILD_DIR := $(KERNEL_BUILD_DIR)/mm
KERNEL_PROC_BUILD_DIR := $(KERNEL_BUILD_DIR)/proc
USER_BUILD_DIR := $(BUILD_ABS)/user
USER_BIN_BUILD_DIR := $(USER_BUILD_DIR)/bin
USER_CRT_BUILD_DIR := $(USER_BUILD_DIR)/crt
USER_LIBC_BUILD_DIR := $(USER_BUILD_DIR)/libc
USER_PROGRAMS_BUILD_DIR := $(USER_BUILD_DIR)/programs
FS_BUILD_DIR := $(BUILD_ABS)/fs

STAGE1_BIN := $(BOOT_BUILD_DIR)/stage1.bin
STAGE1_LAYOUT_INC := $(BOOT_BUILD_DIR)/image-layout.inc
STAGE2_OBJ := $(STAGE2_BUILD_DIR)/entry.o
STAGE2_DEP := $(STAGE2_BUILD_DIR)/entry.d
STAGE2_ELF := $(BOOT_BUILD_DIR)/stage2.elf
STAGE2_BIN := $(BOOT_BUILD_DIR)/stage2.bin
STAGE2_MAP := $(BOOT_BUILD_DIR)/stage2.map
STAGE2_SYM := $(BOOT_BUILD_DIR)/stage2.sym

KERNEL_ENTRY_OBJ := $(KERNEL_ARCH_BUILD_DIR)/entry.o
KERNEL_ENTRY_DEP := $(KERNEL_ARCH_BUILD_DIR)/entry.d
KERNEL_GDT_LOAD_OBJ := $(KERNEL_ARCH_BUILD_DIR)/gdt_load.o
KERNEL_GDT_LOAD_DEP := $(KERNEL_ARCH_BUILD_DIR)/gdt_load.d
KERNEL_GDT_OBJ := $(KERNEL_ARCH_BUILD_DIR)/gdt.o
KERNEL_GDT_DEP := $(KERNEL_ARCH_BUILD_DIR)/gdt.d
KERNEL_EXCEPTION_OBJ := $(KERNEL_ARCH_BUILD_DIR)/exceptions.o
KERNEL_EXCEPTION_DEP := $(KERNEL_ARCH_BUILD_DIR)/exceptions.d
KERNEL_IRQ_OBJ := $(KERNEL_ARCH_BUILD_DIR)/irqs.o
KERNEL_IRQ_DEP := $(KERNEL_ARCH_BUILD_DIR)/irqs.d
KERNEL_CONTEXT_OBJ := $(KERNEL_ARCH_BUILD_DIR)/context_switch.o
KERNEL_CONTEXT_DEP := $(KERNEL_ARCH_BUILD_DIR)/context_switch.d
KERNEL_USER_MODE_OBJ := $(KERNEL_ARCH_BUILD_DIR)/user_mode.o
KERNEL_USER_MODE_DEP := $(KERNEL_ARCH_BUILD_DIR)/user_mode.d
KERNEL_IDT_OBJ := $(KERNEL_ARCH_BUILD_DIR)/idt.o
KERNEL_IDT_DEP := $(KERNEL_ARCH_BUILD_DIR)/idt.d
KERNEL_EXCEPTION_C_OBJ := $(KERNEL_ARCH_BUILD_DIR)/exception.o
KERNEL_EXCEPTION_C_DEP := $(KERNEL_ARCH_BUILD_DIR)/exception.d
KERNEL_IRQ_C_OBJ := $(KERNEL_ARCH_BUILD_DIR)/irq.o
KERNEL_IRQ_C_DEP := $(KERNEL_ARCH_BUILD_DIR)/irq.d
KERNEL_CORE_OBJ := $(KERNEL_CORE_BUILD_DIR)/kernel.o
KERNEL_CORE_DEP := $(KERNEL_CORE_BUILD_DIR)/kernel.d
KERNEL_SYSCALL_OBJ := $(KERNEL_CORE_BUILD_DIR)/syscall.o
KERNEL_SYSCALL_DEP := $(KERNEL_CORE_BUILD_DIR)/syscall.d
KERNEL_CONSOLE_OBJ := $(KERNEL_CORE_BUILD_DIR)/console.o
KERNEL_CONSOLE_DEP := $(KERNEL_CORE_BUILD_DIR)/console.d
KERNEL_PANIC_OBJ := $(KERNEL_CORE_BUILD_DIR)/panic.o
KERNEL_PANIC_DEP := $(KERNEL_CORE_BUILD_DIR)/panic.d
KERNEL_SERIAL_OBJ := $(KERNEL_DRIVERS_BUILD_DIR)/serial.o
KERNEL_SERIAL_DEP := $(KERNEL_DRIVERS_BUILD_DIR)/serial.d
KERNEL_VGA_OBJ := $(KERNEL_DRIVERS_BUILD_DIR)/vga.o
KERNEL_VGA_DEP := $(KERNEL_DRIVERS_BUILD_DIR)/vga.d
KERNEL_PIC_OBJ := $(KERNEL_DRIVERS_BUILD_DIR)/pic.o
KERNEL_PIC_DEP := $(KERNEL_DRIVERS_BUILD_DIR)/pic.d
KERNEL_PIT_OBJ := $(KERNEL_DRIVERS_BUILD_DIR)/pit.o
KERNEL_PIT_DEP := $(KERNEL_DRIVERS_BUILD_DIR)/pit.d
KERNEL_KEYBOARD_OBJ := $(KERNEL_DRIVERS_BUILD_DIR)/keyboard.o
KERNEL_KEYBOARD_DEP := $(KERNEL_DRIVERS_BUILD_DIR)/keyboard.d
KERNEL_ATA_OBJ := $(KERNEL_DRIVERS_BUILD_DIR)/ata.o
KERNEL_ATA_DEP := $(KERNEL_DRIVERS_BUILD_DIR)/ata.d
KERNEL_BLOCK_OBJ := $(KERNEL_BLOCK_BUILD_DIR)/block.o
KERNEL_BLOCK_DEP := $(KERNEL_BLOCK_BUILD_DIR)/block.d
KERNEL_MINIFS_OBJ := $(KERNEL_FS_BUILD_DIR)/minifs.o
KERNEL_MINIFS_DEP := $(KERNEL_FS_BUILD_DIR)/minifs.d
KERNEL_PMM_OBJ := $(KERNEL_MM_BUILD_DIR)/pmm.o
KERNEL_PMM_DEP := $(KERNEL_MM_BUILD_DIR)/pmm.d
KERNEL_VMM_OBJ := $(KERNEL_MM_BUILD_DIR)/vmm.o
KERNEL_VMM_DEP := $(KERNEL_MM_BUILD_DIR)/vmm.d
KERNEL_HEAP_OBJ := $(KERNEL_MM_BUILD_DIR)/heap.o
KERNEL_HEAP_DEP := $(KERNEL_MM_BUILD_DIR)/heap.d
KERNEL_ADDRESS_SPACE_OBJ := $(KERNEL_MM_BUILD_DIR)/address_space.o
KERNEL_ADDRESS_SPACE_DEP := $(KERNEL_MM_BUILD_DIR)/address_space.d
KERNEL_USERCOPY_OBJ := $(KERNEL_MM_BUILD_DIR)/usercopy.o
KERNEL_USERCOPY_DEP := $(KERNEL_MM_BUILD_DIR)/usercopy.d
KERNEL_SCHEDULER_OBJ := $(KERNEL_PROC_BUILD_DIR)/scheduler.o
KERNEL_SCHEDULER_DEP := $(KERNEL_PROC_BUILD_DIR)/scheduler.d
KERNEL_ELF_LOADER_OBJ := $(KERNEL_PROC_BUILD_DIR)/elf.o
KERNEL_ELF_LOADER_DEP := $(KERNEL_PROC_BUILD_DIR)/elf.d
KERNEL_PROGRAM_REGISTRY_OBJ := $(KERNEL_PROC_BUILD_DIR)/program_registry.o
KERNEL_PROGRAM_REGISTRY_DEP := $(KERNEL_PROC_BUILD_DIR)/program_registry.d
KERNEL_EMBEDDED_PROGRAMS_OBJ := $(KERNEL_PROC_BUILD_DIR)/embedded_programs.o
KERNEL_EMBEDDED_PROGRAMS_DEP := $(KERNEL_PROC_BUILD_DIR)/embedded_programs.d
KERNEL_C_OBJECTS := \
	$(KERNEL_GDT_OBJ) \
	$(KERNEL_IDT_OBJ) \
	$(KERNEL_EXCEPTION_C_OBJ) \
	$(KERNEL_IRQ_C_OBJ) \
	$(KERNEL_CORE_OBJ) \
	$(KERNEL_SYSCALL_OBJ) \
	$(KERNEL_CONSOLE_OBJ) \
	$(KERNEL_PANIC_OBJ) \
	$(KERNEL_SERIAL_OBJ) \
	$(KERNEL_VGA_OBJ) \
	$(KERNEL_PIC_OBJ) \
	$(KERNEL_PIT_OBJ) \
	$(KERNEL_KEYBOARD_OBJ) \
	$(KERNEL_ATA_OBJ) \
	$(KERNEL_BLOCK_OBJ) \
	$(KERNEL_MINIFS_OBJ) \
	$(KERNEL_PMM_OBJ) \
	$(KERNEL_VMM_OBJ) \
	$(KERNEL_HEAP_OBJ) \
	$(KERNEL_ADDRESS_SPACE_OBJ) \
	$(KERNEL_USERCOPY_OBJ) \
	$(KERNEL_SCHEDULER_OBJ) \
	$(KERNEL_ELF_LOADER_OBJ) \
	$(KERNEL_PROGRAM_REGISTRY_OBJ)
KERNEL_C_DEPS := \
	$(KERNEL_GDT_DEP) \
	$(KERNEL_IDT_DEP) \
	$(KERNEL_EXCEPTION_C_DEP) \
	$(KERNEL_IRQ_C_DEP) \
	$(KERNEL_CORE_DEP) \
	$(KERNEL_SYSCALL_DEP) \
	$(KERNEL_CONSOLE_DEP) \
	$(KERNEL_PANIC_DEP) \
	$(KERNEL_SERIAL_DEP) \
	$(KERNEL_VGA_DEP) \
	$(KERNEL_PIC_DEP) \
	$(KERNEL_PIT_DEP) \
	$(KERNEL_KEYBOARD_DEP) \
	$(KERNEL_ATA_DEP) \
	$(KERNEL_BLOCK_DEP) \
	$(KERNEL_MINIFS_DEP) \
	$(KERNEL_PMM_DEP) \
	$(KERNEL_VMM_DEP) \
	$(KERNEL_HEAP_DEP) \
	$(KERNEL_ADDRESS_SPACE_DEP) \
	$(KERNEL_USERCOPY_DEP) \
	$(KERNEL_SCHEDULER_DEP) \
	$(KERNEL_ELF_LOADER_DEP) \
	$(KERNEL_PROGRAM_REGISTRY_DEP)
KERNEL_ELF := $(KERNEL_BUILD_DIR)/kernel.elf
KERNEL_BIN := $(KERNEL_BUILD_DIR)/kernel.bin
KERNEL_MAP := $(KERNEL_BUILD_DIR)/kernel.map
KERNEL_SYM := $(KERNEL_BUILD_DIR)/kernel.sym

USER_START_OBJ := $(USER_CRT_BUILD_DIR)/start.o
USER_START_DEP := $(USER_CRT_BUILD_DIR)/start.d
USER_SYSCALL_OBJ := $(USER_LIBC_BUILD_DIR)/syscall.o
USER_SYSCALL_DEP := $(USER_LIBC_BUILD_DIR)/syscall.d
USER_STRING_OBJ := $(USER_LIBC_BUILD_DIR)/string.o
USER_STRING_DEP := $(USER_LIBC_BUILD_DIR)/string.d
USER_INIT_OBJ := $(USER_PROGRAMS_BUILD_DIR)/init.o
USER_INIT_DEP := $(USER_PROGRAMS_BUILD_DIR)/init.d
USER_INIT_ELF := $(USER_BIN_BUILD_DIR)/init.elf
USER_INIT_MAP := $(USER_BIN_BUILD_DIR)/init.map
USER_INIT_SYM := $(USER_BIN_BUILD_DIR)/init.sym
USER_ECHO_OBJ := $(USER_PROGRAMS_BUILD_DIR)/echo.o
USER_ECHO_DEP := $(USER_PROGRAMS_BUILD_DIR)/echo.d
USER_ECHO_ELF := $(USER_BIN_BUILD_DIR)/echo.elf
USER_ECHO_MAP := $(USER_BIN_BUILD_DIR)/echo.map
USER_ECHO_SYM := $(USER_BIN_BUILD_DIR)/echo.sym
USER_SH_OBJ := $(USER_PROGRAMS_BUILD_DIR)/sh.o
USER_SH_DEP := $(USER_PROGRAMS_BUILD_DIR)/sh.d
USER_SH_ELF := $(USER_BIN_BUILD_DIR)/sh.elf
USER_SH_MAP := $(USER_BIN_BUILD_DIR)/sh.map
USER_SH_SYM := $(USER_BIN_BUILD_DIR)/sh.sym
USER_PS_OBJ := $(USER_PROGRAMS_BUILD_DIR)/ps.o
USER_PS_DEP := $(USER_PROGRAMS_BUILD_DIR)/ps.d
USER_PS_ELF := $(USER_BIN_BUILD_DIR)/ps.elf
USER_PS_MAP := $(USER_BIN_BUILD_DIR)/ps.map
USER_PS_SYM := $(USER_BIN_BUILD_DIR)/ps.sym
USER_MEMTEST_OBJ := $(USER_PROGRAMS_BUILD_DIR)/memtest.o
USER_MEMTEST_DEP := $(USER_PROGRAMS_BUILD_DIR)/memtest.d
USER_MEMTEST_ELF := $(USER_BIN_BUILD_DIR)/memtest.elf
USER_MEMTEST_MAP := $(USER_BIN_BUILD_DIR)/memtest.map
USER_MEMTEST_SYM := $(USER_BIN_BUILD_DIR)/memtest.sym
USER_FAULT_OBJ := $(USER_PROGRAMS_BUILD_DIR)/fault.o
USER_FAULT_DEP := $(USER_PROGRAMS_BUILD_DIR)/fault.d
USER_FAULT_ELF := $(USER_BIN_BUILD_DIR)/fault.elf
USER_FAULT_MAP := $(USER_BIN_BUILD_DIR)/fault.map
USER_FAULT_SYM := $(USER_BIN_BUILD_DIR)/fault.sym

MINIFS_IMAGE := $(FS_BUILD_DIR)/minifs.img
MINIFS_LAYOUT_HEADER := $(KERNEL_BUILD_DIR)/minifs-layout.h
IMAGE := $(BUILD_ABS)/miniorangeos.img
QEMU_TEST_FIXTURE := $(BUILD_ABS)/test-fixtures/protocol-pass.img
QEMU_SERIAL_LOG := $(BUILD_ABS)/test-logs/qemu-serial.log

KERNEL_CFLAGS := \
	-I "$(ROOT_DIR)/include" \
	-I "$(ROOT_DIR)/kernel/include" \
	-I "$(KERNEL_BUILD_DIR)" \
	-DMINIOS_TEST_BREAKPOINT=$(KERNEL_TEST_BREAKPOINT) \
	-DMINIOS_TEST_PAGE_FAULT=$(KERNEL_TEST_PAGE_FAULT) \
	-DMINIOS_TEST_MINIFS_WRITE=$(KERNEL_TEST_MINIFS_WRITE) \
	-std=c11 \
	-ffreestanding \
	-fno-builtin \
	-fno-stack-protector \
	-fno-pic \
	-fno-pie \
	-m32 \
	-mno-mmx \
	-mno-sse \
	-mno-sse2 \
	-Wall \
	-Wextra \
	-Wpedantic \
	-Wshadow \
	-Wconversion \
	-Wmissing-prototypes \
	-Wstrict-prototypes \
	-Werror

USER_CFLAGS := \
	-I "$(ROOT_DIR)/include" \
	-I "$(ROOT_DIR)/user/include" \
	-std=c11 \
	-ffreestanding \
	-fno-builtin \
	-fno-stack-protector \
	-fno-pic \
	-fno-pie \
	-m32 \
	-mno-mmx \
	-mno-sse \
	-mno-sse2 \
	-Wall \
	-Wextra \
	-Wpedantic \
	-Wshadow \
	-Wconversion \
	-Wmissing-prototypes \
	-Wstrict-prototypes \
	-Werror

ALL_ARTIFACTS := \
	$(STAGE1_BIN) \
	$(STAGE2_ELF) \
	$(STAGE2_BIN) \
	$(STAGE2_MAP) \
	$(STAGE2_SYM) \
	$(KERNEL_ELF) \
	$(KERNEL_BIN) \
	$(KERNEL_MAP) \
	$(KERNEL_SYM) \
	$(USER_INIT_ELF) \
	$(USER_INIT_MAP) \
	$(USER_INIT_SYM) \
	$(USER_ECHO_ELF) \
	$(USER_ECHO_MAP) \
	$(USER_ECHO_SYM) \
	$(USER_SH_ELF) \
	$(USER_SH_MAP) \
	$(USER_SH_SYM) \
	$(USER_PS_ELF) \
	$(USER_PS_MAP) \
	$(USER_PS_SYM) \
	$(USER_MEMTEST_ELF) \
	$(USER_MEMTEST_MAP) \
	$(USER_MEMTEST_SYM) \
	$(USER_FAULT_ELF) \
	$(USER_FAULT_MAP) \
	$(USER_FAULT_SYM) \
	$(MINIFS_IMAGE)

.PHONY: all image user clean distclean prepare-build-dir run-serial run-curses debug gdb test-qemu test-boot-qemu test-image

all: $(ALL_ARTIFACTS) | prepare-build-dir

image: $(IMAGE) | prepare-build-dir

user: $(USER_INIT_ELF) $(USER_INIT_MAP) $(USER_INIT_SYM) $(USER_ECHO_ELF) $(USER_ECHO_MAP) $(USER_ECHO_SYM) $(USER_SH_ELF) $(USER_SH_MAP) $(USER_SH_SYM) $(USER_PS_ELF) $(USER_PS_MAP) $(USER_PS_SYM) $(USER_MEMTEST_ELF) $(USER_MEMTEST_MAP) $(USER_MEMTEST_SYM) $(USER_FAULT_ELF) $(USER_FAULT_MAP) $(USER_FAULT_SYM) | prepare-build-dir

run-serial: $(IMAGE) | prepare-build-dir
	@$(PYTHON) tools/qemu_run.py --mode serial --qemu "$(QEMU)" --image "$(IMAGE)" --gdb-endpoint "$(GDB_ENDPOINT)" --repo "$(ROOT_DIR)" --build-dir "$(BUILD_DIR)"

run-curses: $(IMAGE) | prepare-build-dir
	@$(PYTHON) tools/qemu_run.py --mode curses --qemu "$(QEMU)" --image "$(IMAGE)" --gdb-endpoint "$(GDB_ENDPOINT)" --repo "$(ROOT_DIR)" --build-dir "$(BUILD_DIR)"

debug: $(IMAGE) | prepare-build-dir
	@$(PYTHON) tools/qemu_run.py --mode debug --qemu "$(QEMU)" --image "$(IMAGE)" --gdb-endpoint "$(GDB_ENDPOINT)" --repo "$(ROOT_DIR)" --build-dir "$(BUILD_DIR)"

gdb: $(KERNEL_ELF) | prepare-build-dir
	@$(PYTHON) tools/qemu_run.py --mode gdb --gdb "$(GDB)" --kernel "$(KERNEL_ELF)" --gdb-endpoint "$(GDB_ENDPOINT)" --repo "$(ROOT_DIR)" --build-dir "$(BUILD_DIR)"

test-qemu: $(QEMU_TEST_FIXTURE) | prepare-build-dir
	@$(PYTHON) tools/qemu_test.py --qemu "$(QEMU)" --image "$(QEMU_TEST_FIXTURE)" --log "$(QEMU_SERIAL_LOG)" --timeout "$(QEMU_TIMEOUT)" --max-log-bytes "$(QEMU_LOG_MAX_BYTES)" --repo "$(ROOT_DIR)" --build-dir "$(BUILD_DIR)"

test-boot-qemu: | prepare-build-dir
	@MINIOS_QEMU="$(QEMU)" $(PYTHON) -m unittest tests.host.test_boot_stage2

test-image: $(IMAGE) | prepare-build-dir
	@$(PYTHON) tools/fsck.py --layout config/image-layout.json --image "$(IMAGE)"
	@$(PYTHON) -m unittest tests.host.test_minifs_tools

prepare-build-dir:
	@$(PYTHON) tools/build_dir_guard.py prepare --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)"

$(STAGE1_LAYOUT_INC): config/image-layout.json tools/generate_boot_layout.py | prepare-build-dir
	$(PYTHON) tools/generate_boot_layout.py --repo "$(ROOT_DIR)" --build-dir "$(BUILD_DIR)" --layout "$<" --output "$@"

$(MINIFS_LAYOUT_HEADER): config/image-layout.json tools/minifs.py tools/generate_minifs_layout.py | prepare-build-dir
	$(PYTHON) tools/generate_minifs_layout.py --layout "$<" --output "$@"

$(STAGE1_BIN): boot/stage1/boot.asm $(STAGE1_LAYOUT_INC) | prepare-build-dir
	$(NASM) -I "$(BOOT_BUILD_DIR)/" -f bin -o "$@" "$<"

$(STAGE2_OBJ): boot/stage2/entry.asm boot/include/boot_info.inc $(STAGE1_LAYOUT_INC) | prepare-build-dir
	$(NASM) -I "$(BOOT_BUILD_DIR)/" -I "$(BOOT_INCLUDE_DIR)/" -f elf32 -MD "$(STAGE2_DEP)" -MT "$@" -o "$@" "$<"

$(STAGE2_ELF) $(STAGE2_MAP) &: $(STAGE2_OBJ) boot/stage2/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T boot/stage2/linker.ld -Map "$(STAGE2_MAP)" -o "$(STAGE2_ELF)" "$(STAGE2_OBJ)"

$(STAGE2_BIN): $(STAGE2_ELF) | prepare-build-dir
	$(OBJCOPY) -O binary "$<" "$@"

$(STAGE2_SYM): $(STAGE2_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(KERNEL_ENTRY_OBJ): kernel/arch/x86/entry.asm boot/include/boot_info.inc | prepare-build-dir
	$(NASM) -I "$(BOOT_INCLUDE_DIR)/" -f elf32 -MD "$(KERNEL_ENTRY_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_GDT_LOAD_OBJ): kernel/arch/x86/gdt.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(KERNEL_GDT_LOAD_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_GDT_OBJ): kernel/arch/x86/gdt.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_GDT_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_EXCEPTION_OBJ): kernel/arch/x86/exceptions.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(KERNEL_EXCEPTION_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_IRQ_OBJ): kernel/arch/x86/irqs.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(KERNEL_IRQ_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_CONTEXT_OBJ): kernel/arch/x86/context_switch.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(KERNEL_CONTEXT_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_USER_MODE_OBJ): kernel/arch/x86/user_mode.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(KERNEL_USER_MODE_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_IDT_OBJ): kernel/arch/x86/idt.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_IDT_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_EXCEPTION_C_OBJ): kernel/arch/x86/exception.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_EXCEPTION_C_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_IRQ_C_OBJ): kernel/arch/x86/irq.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_IRQ_C_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_CORE_OBJ): kernel/core/kernel.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_CORE_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_SYSCALL_OBJ): kernel/core/syscall.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_SYSCALL_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_CONSOLE_OBJ): kernel/core/console.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_CONSOLE_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_PANIC_OBJ): kernel/core/panic.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_PANIC_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_SERIAL_OBJ): kernel/drivers/serial.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_SERIAL_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_VGA_OBJ): kernel/drivers/vga.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_VGA_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_PIC_OBJ): kernel/drivers/pic.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_PIC_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_PIT_OBJ): kernel/drivers/pit.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_PIT_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_KEYBOARD_OBJ): kernel/drivers/keyboard.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_KEYBOARD_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_ATA_OBJ): kernel/drivers/ata.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_ATA_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_BLOCK_OBJ): kernel/block/block.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_BLOCK_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_MINIFS_OBJ): kernel/fs/minifs.c $(MINIFS_LAYOUT_HEADER) | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_MINIFS_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_PMM_OBJ): kernel/mm/pmm.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_PMM_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_VMM_OBJ): kernel/mm/vmm.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_VMM_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_HEAP_OBJ): kernel/mm/heap.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_HEAP_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_ADDRESS_SPACE_OBJ): kernel/mm/address_space.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_ADDRESS_SPACE_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_USERCOPY_OBJ): kernel/mm/usercopy.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_USERCOPY_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_SCHEDULER_OBJ): kernel/proc/scheduler.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_SCHEDULER_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_ELF_LOADER_OBJ): kernel/proc/elf.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_ELF_LOADER_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_PROGRAM_REGISTRY_OBJ): kernel/proc/program_registry.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_PROGRAM_REGISTRY_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_EMBEDDED_PROGRAMS_OBJ): kernel/proc/embedded_programs.asm $(USER_INIT_ELF) $(USER_ECHO_ELF) $(USER_SH_ELF) $(USER_PS_ELF) $(USER_MEMTEST_ELF) $(USER_FAULT_ELF) | prepare-build-dir
	$(NASM) -I "$(USER_BIN_BUILD_DIR)/" -f elf32 -MD "$(KERNEL_EMBEDDED_PROGRAMS_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_ELF) $(KERNEL_MAP) &: $(KERNEL_ENTRY_OBJ) $(KERNEL_GDT_LOAD_OBJ) $(KERNEL_EXCEPTION_OBJ) $(KERNEL_IRQ_OBJ) $(KERNEL_CONTEXT_OBJ) $(KERNEL_USER_MODE_OBJ) $(KERNEL_EMBEDDED_PROGRAMS_OBJ) $(KERNEL_C_OBJECTS) kernel/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T kernel/linker.ld -Map "$(KERNEL_MAP)" -o "$(KERNEL_ELF)" $(KERNEL_ENTRY_OBJ) $(KERNEL_GDT_LOAD_OBJ) $(KERNEL_EXCEPTION_OBJ) $(KERNEL_IRQ_OBJ) $(KERNEL_CONTEXT_OBJ) $(KERNEL_USER_MODE_OBJ) $(KERNEL_EMBEDDED_PROGRAMS_OBJ) $(KERNEL_C_OBJECTS)

$(KERNEL_BIN): $(KERNEL_ELF) | prepare-build-dir
	$(OBJCOPY) -O binary "$<" "$@"

$(KERNEL_SYM): $(KERNEL_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(USER_START_OBJ): user/crt/start.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(USER_START_DEP)" -MT "$@" -o "$@" "$<"

$(USER_SYSCALL_OBJ): user/libc/syscall.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_SYSCALL_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_STRING_OBJ): user/libc/string.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_STRING_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_INIT_OBJ): user/programs/init.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_INIT_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_INIT_ELF) $(USER_INIT_MAP) &: $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_INIT_OBJ) user/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T user/linker.ld -Map "$(USER_INIT_MAP)" -o "$(USER_INIT_ELF)" $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_INIT_OBJ)

$(USER_INIT_SYM): $(USER_INIT_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(USER_ECHO_OBJ): user/programs/echo.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_ECHO_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_ECHO_ELF) $(USER_ECHO_MAP) &: $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_ECHO_OBJ) user/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T user/linker.ld -Map "$(USER_ECHO_MAP)" -o "$(USER_ECHO_ELF)" $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_ECHO_OBJ)

$(USER_ECHO_SYM): $(USER_ECHO_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(USER_SH_OBJ): user/programs/sh.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_SH_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_SH_ELF) $(USER_SH_MAP) &: $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_SH_OBJ) user/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T user/linker.ld -Map "$(USER_SH_MAP)" -o "$(USER_SH_ELF)" $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_SH_OBJ)

$(USER_SH_SYM): $(USER_SH_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(USER_PS_OBJ): user/programs/ps.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_PS_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_PS_ELF) $(USER_PS_MAP) &: $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_PS_OBJ) user/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T user/linker.ld -Map "$(USER_PS_MAP)" -o "$(USER_PS_ELF)" $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_PS_OBJ)

$(USER_PS_SYM): $(USER_PS_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(USER_MEMTEST_OBJ): user/programs/memtest.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_MEMTEST_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_MEMTEST_ELF) $(USER_MEMTEST_MAP) &: $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_MEMTEST_OBJ) user/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T user/linker.ld -Map "$(USER_MEMTEST_MAP)" -o "$(USER_MEMTEST_ELF)" $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_MEMTEST_OBJ)

$(USER_MEMTEST_SYM): $(USER_MEMTEST_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(USER_FAULT_OBJ): user/programs/fault.c | prepare-build-dir
	$(CC) $(USER_CFLAGS) -MMD -MP -MF "$(USER_FAULT_DEP)" -MT "$@" -c "$<" -o "$@"

$(USER_FAULT_ELF) $(USER_FAULT_MAP) &: $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_FAULT_OBJ) user/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T user/linker.ld -Map "$(USER_FAULT_MAP)" -o "$(USER_FAULT_ELF)" $(USER_START_OBJ) $(USER_SYSCALL_OBJ) $(USER_STRING_OBJ) $(USER_FAULT_OBJ)

$(USER_FAULT_SYM): $(USER_FAULT_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(MINIFS_IMAGE): config/image-layout.json tools/minifs.py tools/mkfs.py $(USER_INIT_ELF) $(USER_ECHO_ELF) $(USER_SH_ELF) $(USER_PS_ELF) $(USER_MEMTEST_ELF) $(USER_FAULT_ELF) | prepare-build-dir
	$(PYTHON) tools/mkfs.py --layout config/image-layout.json --output "$@" \
		--import "/bin/init=$(USER_INIT_ELF)" \
		--import "/bin/echo=$(USER_ECHO_ELF)" \
		--import "/bin/sh=$(USER_SH_ELF)" \
		--import "/bin/ps=$(USER_PS_ELF)" \
		--import "/bin/memtest=$(USER_MEMTEST_ELF)" \
		--import "/bin/fault=$(USER_FAULT_ELF)"

$(IMAGE): config/image-layout.json tools/make_image.py $(ALL_ARTIFACTS) | prepare-build-dir
	$(PYTHON) tools/make_image.py --layout config/image-layout.json --build-dir "$(BUILD_DIR)" --output "$(BUILD_DIR)/miniorangeos.img"

$(QEMU_TEST_FIXTURE): tests/fixtures/qemu/protocol_pass.asm | prepare-build-dir
	@mkdir -p "$(dir $@)"
	$(NASM) -f bin -o "$@" "$<"

clean:
	@$(PYTHON) tools/build_dir_guard.py clean --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)" --target clean

distclean:
	@$(PYTHON) tools/build_dir_guard.py clean --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)" --target distclean

-include $(STAGE2_DEP) $(KERNEL_ENTRY_DEP) $(KERNEL_GDT_LOAD_DEP) $(KERNEL_EXCEPTION_DEP) $(KERNEL_IRQ_DEP) $(KERNEL_CONTEXT_DEP) $(KERNEL_USER_MODE_DEP) $(KERNEL_EMBEDDED_PROGRAMS_DEP) $(KERNEL_C_DEPS) $(USER_START_DEP) $(USER_SYSCALL_DEP) $(USER_STRING_DEP) $(USER_INIT_DEP) $(USER_ECHO_DEP) $(USER_SH_DEP) $(USER_PS_DEP) $(USER_MEMTEST_DEP) $(USER_FAULT_DEP)
