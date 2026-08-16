/* SPDX-License-Identifier: MIT */
#include <wtwm/color.h>

#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static bool parse_hex_component(const char *text, size_t digits,
		uint16_t *component) {
	if (digits < 1 || digits > 4) return false;
	unsigned value = 0;
	for (size_t i = 0; i < digits; ++i) {
		unsigned char c = (unsigned char)text[i];
		if (!isxdigit(c)) return false;
		value <<= 4;
		value |= c >= '0' && c <= '9' ? (unsigned)(c - '0') :
			(unsigned)(tolower(c) - 'a' + 10);
	}
	unsigned maximum = (1u << (4u * (unsigned)digits)) - 1u;
	*component = (uint16_t)((value * 65535u + maximum / 2u) / maximum);
	return true;
}

static bool parse_hash(const char *name, struct wtwm_color *color) {
	size_t length = strlen(name + 1);
	if (length != 3 && length != 6 && length != 9 && length != 12) return false;
	size_t digits = length / 3;
	return parse_hex_component(name + 1, digits, &color->red) &&
		parse_hex_component(name + 1 + digits, digits, &color->green) &&
		parse_hex_component(name + 1 + 2 * digits, digits, &color->blue);
}

static bool parse_rgb(const char *name, struct wtwm_color *color) {
	const char *cursor = name + 4;
	uint16_t *channels[] = {&color->red, &color->green, &color->blue};
	for (size_t channel = 0; channel < 3; ++channel) {
		const char *end = cursor;
		while (isxdigit((unsigned char)*end)) ++end;
		size_t digits = (size_t)(end - cursor);
		if (!parse_hex_component(cursor, digits, channels[channel])) return false;
		if (channel < 2) {
			if (*end != '/') return false;
			cursor = end + 1;
		} else if (*end != '\0') return false;
	}
	return true;
}

static bool parse_rgbi(const char *name, struct wtwm_color *color) {
	const char *cursor = name + 5;
	uint16_t *channels[] = {&color->red, &color->green, &color->blue};
	for (size_t channel = 0; channel < 3; ++channel) {
		errno = 0;
		char *end = NULL;
		double value = strtod(cursor, &end);
		if (end == cursor || errno == ERANGE || !isfinite(value) ||
			value < 0.0 || value > 1.0) return false;
		double scaled = value * 65535.0;
		*channels[channel] = (uint16_t)(scaled + 0.5);
		if (channel < 2) {
			if (*end != '/') return false;
			cursor = end + 1;
		} else if (*end != '\0') return false;
	}
	return true;
}

static bool parse_gray(const char *name, struct wtwm_color *color) {
	const char *digits = name;
	if (strncasecmp(name, "gray", 4) == 0 || strncasecmp(name, "grey", 4) == 0)
		digits += 4;
	else return false;
	if (*digits == '\0') return false;
	errno = 0;
	char *end = NULL;
	long percent = strtol(digits, &end, 10);
	if (*end != '\0' || errno == ERANGE || percent < 0 || percent > 100)
		return false;
	uint16_t channel = (uint16_t)((percent * 255 + 50) / 100 * 257);
	color->red = color->green = color->blue = channel;
	return true;
}

bool wtwm_color_parse_literal(const char *name, struct wtwm_color *color) {
	if (name == NULL || color == NULL) return false;
	if (name[0] == '#') return parse_hash(name, color);
	if (strncasecmp(name, "rgb:", 4) == 0) return parse_rgb(name, color);
	if (strncasecmp(name, "rgbi:", 5) == 0) return parse_rgbi(name, color);
	if (parse_gray(name, color)) return true;
	static const struct {
		const char *name;
		struct wtwm_color color;
	} intrinsic[] = {
		{"black", {0, 0, 0}},
		{"white", {65535, 65535, 65535}},
		{"red", {65535, 0, 0}},
		{"green", {0, 32896, 0}},
		{"blue", {0, 0, 65535}},
		{"yellow", {65535, 65535, 0}},
	};
	for (size_t i = 0; i < sizeof(intrinsic) / sizeof(intrinsic[0]); ++i) {
		if (strcasecmp(name, intrinsic[i].name) == 0) {
			*color = intrinsic[i].color;
			return true;
		}
	}
	return false;
}

void wtwm_color_to_float(const struct wtwm_color *color,
		float result[static 4]) {
	result[0] = (float)color->red / 65535.0f;
	result[1] = (float)color->green / 65535.0f;
	result[2] = (float)color->blue / 65535.0f;
	result[3] = 1.0f;
}

static uint16_t interpolate_channel(uint16_t first, uint16_t last,
		unsigned index, unsigned steps) {
	if (steps == 0 || index >= steps) return last;
	int difference = (int)last - (int)first;
	int value = (int)first + (difference / (int)steps) * (int)index;
	if (value < 0) value = 0;
	if (value > 65535) value = 65535;
	return (uint16_t)value;
}

struct wtwm_color wtwm_color_interpolate(struct wtwm_color first,
		struct wtwm_color last, unsigned index, unsigned steps) {
	return (struct wtwm_color){
		.red = interpolate_channel(first.red, last.red, index, steps),
		.green = interpolate_channel(first.green, last.green, index, steps),
		.blue = interpolate_channel(first.blue, last.blue, index, steps),
	};
}

struct wtwm_color wtwm_color_grayscale(struct wtwm_color color) {
	/* Integer Rec. 601 luma, with coefficients summing to 65536. */
	uint32_t luminance = ((uint32_t)color.red * 19595u +
		(uint32_t)color.green * 38470u + (uint32_t)color.blue * 7471u +
		32768u) >> 16;
	if (luminance > 65535u) luminance = 65535u;
	return (struct wtwm_color){(uint16_t)luminance, (uint16_t)luminance,
		(uint16_t)luminance};
}

struct wtwm_color wtwm_color_monochrome(struct wtwm_color color) {
	struct wtwm_color grayscale = wtwm_color_grayscale(color);
	uint16_t channel = grayscale.red >= 32768u ? 65535u : 0u;
	return (struct wtwm_color){channel, channel, channel};
}
