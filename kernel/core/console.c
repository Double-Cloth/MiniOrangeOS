#include <minios/console.h>
#include <minios/drivers/serial.h>
#include <minios/drivers/vga.h>

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>

/* 最小格式集合：%s %c %u %d %x %p %% */

static void console_write_unsigned(uint32_t value, uint32_t base, size_t minimum_width)
{
    static const char digits[] = "0123456789abcdef";
    char reversed[32];
    size_t length = 0U;

    do {
        reversed[length] = digits[value % base];
        ++length;
        value /= base;
    } while (value != 0U);

    while (length < minimum_width) {
        reversed[length] = '0';
        ++length;
    }
    while (length > 0U) {
        --length;
        console_putc(reversed[length]);
    }
}

static void console_write_signed(int32_t value)
{
    uint32_t magnitude;

    if (value < 0) {
        console_putc('-');
        magnitude = (uint32_t)(-(value + 1)) + 1U;
    } else {
        magnitude = (uint32_t)value;
    }
    console_write_unsigned(magnitude, 10U, 1U);
}

void console_init(void)
{
    serial_init();
    vga_init();
}

void console_putc(char character)
{
    if (character == '\n') {
        serial_write_char('\r');
    }
    serial_write_char(character);
    vga_write_char(character);
}

void console_write(const char *text)
{
    if (text == NULL) {
        text = "(null)";
    }
    while (*text != '\0') {
        console_putc(*text);
        ++text;
    }
}

void console_vprintf(const char *format, va_list arguments)
{
    if (format == NULL) {
        console_write("(null)");
        return;
    }

    while (*format != '\0') {
        char specifier;

        if (*format != '%') {
            console_putc(*format);
            ++format;
            continue;
        }
        ++format;
        specifier = *format;
        if (specifier == '\0') {
            console_putc('%');
            return;
        }

        switch (specifier) {
        case 's':
            console_write(va_arg(arguments, const char *));
            break;
        case 'c':
            console_putc((char)va_arg(arguments, int));
            break;
        case 'u':
            console_write_unsigned(va_arg(arguments, uint32_t), 10U, 1U);
            break;
        case 'd':
            console_write_signed(va_arg(arguments, int32_t));
            break;
        case 'x':
            console_write_unsigned(va_arg(arguments, uint32_t), 16U, 1U);
            break;
        case 'p':
            console_write("0x");
            console_write_unsigned((uint32_t)(uintptr_t)va_arg(arguments, void *), 16U, 8U);
            break;
        case '%':
            console_putc('%');
            break;
        default:
            console_putc('%');
            console_putc(specifier);
            break;
        }
        ++format;
    }
}

void console_printf(const char *format, ...)
{
    va_list arguments;

    va_start(arguments, format);
    console_vprintf(format, arguments);
    va_end(arguments);
}
