/* SPDX-License-Identifier: MIT */
#include <wtwm/font.h>

#include <limits.h>
#include <stdlib.h>
#include <string.h>

int wtwm_x11_bitmap_font_height(const char *font) {
	if (font == NULL) return 0;
	/* X.Org's canonical "fixed" alias is the 6x13 core bitmap font. */
	if (strcmp(font, "fixed") == 0) return 13;

	char *separator = NULL;
	long width = strtol(font, &separator, 10);
	if (separator == font || *separator != 'x' || width <= 0) return 0;
	char *end = NULL;
	long height = strtol(separator + 1, &end, 10);
	if (end == separator + 1 || *end != '\0' || height <= 0 || height > INT_MAX)
		return 0;
	return (int)height;
}

const char *wtwm_pango_font_description(const char *font) {
	if (font == NULL || font[0] == '\0' || font[0] == '-') return "Sans Bold 10";
	if (strcmp(font, "fixed") == 0) return "Monospace 8";
	if (strcmp(font, "9x15") == 0) return "Monospace 9";
	return font;
}
