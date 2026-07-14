#include <minios/arch/x86/io.h>
#include <minios/drivers/keyboard.h>
#include <minios/panic.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PS2_DATA_PORT 0x0060
#define PS2_STATUS_PORT 0x0064
#define PS2_COMMAND_PORT 0x0064
#define PS2_STATUS_OUTPUT_FULL 0x01U
#define PS2_STATUS_INPUT_FULL 0x02U
#define PS2_STATUS_AUXILIARY 0x20U
#define PS2_POLL_LIMIT 0x0000FFFFU
#define PS2_DISABLE_FIRST_PORT 0xADU
#define PS2_DISABLE_SECOND_PORT 0xA7U
#define PS2_ENABLE_FIRST_PORT 0xAEU
#define PS2_READ_CONFIG 0x20U
#define PS2_WRITE_CONFIG 0x60U
#define PS2_SELF_TEST 0xAAU
#define PS2_TEST_FIRST_PORT 0xABU
#define PS2_SELF_TEST_OK 0x55U
#define PS2_PORT_TEST_OK 0x00U
#define PS2_CONFIG_IRQ1 0x01U
#define PS2_CONFIG_IRQ2 0x02U
#define PS2_CONFIG_FIRST_CLOCK_DISABLED 0x10U
#define PS2_CONFIG_TRANSLATION 0x40U
#define KEYBOARD_ENABLE_SCANNING 0xF4U
#define KEYBOARD_ACK 0xFAU
#define SCANCODE_EXTENDED 0xE0U
#define SCANCODE_RELEASE 0x80U
#define SCANCODE_LEFT_SHIFT 0x2AU
#define SCANCODE_RIGHT_SHIFT 0x36U
#define SCANCODE_CAPS_LOCK 0x3AU
#define KEYBOARD_BUFFER_SIZE 64U
#define KEYBOARD_BUFFER_MASK (KEYBOARD_BUFFER_SIZE - 1U)

static const char normal_map[128] = {
    [0x02] = '1', [0x03] = '2', [0x04] = '3', [0x05] = '4',
    [0x06] = '5', [0x07] = '6', [0x08] = '7', [0x09] = '8',
    [0x0A] = '9', [0x0B] = '0', [0x0E] = '\b', [0x0F] = '\t',
    [0x10] = 'q', [0x11] = 'w', [0x12] = 'e', [0x13] = 'r',
    [0x14] = 't', [0x15] = 'y', [0x16] = 'u', [0x17] = 'i',
    [0x18] = 'o', [0x19] = 'p', [0x1C] = '\n', [0x1E] = 'a',
    [0x1F] = 's', [0x20] = 'd', [0x21] = 'f', [0x22] = 'g',
    [0x23] = 'h', [0x24] = 'j', [0x25] = 'k', [0x26] = 'l',
    [0x2C] = 'z', [0x2D] = 'x', [0x2E] = 'c', [0x2F] = 'v',
    [0x30] = 'b', [0x31] = 'n', [0x32] = 'm', [0x39] = ' ',
};

static const char shifted_map[128] = {
    [0x02] = '!', [0x03] = '@', [0x04] = '#', [0x05] = '$',
    [0x06] = '%', [0x07] = '^', [0x08] = '&', [0x09] = '*',
    [0x0A] = '(', [0x0B] = ')',
};

static char input_buffer[KEYBOARD_BUFFER_SIZE];
static volatile uint8_t input_head;
static volatile uint8_t input_tail;
static bool shift_pressed;
static bool caps_lock;
static bool extended_scancode;

static void ps2_wait_input_empty(void)
{
    uint32_t remaining = PS2_POLL_LIMIT;

    while (remaining > 0U) {
        if ((io_in8(PS2_STATUS_PORT) & PS2_STATUS_INPUT_FULL) == 0U) {
            return;
        }
        --remaining;
    }
    panic("PS/2 input timeout");
}

static uint8_t ps2_read_data(void)
{
    uint32_t remaining = PS2_POLL_LIMIT;

    while (remaining > 0U) {
        if ((io_in8(PS2_STATUS_PORT) & PS2_STATUS_OUTPUT_FULL) != 0U) {
            return io_in8(PS2_DATA_PORT);
        }
        --remaining;
    }
    panic("PS/2 output timeout");
}

static void ps2_write_command(uint8_t command)
{
    ps2_wait_input_empty();
    io_out8(PS2_COMMAND_PORT, command);
}

