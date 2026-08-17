/* SPDX-License-Identifier: MIT */
#include <wtwm/font.h>

#include <stdbool.h>
#include <limits.h>
#include <stddef.h>

#define XLFD_FIELD_COUNT 14
#define XLFD_INPUT_MAX 1024
#define XLFD_FIELD_MAX 255

enum xlfd_field {
	XLFD_FOUNDRY,
	XLFD_FAMILY,
	XLFD_WEIGHT,
	XLFD_SLANT,
	XLFD_SETWIDTH,
	XLFD_ADD_STYLE,
	XLFD_PIXEL_SIZE,
	XLFD_POINT_SIZE,
	XLFD_RESOLUTION_X,
	XLFD_RESOLUTION_Y,
	XLFD_SPACING,
	XLFD_AVERAGE_WIDTH,
	XLFD_REGISTRY,
	XLFD_ENCODING,
};

struct string_span {
	const char *data;
	size_t length;
};

struct output_writer {
	char *data;
	size_t capacity;
	size_t length;
};

enum number_kind {
	NUMBER_INVALID,
	NUMBER_UNSPECIFIED,
	NUMBER_VALUE,
};

static bool ascii_equal(char left, char right) {
	if (left >= 'A' && left <= 'Z') left = (char)(left - 'A' + 'a');
	if (right >= 'A' && right <= 'Z') right = (char)(right - 'A' + 'a');
	return left == right;
}

static bool string_equal_case(const char *left, const char *right) {
	if (left == NULL || right == NULL) return left == right;
	while (*left != '\0' && *right != '\0') {
		if (!ascii_equal(*left, *right)) return false;
		left++;
		right++;
	}
	return *left == *right;
}

static bool span_equal_case(struct string_span span, const char *value) {
	size_t index = 0;
	while (index < span.length && value[index] != '\0') {
		if (!ascii_equal(span.data[index], value[index])) return false;
		index++;
	}
	return index == span.length && value[index] == '\0';
}

static bool span_has_wildcard(struct string_span span) {
	for (size_t index = 0; index < span.length; index++) {
		if (span.data[index] == '*' || span.data[index] == '?') return true;
	}
	return false;
}

static bool valid_xlfd_field(struct string_span span) {
	if (span.length > XLFD_FIELD_MAX) return false;
	for (size_t index = 0; index < span.length; index++) {
		unsigned char character = (unsigned char)span.data[index];
		if (character < 0x20 || character == 0x7f) return false;
	}
	return true;
}

static bool parse_xlfd(const char *font,
	struct string_span fields[static XLFD_FIELD_COUNT]) {
	if (font == NULL || font[0] != '-') return false;

	size_t length = 0;
	while (length <= XLFD_INPUT_MAX && font[length] != '\0') length++;
	if (length > XLFD_INPUT_MAX) return false;

	const char *field_start = font + 1;
	for (size_t index = 0; index < XLFD_FIELD_COUNT; index++) {
		const char *field_end = field_start;
		while (*field_end != '\0' && *field_end != '-') field_end++;
		fields[index].data = field_start;
		fields[index].length = (size_t)(field_end - field_start);
		if (!valid_xlfd_field(fields[index])) return false;
		if (index + 1 < XLFD_FIELD_COUNT) {
			if (*field_end != '-') return false;
			field_start = field_end + 1;
		} else if (*field_end != '\0') {
			return false;
		}
	}
	return true;
}

static enum number_kind parse_number(struct string_span span, int *value) {
	if (span.length == 0 || span_equal_case(span, "*"))
		return NUMBER_UNSPECIFIED;
	if (span_has_wildcard(span)) return NUMBER_UNSPECIFIED;

	int parsed = 0;
	for (size_t index = 0; index < span.length; index++) {
		char character = span.data[index];
		if (character < '0' || character > '9') return NUMBER_INVALID;
		int digit = character - '0';
		if (parsed > (INT_MAX - digit) / 10) return NUMBER_INVALID;
		parsed = parsed * 10 + digit;
	}
	*value = parsed;
	return NUMBER_VALUE;
}

