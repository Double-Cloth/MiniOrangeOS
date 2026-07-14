#include <minios/string.h>

size_t minios_strlen(const char *value)
{
    size_t length = 0U;

    if (value == NULL) {
        return 0U;
    }
    while (value[length] != '\0') {
        ++length;
    }
    return length;
}

bool minios_streq(const char *left, const char *right)
{
    size_t index = 0U;

    if (left == NULL || right == NULL) {
        return false;
    }
    while (left[index] != '\0' && right[index] != '\0') {
        if (left[index] != right[index]) {
            return false;
        }
        ++index;
    }
    return left[index] == right[index];
}