static void ps2_write_data(uint8_t data)
{
    ps2_wait_input_empty();
    io_out8(PS2_DATA_PORT, data);
}

static void ps2_write_config(uint8_t config)
{
    ps2_write_command(PS2_WRITE_CONFIG);
    ps2_write_data(config);
}

static void ps2_flush_output(void)
{
    uint32_t remaining = PS2_POLL_LIMIT;

    while (remaining > 0U &&
           (io_in8(PS2_STATUS_PORT) & PS2_STATUS_OUTPUT_FULL) != 0U) {
        (void)io_in8(PS2_DATA_PORT);
        --remaining;
    }
}

static bool ascii_is_letter(char character)
{
    return character >= 'a' && character <= 'z';
}

static void keyboard_buffer_push(char character)
{
    uint8_t next = (uint8_t)((input_head + 1U) & KEYBOARD_BUFFER_MASK);

    if (next == input_tail) {
        return;
    }
    input_buffer[input_head] = character;
    __asm__ volatile("" : : : "memory");
    input_head = next;
}

void keyboard_init(void)
{
    uint8_t config;

    input_head = 0U;
    input_tail = 0U;
    shift_pressed = false;
    caps_lock = false;
    extended_scancode = false;

    ps2_write_command(PS2_DISABLE_FIRST_PORT);
    ps2_write_command(PS2_DISABLE_SECOND_PORT);
    ps2_flush_output();
    ps2_write_command(PS2_READ_CONFIG);
    config = ps2_read_data();
    config = (uint8_t)(config & ~(PS2_CONFIG_IRQ1 | PS2_CONFIG_IRQ2));
    ps2_write_config(config);

    ps2_write_command(PS2_SELF_TEST);
    if (ps2_read_data() != PS2_SELF_TEST_OK) {
        panic("PS/2 controller self-test failed");
    }
    ps2_write_command(PS2_TEST_FIRST_PORT);
    if (ps2_read_data() != PS2_PORT_TEST_OK) {
        panic("PS/2 first port test failed");
    }

    config = (uint8_t)(config | PS2_CONFIG_IRQ1 | PS2_CONFIG_TRANSLATION);
    config = (uint8_t)(config & ~PS2_CONFIG_FIRST_CLOCK_DISABLED);
    ps2_write_config(config);
    ps2_write_command(PS2_ENABLE_FIRST_PORT);
    ps2_write_data(KEYBOARD_ENABLE_SCANNING);
    if (ps2_read_data() != KEYBOARD_ACK) {
        panic("keyboard enable scanning failed");
    }
}

void keyboard_handle_irq(void)
{
    uint8_t status = io_in8(PS2_STATUS_PORT);
    uint8_t scancode;
    uint8_t code;
    char character;

    if ((status & PS2_STATUS_OUTPUT_FULL) == 0U) {
        return;
    }
    scancode = io_in8(PS2_DATA_PORT);
    if ((status & PS2_STATUS_AUXILIARY) != 0U) {
        return;
    }
    if (scancode == SCANCODE_EXTENDED) {
        extended_scancode = true;
        return;
    }
    code = (uint8_t)(scancode & ~SCANCODE_RELEASE);
    if (code == SCANCODE_LEFT_SHIFT || code == SCANCODE_RIGHT_SHIFT) {
        shift_pressed = (scancode & SCANCODE_RELEASE) == 0U;
        return;
    }
    if ((scancode & SCANCODE_RELEASE) != 0U) {
        extended_scancode = false;
        return;
    }
    if (extended_scancode) {
        extended_scancode = false;
        return;
    }
    if (code == SCANCODE_CAPS_LOCK) {
        caps_lock = !caps_lock;
        return;
    }

    character = shift_pressed && shifted_map[code] != '\0'
        ? shifted_map[code]
        : normal_map[code];
    if (ascii_is_letter(character) && (shift_pressed != caps_lock)) {
        character = (char)(character - 'a' + 'A');
    }
    if (character != '\0') {
        keyboard_buffer_push(character);
    }
}

bool keyboard_try_read(char *character)
{
    if (character == NULL || input_tail == input_head) {
        return false;
    }
    *character = input_buffer[input_tail];
    __asm__ volatile("" : : : "memory");
    input_tail = (uint8_t)((input_tail + 1U) & KEYBOARD_BUFFER_MASK);
    return true;
}
