#include <minios/arch/x86/io.h>
#include <minios/drivers/vga.h>

#include <stddef.h>
#include <stdint.h>

#define VGA_TEXT_ADDRESS 0xC00B8000
#define VGA_WIDTH 80U
#define VGA_HEIGHT 25U
#define VGA_DEFAULT_COLOR 0x07U
#define VGA_CURSOR_INDEX_PORT 0x03D4
#define VGA_CURSOR_DATA_PORT 0x03D5
#define VGA_CURSOR_HIGH 0x0EU
#define VGA_CURSOR_LOW 0x0FU

enum vga_escape_state {
    VGA_ESCAPE_NONE,
    VGA_ESCAPE_STARTED,
    VGA_ESCAPE_CSI,
    VGA_ESCAPE_CSI_2,
};

static volatile uint16_t *const vga_buffer = (volatile uint16_t *)VGA_TEXT_ADDRESS;
static size_t vga_row;
static size_t vga_column;
static uint8_t vga_color;
static enum vga_escape_state vga_escape;

static uint16_t vga_cell(char character)
{
    return (uint16_t)((uint16_t)vga_color << 8U) | (uint8_t)character;
}

static void vga_update_cursor(void)
{
    uint16_t position = (uint16_t)(vga_row * VGA_WIDTH + vga_column);

    io_out8(VGA_CURSOR_INDEX_PORT, VGA_CURSOR_HIGH);
    io_out8(VGA_CURSOR_DATA_PORT, (uint8_t)(position >> 8U));
    io_out8(VGA_CURSOR_INDEX_PORT, VGA_CURSOR_LOW);
    io_out8(VGA_CURSOR_DATA_PORT, (uint8_t)position);
}

static void vga_clear(void)
{
    size_t index;

    for (index = 0U; index < VGA_WIDTH * VGA_HEIGHT; ++index) {
        vga_buffer[index] = vga_cell(' ');
    }
    vga_row = 0U;
    vga_column = 0U;
}

static void vga_scroll(void)
{
    size_t row;
    size_t column;

    for (row = 1U; row < VGA_HEIGHT; ++row) {
        for (column = 0U; column < VGA_WIDTH; ++column) {
            vga_buffer[(row - 1U) * VGA_WIDTH + column] =
                vga_buffer[row * VGA_WIDTH + column];
        }
    }
    for (column = 0U; column < VGA_WIDTH; ++column) {
        vga_buffer[(VGA_HEIGHT - 1U) * VGA_WIDTH + column] = vga_cell(' ');
    }
    vga_row = VGA_HEIGHT - 1U;
}

void vga_init(void)
{
    vga_color = VGA_DEFAULT_COLOR;
    vga_escape = VGA_ESCAPE_NONE;
    vga_clear();
    vga_update_cursor();
}

void vga_write_char(char character)
{
    if (vga_escape == VGA_ESCAPE_STARTED) {
        vga_escape = character == '[' ? VGA_ESCAPE_CSI : VGA_ESCAPE_NONE;
        return;
    }
    if (vga_escape == VGA_ESCAPE_CSI) {
        if (character == '2') {
            vga_escape = VGA_ESCAPE_CSI_2;
        } else {
            if (character == 'H') {
                vga_row = 0U;
                vga_column = 0U;
                vga_update_cursor();
            }
            vga_escape = VGA_ESCAPE_NONE;
        }
        return;
    }
    if (vga_escape == VGA_ESCAPE_CSI_2) {
        if (character == 'J') {
            vga_clear();
            vga_update_cursor();
        }
        vga_escape = VGA_ESCAPE_NONE;
        return;
    }
    if (character == '\x1B') {
        vga_escape = VGA_ESCAPE_STARTED;
        return;
    }
    if (character == '\r') {
        vga_column = 0U;
        vga_update_cursor();
        return;
    }
    if (character == '\b') {
        if (vga_column > 0U) {
            --vga_column;
        } else if (vga_row > 0U) {
            --vga_row;
            vga_column = VGA_WIDTH - 1U;
        }
        vga_update_cursor();
        return;
    }
    if (character == '\n') {
        vga_column = 0U;
        ++vga_row;
    } else {
        vga_buffer[vga_row * VGA_WIDTH + vga_column] = vga_cell(character);
        ++vga_column;
        if (vga_column == VGA_WIDTH) {
            vga_column = 0U;
            ++vga_row;
        }
    }
    if (vga_row == VGA_HEIGHT) {
        vga_scroll();
    }
    vga_update_cursor();
}
