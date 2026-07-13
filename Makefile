.DELETE_ON_ERROR:
.DEFAULT_GOAL := all

CROSS_COMPILE ?= i686-elf-
NASM ?= nasm
PYTHON ?= python3
BUILD_DIR ?= build

# GNU Make 会在目标图展开时拆分含空白的路径。必须在展开任何路径和执行
# 任何配方之前明确拒绝，避免半构建或清理错误位置。
ifneq ($(words $(CURDIR)),1)
$(error CURDIR 含空格路径不支持)
endif
ifneq ($(strip $(CURDIR)),$(CURDIR))
$(error CURDIR 含空格路径不支持)
endif
ifneq ($(words $(BUILD_DIR)),1)
$(error BUILD_DIR 含空格路径不支持)
endif
ifneq ($(strip $(BUILD_DIR)),$(BUILD_DIR))
$(error BUILD_DIR 含空格路径不支持)
endif
ifneq ($(words $(CROSS_COMPILE)),1)
$(error CROSS_COMPILE 含空格路径不支持)
endif
ifneq ($(strip $(CROSS_COMPILE)),$(CROSS_COMPILE))
$(error CROSS_COMPILE 含空格路径不支持)
endif
ifneq ($(words $(NASM)),1)
$(error NASM 含空格路径不支持)
endif
ifneq ($(strip $(NASM)),$(NASM))
$(error NASM 含空格路径不支持)
endif
ifneq ($(words $(PYTHON)),1)
$(error PYTHON 含空格路径不支持)
endif
ifneq ($(strip $(PYTHON)),$(PYTHON))
$(error PYTHON 含空格路径不支持)
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

.PHONY: all image clean distclean prepare-build-dir

all: $(ALL_ARTIFACTS) | prepare-build-dir

image: $(IMAGE) | prepare-build-dir

prepare-build-dir:
	@$(PYTHON) tools/build_dir_guard.py prepare --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)"

$(STAGE1_BIN): boot/stage1/boot.asm | prepare-build-dir
	$(NASM) -f bin -o "$@" "$<"

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
	$(PYTHON) tools/make_image.py --layout config/image-layout.json --build-dir $(BUILD_DIR) --output $(BUILD_DIR)/miniorangeos.img

clean:
	@$(PYTHON) tools/build_dir_guard.py clean --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)" --target clean

distclean:
	@$(PYTHON) tools/build_dir_guard.py clean --repo "$(ROOT_DIR)" --build "$(BUILD_DIR)" --target distclean

-include $(STAGE2_DEP) $(KERNEL_ENTRY_DEP) $(KERNEL_CORE_DEP)
