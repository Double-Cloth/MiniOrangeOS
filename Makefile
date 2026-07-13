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

CC := $(CROSS_COMPILE)gcc
LD := $(CROSS_COMPILE)ld
OBJCOPY := $(CROSS_COMPILE)objcopy
NM := $(CROSS_COMPILE)nm

ROOT_DIR := $(CURDIR)
BUILD_ABS := $(abspath $(BUILD_DIR))

BOOT_BUILD_DIR := $(BUILD_ABS)/boot
STAGE2_BUILD_DIR := $(BOOT_BUILD_DIR)/stage2
KERNEL_BUILD_DIR := $(BUILD_ABS)/kernel
KERNEL_ARCH_BUILD_DIR := $(KERNEL_BUILD_DIR)/arch/x86
KERNEL_CORE_BUILD_DIR := $(KERNEL_BUILD_DIR)/core

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
KERNEL_CORE_OBJ := $(KERNEL_CORE_BUILD_DIR)/kernel.o
KERNEL_CORE_DEP := $(KERNEL_CORE_BUILD_DIR)/kernel.d
KERNEL_ELF := $(KERNEL_BUILD_DIR)/kernel.elf
KERNEL_BIN := $(KERNEL_BUILD_DIR)/kernel.bin
KERNEL_MAP := $(KERNEL_BUILD_DIR)/kernel.map
KERNEL_SYM := $(KERNEL_BUILD_DIR)/kernel.sym

IMAGE := $(BUILD_ABS)/miniorangeos.img
QEMU_TEST_FIXTURE := $(BUILD_ABS)/test-fixtures/protocol-pass.img
QEMU_SERIAL_LOG := $(BUILD_ABS)/test-logs/qemu-serial.log

KERNEL_CFLAGS := \
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
	$(KERNEL_SYM)

.PHONY: all image clean distclean prepare-build-dir run-serial run-curses debug gdb test-qemu

all: $(ALL_ARTIFACTS) | prepare-build-dir

image: $(IMAGE) | prepare-build-dir

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

prepare-build-dir:
	@$(PYTHON) tools/build_dir_guard.py prepare --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)"

$(STAGE1_LAYOUT_INC): config/image-layout.json tools/generate_boot_layout.py | prepare-build-dir
	$(PYTHON) tools/generate_boot_layout.py --layout "$<" --output "$@"

$(STAGE1_BIN): boot/stage1/boot.asm $(STAGE1_LAYOUT_INC) | prepare-build-dir
	$(NASM) -I "$(BOOT_BUILD_DIR)/" -f bin -o "$@" "$<"

$(STAGE2_OBJ): boot/stage2/entry.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(STAGE2_DEP)" -MT "$@" -o "$@" "$<"

$(STAGE2_ELF) $(STAGE2_MAP) &: $(STAGE2_OBJ) boot/stage2/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T boot/stage2/linker.ld -Map "$(STAGE2_MAP)" -o "$(STAGE2_ELF)" "$(STAGE2_OBJ)"

$(STAGE2_BIN): $(STAGE2_ELF) | prepare-build-dir
	$(OBJCOPY) -O binary "$<" "$@"

$(STAGE2_SYM): $(STAGE2_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(KERNEL_ENTRY_OBJ): kernel/arch/x86/entry.asm | prepare-build-dir
	$(NASM) -f elf32 -MD "$(KERNEL_ENTRY_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_CORE_OBJ): kernel/core/kernel.c | prepare-build-dir
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_CORE_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_ELF) $(KERNEL_MAP) &: $(KERNEL_ENTRY_OBJ) $(KERNEL_CORE_OBJ) kernel/linker.ld | prepare-build-dir
	$(LD) -m elf_i386 -nostdlib -T kernel/linker.ld -Map "$(KERNEL_MAP)" -o "$(KERNEL_ELF)" $(KERNEL_ENTRY_OBJ) $(KERNEL_CORE_OBJ)

$(KERNEL_BIN): $(KERNEL_ELF) | prepare-build-dir
	$(OBJCOPY) -O binary "$<" "$@"

$(KERNEL_SYM): $(KERNEL_ELF) | prepare-build-dir
	$(NM) -n "$<" > "$@"

$(IMAGE): config/image-layout.json tools/make_image.py $(ALL_ARTIFACTS) | prepare-build-dir
	$(PYTHON) tools/make_image.py --layout config/image-layout.json --build-dir "$(BUILD_DIR)" --output "$(BUILD_DIR)/miniorangeos.img"

$(QEMU_TEST_FIXTURE): tests/fixtures/qemu/protocol_pass.asm | prepare-build-dir
	@mkdir -p "$(dir $@)"
	$(NASM) -f bin -o "$@" "$<"

clean:
	@$(PYTHON) tools/build_dir_guard.py clean --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)" --target clean

distclean:
	@$(PYTHON) tools/build_dir_guard.py clean --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)" --target distclean

-include $(STAGE2_DEP) $(KERNEL_ENTRY_DEP) $(KERNEL_CORE_DEP)
