#include <minios/drivers/vga.h>

#include <stddef.h>
#include <stdint.h>

#define VGA_TEXT_ADDRESS 0xC00B8000
#define VGA_WIDTH 80U
#define VGA_HEIGHT 25U
#define VGA_DEFAULT_COLOR 0x07U

static volatile uint16_t *const vga_buffer = (volatile uint16_t *)VGA_TEXT_ADDRESS;
static size_t vga_row;
static size_t vga_column;
static uint8_t vga_color;

static uint16_t vga_cell(char character)
{
    return (uint16_t)((uint16_t)vga_color << 8U) | (uint8_t)character;
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
    size_t index;

    vga_row = 0U;
    vga_column = 0U;
    vga_color = VGA_DEFAULT_COLOR;
    for (index = 0U; index < VGA_WIDTH * VGA_HEIGHT; ++index) {
        vga_buffer[index] = vga_cell(' ');
    }
}

void vga_write_char(char character)
{
    if (character == '\r') {
        vga_column = 0U;
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
}