static bool parse_positive_decimal(const char **cursor, int *value) {
	const char *position = *cursor;
	if (*position < '0' || *position > '9') return false;
	int parsed = 0;
	do {
		int digit = *position - '0';
		if (parsed > (INT_MAX - digit) / 10) return false;
		parsed = parsed * 10 + digit;
		position++;
	} while (*position >= '0' && *position <= '9');
	if (parsed == 0) return false;
	*cursor = position;
	*value = parsed;
	return true;
}

static bool parse_bitmap_alias(const char *font, int *width, int *height) {
	if (font == NULL) return false;
	const char *cursor = font;
	if (!parse_positive_decimal(&cursor, width) || *cursor != 'x') return false;
	cursor++;
	return parse_positive_decimal(&cursor, height) && *cursor == '\0';
}

static void writer_character(struct output_writer *writer, char character) {
	if (writer->capacity > 0 && writer->length + 1 < writer->capacity)
		writer->data[writer->length] = character;
	writer->length++;
}

static void writer_span(struct output_writer *writer, struct string_span span) {
	for (size_t index = 0; index < span.length; index++)
		writer_character(writer, span.data[index]);
}

static void writer_string(struct output_writer *writer, const char *value) {
	while (*value != '\0') {
		writer_character(writer, *value);
		value++;
	}
}

static void writer_unsigned(struct output_writer *writer, unsigned int value) {
	char digits[sizeof(value) * 3];
	size_t length = 0;
	do {
		digits[length++] = (char)('0' + value % 10);
		value /= 10;
	} while (value > 0);
	while (length > 0) writer_character(writer, digits[--length]);
}

static void writer_finish(struct output_writer *writer) {
	if (writer->capacity == 0) return;
	size_t terminator = writer->length;
	if (terminator >= writer->capacity) terminator = writer->capacity - 1;
	writer->data[terminator] = '\0';
}

static bool family_is_monospace(struct string_span family) {
	return span_equal_case(family, "fixed") ||
		span_equal_case(family, "courier") ||
		span_equal_case(family, "lucidatypewriter") ||
		span_equal_case(family, "lucida typewriter") ||
		span_equal_case(family, "monospace") ||
		span_equal_case(family, "terminal");
}

static bool family_is_sans(struct string_span family) {
	return span_equal_case(family, "helvetica") ||
		span_equal_case(family, "arial") ||
		span_equal_case(family, "lucida") ||
		span_equal_case(family, "sans") ||
		span_equal_case(family, "sans serif");
}

static bool family_is_serif(struct string_span family) {
	return span_equal_case(family, "times") ||
		span_equal_case(family, "times new roman") ||
		span_equal_case(family, "charter") ||
		span_equal_case(family, "new century schoolbook") ||
		span_equal_case(family, "serif");
}

static bool spacing_is_monospace(struct string_span spacing) {
	return span_equal_case(spacing, "m") || span_equal_case(spacing, "c");
}

static void write_family(struct output_writer *writer,
	const struct string_span fields[static XLFD_FIELD_COUNT]) {
	struct string_span family = fields[XLFD_FAMILY];
	if (spacing_is_monospace(fields[XLFD_SPACING]) || family_is_monospace(family)) {
		writer_string(writer, "Monospace");
	} else if (family.length == 0 || span_has_wildcard(family) ||
		family_is_sans(family)) {
		writer_string(writer, "Sans");
	} else if (family_is_serif(family)) {
		writer_string(writer, "Serif");
	} else {
		writer_span(writer, family);
	}
}

static void write_weight(struct output_writer *writer, struct string_span weight) {
	const char *mapped = NULL;
	if (span_equal_case(weight, "bold") || span_equal_case(weight, "demibold") ||
		span_equal_case(weight, "demi") || span_equal_case(weight, "semibold")) {
		mapped = "Bold";
	} else if (span_equal_case(weight, "black") ||
		span_equal_case(weight, "heavy")) {
		mapped = "Heavy";
	} else if (span_equal_case(weight, "light")) {
		mapped = "Light";
	}
	if (mapped != NULL) {
		writer_character(writer, ' ');
		writer_string(writer, mapped);
	}
}

