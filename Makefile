.DELETE_ON_ERROR:
.DEFAULT_GOAL := all

CROSS_COMPILE ?= i686-elf-
NASM ?= nasm
PYTHON ?= python3
BUILD_DIR ?= build

CC := $(CROSS_COMPILE)gcc
LD := $(CROSS_COMPILE)ld
OBJCOPY := $(CROSS_COMPILE)objcopy
NM := $(CROSS_COMPILE)nm

ROOT_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
BUILD_ABS := $(abspath $(BUILD_DIR))

# 构建和 clean 都只允许操作仓库内部的非根目录。
ifeq ($(filter $(ROOT_DIR)/%,$(BUILD_ABS)),)
$(error BUILD_DIR 必须是仓库内部的非根目录：$(BUILD_DIR))
endif

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

BUILD_DIRECTORIES := \
	$(BOOT_BUILD_DIR) \
	$(STAGE2_BUILD_DIR) \
	$(KERNEL_BUILD_DIR) \
	$(KERNEL_ARCH_BUILD_DIR) \
	$(KERNEL_CORE_BUILD_DIR)

.PHONY: all image clean validate-build-dir

all: $(ALL_ARTIFACTS) | validate-build-dir

image: $(IMAGE) | validate-build-dir

validate-build-dir:
	@root="$$(realpath -e -- "$(ROOT_DIR)")"; \
	target="$$(realpath -m -- "$(BUILD_ABS)")"; \
	case "$$target" in \
		"$$root"/*) ;; \
		*) printf '%s\n' "BUILD_DIR 解析后必须位于仓库内部：$(BUILD_DIR)" >&2; exit 2 ;; \
	esac

$(BUILD_DIRECTORIES): | validate-build-dir
	mkdir -p -- "$@"

$(STAGE1_BIN): boot/stage1/boot.asm | $(BOOT_BUILD_DIR)
	$(NASM) -f bin -o "$@" "$<"

$(STAGE2_OBJ): boot/stage2/entry.asm | $(STAGE2_BUILD_DIR)
	$(NASM) -f elf32 -MD "$(STAGE2_DEP)" -MT "$@" -o "$@" "$<"

$(STAGE2_ELF) $(STAGE2_MAP) &: $(STAGE2_OBJ) boot/stage2/linker.ld | $(BOOT_BUILD_DIR)
	$(LD) -m elf_i386 -nostdlib -T boot/stage2/linker.ld -Map "$(STAGE2_MAP)" -o "$(STAGE2_ELF)" "$(STAGE2_OBJ)"

$(STAGE2_BIN): $(STAGE2_ELF) | $(BOOT_BUILD_DIR)
	$(OBJCOPY) -O binary "$<" "$@"

$(STAGE2_SYM): $(STAGE2_ELF) | $(BOOT_BUILD_DIR)
	$(NM) -n "$<" > "$@"

$(KERNEL_ENTRY_OBJ): kernel/arch/x86/entry.asm | $(KERNEL_ARCH_BUILD_DIR)
	$(NASM) -f elf32 -MD "$(KERNEL_ENTRY_DEP)" -MT "$@" -o "$@" "$<"

$(KERNEL_CORE_OBJ): kernel/core/kernel.c | $(KERNEL_CORE_BUILD_DIR)
	$(CC) $(KERNEL_CFLAGS) -MMD -MP -MF "$(KERNEL_CORE_DEP)" -MT "$@" -c "$<" -o "$@"

$(KERNEL_ELF) $(KERNEL_MAP) &: $(KERNEL_ENTRY_OBJ) $(KERNEL_CORE_OBJ) kernel/linker.ld | $(KERNEL_BUILD_DIR)
	$(LD) -m elf_i386 -nostdlib -T kernel/linker.ld -Map "$(KERNEL_MAP)" -o "$(KERNEL_ELF)" $(KERNEL_ENTRY_OBJ) $(KERNEL_CORE_OBJ)

$(KERNEL_BIN): $(KERNEL_ELF) | $(KERNEL_BUILD_DIR)
	$(OBJCOPY) -O binary "$<" "$@"

$(KERNEL_SYM): $(KERNEL_ELF) | $(KERNEL_BUILD_DIR)
	$(NM) -n "$<" > "$@"

$(IMAGE): config/image-layout.json tools/make_image.py $(ALL_ARTIFACTS) | $(BUILD_ABS)
	$(PYTHON) tools/make_image.py --layout config/image-layout.json --build-dir $(BUILD_DIR) --output $(BUILD_DIR)/miniorangeos.img

$(BUILD_ABS): | validate-build-dir
	mkdir -p -- "$@"

clean: validate-build-dir
	rm -rf -- "$(BUILD_ABS)"

-include $(STAGE2_DEP) $(KERNEL_ENTRY_DEP) $(KERNEL_CORE_DEP)