static void write_slant(struct output_writer *writer, struct string_span slant) {
	const char *mapped = NULL;
	if (span_equal_case(slant, "i") || span_equal_case(slant, "ri")) {
		mapped = "Italic";
	} else if (span_equal_case(slant, "o") || span_equal_case(slant, "ro") ||
		span_equal_case(slant, "ot")) {
		mapped = "Oblique";
	}
	if (mapped != NULL) {
		writer_character(writer, ' ');
		writer_string(writer, mapped);
	}
}

static bool write_xlfd_description(struct output_writer *writer,
	const struct string_span fields[static XLFD_FIELD_COUNT]) {
	int pixel_size = 0;
	int point_size = 0;
	enum number_kind pixel_kind =
		parse_number(fields[XLFD_PIXEL_SIZE], &pixel_size);
	enum number_kind point_kind =
		parse_number(fields[XLFD_POINT_SIZE], &point_size);
	if (pixel_kind == NUMBER_INVALID || point_kind == NUMBER_INVALID) return false;

	write_family(writer, fields);
	write_weight(writer, fields[XLFD_WEIGHT]);
	write_slant(writer, fields[XLFD_SLANT]);
	writer_character(writer, ' ');
	if (pixel_kind == NUMBER_VALUE && pixel_size > 0) {
		writer_unsigned(writer, (unsigned int)pixel_size);
		writer_string(writer, "px");
	} else if (point_kind == NUMBER_VALUE && point_size > 0) {
		writer_unsigned(writer, (unsigned int)(point_size / 10));
		if (point_size % 10 != 0) {
			writer_character(writer, '.');
			writer_unsigned(writer, (unsigned int)(point_size % 10));
		}
	} else {
		writer_string(writer, "10");
	}
	return true;
}

static size_t write_fallback(char *description, size_t capacity) {
	if (description == NULL) capacity = 0;
	struct output_writer writer = {description, capacity, 0};
	writer_string(&writer, "Sans Bold 10");
	writer_finish(&writer);
	return writer.length;
}

int wtwm_x11_bitmap_font_height(const char *font) {
	if (font == NULL) return 0;
	/* X.Org's canonical "fixed" alias is the 6x13 core bitmap font. */
	if (string_equal_case(font, "fixed")) return 13;

	int width = 0;
	int height = 0;
	if (parse_bitmap_alias(font, &width, &height)) {
		(void)width;
		return height;
	}

	struct string_span fields[XLFD_FIELD_COUNT];
	if (!parse_xlfd(font, fields)) return 0;
	int pixel_size = 0;
	if (parse_number(fields[XLFD_PIXEL_SIZE], &pixel_size) != NUMBER_VALUE ||
		pixel_size <= 0) {
		return 0;
	}
	return pixel_size;
}

size_t wtwm_pango_font_description(const char *font, char *description,
	size_t capacity) {
	if (description == NULL) capacity = 0;
	if (font == NULL || font[0] == '\0') return write_fallback(description, capacity);

	struct output_writer writer = {description, capacity, 0};
	if (string_equal_case(font, "fixed")) {
		writer_string(&writer, "Monospace 13px");
		writer_finish(&writer);
		return writer.length;
	}

	int width = 0;
	int height = 0;
	if (parse_bitmap_alias(font, &width, &height)) {
		(void)width;
		writer_string(&writer, "Monospace ");
		writer_unsigned(&writer, (unsigned int)height);
		writer_string(&writer, "px");
		writer_finish(&writer);
		return writer.length;
	}

	if (font[0] != '-') {
		writer_string(&writer, font);
		writer_finish(&writer);
		return writer.length;
	}

	struct string_span fields[XLFD_FIELD_COUNT];
	if (!parse_xlfd(font, fields) || !write_xlfd_description(&writer, fields))
		return write_fallback(description, capacity);
	writer_finish(&writer);
	return writer.length;
}
