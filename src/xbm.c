/* SPDX-License-Identifier: MIT */
#include "wtwm/xbm.h"

#include <errno.h>
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum token_kind {
	TOKEN_EOF,
	TOKEN_NEWLINE,
	TOKEN_IDENTIFIER,
	TOKEN_NUMBER,
	TOKEN_PUNCTUATION,
};

struct token {
	enum token_kind kind;
	const char *text;
	size_t length;
	size_t line;
	size_t column;
	char punctuation;
};

struct scanner {
	const char *filename;
	const char *source;
	size_t length;
	size_t offset;
	size_t line;
	size_t column;
	char *error;
	size_t error_size;
	bool failed;
};

struct parser {
	struct scanner scanner;
	char *prefix;
	unsigned width;
	unsigned height;
	int x_hot;
	int y_hot;
	bool have_width;
	bool have_height;
	bool have_x_hot;
	bool have_y_hot;
	bool have_bits;
	struct wtwm_xbm result;
};

static void set_error(char *error, size_t error_size, const char *format, ...) {
	if (!error || error_size == 0) return;
	va_list args;
	va_start(args, format);
	(void)vsnprintf(error, error_size, format, args);
	va_end(args);
}

static bool scanner_error(struct scanner *scanner, size_t line, size_t column,
		const char *format, ...) {
	if (!scanner->failed && scanner->error && scanner->error_size > 0) {
		int used = snprintf(scanner->error, scanner->error_size, "%s:%zu:%zu: ",
			scanner->filename, line, column);
		if (used >= 0 && (size_t)used < scanner->error_size) {
			va_list args;
			va_start(args, format);
			(void)vsnprintf(scanner->error + (size_t)used,
				scanner->error_size - (size_t)used, format, args);
			va_end(args);
		}
	}
	scanner->failed = true;
	return false;
}

static bool is_identifier_start(unsigned char ch) {
	return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch == '_';
}

static bool is_identifier_continue(unsigned char ch) {
	return is_identifier_start(ch) || (ch >= '0' && ch <= '9');
}

static bool is_space_no_newline(unsigned char ch) {
	return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\f' || ch == '\v';
}

static void scanner_advance(struct scanner *scanner) {
	if (scanner->source[scanner->offset] == '\n') {
		scanner->line++;
		scanner->column = 1;
	} else {
		scanner->column++;
	}
	scanner->offset++;
}

static bool scanner_skip_ignored(struct scanner *scanner) {
	for (;;) {
		while (scanner->offset < scanner->length &&
				is_space_no_newline((unsigned char)scanner->source[scanner->offset])) {
			scanner_advance(scanner);
		}
		if (scanner->offset + 1 >= scanner->length ||
				scanner->source[scanner->offset] != '/') {
			return true;
		}
		char next = scanner->source[scanner->offset + 1];
		if (next == '/') {
			while (scanner->offset < scanner->length &&
					scanner->source[scanner->offset] != '\n') {
				scanner_advance(scanner);
			}
			continue;
		}
		if (next != '*') return true;

		size_t line = scanner->line;
		size_t column = scanner->column;
		scanner_advance(scanner);
		scanner_advance(scanner);
		bool closed = false;
		while (scanner->offset < scanner->length) {
			if (scanner->offset + 1 < scanner->length &&
					scanner->source[scanner->offset] == '*' &&
					scanner->source[scanner->offset + 1] == '/') {
				scanner_advance(scanner);
				scanner_advance(scanner);
				closed = true;
				break;
			}
			scanner_advance(scanner);
		}
		if (!closed) {
			return scanner_error(scanner, line, column, "unterminated comment");
		}
	}
}

static bool is_punctuation(unsigned char ch) {
	return ch == '#' || ch == '[' || ch == ']' || ch == '=' || ch == '{' ||
		ch == '}' || ch == ',' || ch == ';';
}

static bool scanner_next(struct scanner *scanner, struct token *token) {
	memset(token, 0, sizeof(*token));
	if (!scanner_skip_ignored(scanner)) return false;
	if (scanner->offset == scanner->length) {
		token->kind = TOKEN_EOF;
		token->line = scanner->line;
		token->column = scanner->column;
		return true;
	}

	unsigned char ch = (unsigned char)scanner->source[scanner->offset];
	token->text = scanner->source + scanner->offset;
	token->line = scanner->line;
	token->column = scanner->column;
	if (ch == '\n') {
		token->kind = TOKEN_NEWLINE;
		token->length = 1;
		scanner_advance(scanner);
		return true;
	}
	if (is_identifier_start(ch)) {
		token->kind = TOKEN_IDENTIFIER;
		do {
			scanner_advance(scanner);
		} while (scanner->offset < scanner->length &&
			is_identifier_continue((unsigned char)scanner->source[scanner->offset]));
		token->length = (size_t)(scanner->source + scanner->offset - token->text);
		return true;
	}
	if ((ch == '+' || ch == '-') && scanner->offset + 1 < scanner->length &&
			scanner->source[scanner->offset + 1] >= '0' &&
			scanner->source[scanner->offset + 1] <= '9') {
		scanner_advance(scanner);
		ch = (unsigned char)scanner->source[scanner->offset];
	}
	if (ch >= '0' && ch <= '9') {
		token->kind = TOKEN_NUMBER;
		do {
			scanner_advance(scanner);
		} while (scanner->offset < scanner->length &&
			is_identifier_continue((unsigned char)scanner->source[scanner->offset]));
		token->length = (size_t)(scanner->source + scanner->offset - token->text);
		return true;
	}
	if (is_punctuation(ch)) {
		token->kind = TOKEN_PUNCTUATION;
		token->length = 1;
		token->punctuation = (char)ch;
		scanner_advance(scanner);
		return true;
	}
	return scanner_error(scanner, token->line, token->column,
		"invalid character 0x%02x", (unsigned)ch);
}

static bool next_non_newline(struct scanner *scanner, struct token *token) {
	do {
		if (!scanner_next(scanner, token)) return false;
	} while (token->kind == TOKEN_NEWLINE);
	return true;
}

static bool token_equals(const struct token *token, const char *text) {
	return token->kind == TOKEN_IDENTIFIER && strlen(text) == token->length &&
		memcmp(token->text, text, token->length) == 0;
}

static bool expect_punctuation(struct scanner *scanner, char punctuation,
		struct token *token) {
	if (!next_non_newline(scanner, token)) return false;
	if (token->kind != TOKEN_PUNCTUATION || token->punctuation != punctuation) {
		return scanner_error(scanner, token->line, token->column,
			"expected '%c'", punctuation);
	}
	return true;
}

static int digit_value(unsigned char ch) {
	if (ch >= '0' && ch <= '9') return ch - '0';
	if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
	if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
	return -1;
}

static bool parse_integer(const struct token *token, bool allow_negative,
		uint64_t maximum, int64_t minimum, int64_t *result) {
	if (token->kind != TOKEN_NUMBER || token->length == 0) return false;
	size_t offset = 0;
	bool negative = false;
	if (token->text[offset] == '+' || token->text[offset] == '-') {
		negative = token->text[offset] == '-';
		offset++;
	}
	if (negative && !allow_negative) return false;
	if (offset == token->length) return false;

	unsigned base = 10;
	if (token->text[offset] == '0') {
		base = 8;
		if (offset + 1 < token->length &&
				(token->text[offset + 1] == 'x' || token->text[offset + 1] == 'X')) {
			base = 16;
			offset += 2;
			if (offset == token->length) return false;
		}
	}

	uint64_t value = 0;
	for (; offset < token->length; ++offset) {
		int digit = digit_value((unsigned char)token->text[offset]);
		if (digit < 0 || (unsigned)digit >= base) return false;
		if (value > (maximum - (unsigned)digit) / base) return false;
		value = value * base + (unsigned)digit;
	}
	if (negative) {
		uint64_t magnitude_limit = (uint64_t)(-(minimum + 1)) + 1u;
		if (value > magnitude_limit) return false;
		if (value == magnitude_limit) {
			*result = minimum;
		} else {
			*result = -(int64_t)value;
		}
	} else {
		*result = (int64_t)value;
	}
	return true;
}

static bool macro_suffix(const struct token *token, const char *suffix,
		size_t *prefix_length) {
	size_t suffix_length = strlen(suffix);
	if (token->kind != TOKEN_IDENTIFIER || token->length <= suffix_length ||
		memcmp(token->text + token->length - suffix_length, suffix,
			suffix_length) != 0) {
		return false;
	}
	*prefix_length = token->length - suffix_length;
	return true;
}

static bool set_prefix(struct parser *parser, const struct token *token,
		size_t prefix_length) {
	if (parser->prefix) {
		if (strlen(parser->prefix) != prefix_length ||
				memcmp(parser->prefix, token->text, prefix_length) != 0) {
			return scanner_error(&parser->scanner, token->line, token->column,
				"bitmap prefix does not match '%s'", parser->prefix);
		}
		return true;
	}
	if (prefix_length > 255) {
		return scanner_error(&parser->scanner, token->line, token->column,
			"bitmap prefix exceeds 255 bytes");
	}
	parser->prefix = malloc(prefix_length + 1);
	if (!parser->prefix) {
		return scanner_error(&parser->scanner, token->line, token->column,
			"out of memory");
	}
	memcpy(parser->prefix, token->text, prefix_length);
	parser->prefix[prefix_length] = '\0';
	return true;
}

static bool parse_define(struct parser *parser, const struct token *hash) {
	struct token token;
	if (!scanner_next(&parser->scanner, &token)) return false;
	if (token.kind == TOKEN_NEWLINE || !token_equals(&token, "define")) {
		return scanner_error(&parser->scanner, token.line, token.column,
			"expected 'define' after '#'");
	}
	if (!scanner_next(&parser->scanner, &token)) return false;
	if (token.kind != TOKEN_IDENTIFIER || token.line != hash->line) {
		return scanner_error(&parser->scanner, token.line, token.column,
			"expected bitmap macro name");
	}
	struct token name = token;
	if (!scanner_next(&parser->scanner, &token)) return false;
	if (token.kind != TOKEN_NUMBER || token.line != hash->line) {
		return scanner_error(&parser->scanner, token.line, token.column,
			"expected integer bitmap macro value");
	}
	struct token value_token = token;
	if (!scanner_next(&parser->scanner, &token)) return false;
	if (token.kind != TOKEN_NEWLINE && token.kind != TOKEN_EOF) {
		return scanner_error(&parser->scanner, token.line, token.column,
			"unexpected token after bitmap macro value");
	}

	size_t prefix_length = 0;
	enum { DEFINE_WIDTH, DEFINE_HEIGHT, DEFINE_X_HOT, DEFINE_Y_HOT } kind;
	if (macro_suffix(&name, "_width", &prefix_length)) {
		kind = DEFINE_WIDTH;
	} else if (macro_suffix(&name, "_height", &prefix_length)) {
		kind = DEFINE_HEIGHT;
	} else if (macro_suffix(&name, "_x_hot", &prefix_length)) {
		kind = DEFINE_X_HOT;
	} else if (macro_suffix(&name, "_y_hot", &prefix_length)) {
		kind = DEFINE_Y_HOT;
	} else {
		return scanner_error(&parser->scanner, name.line, name.column,
			"unsupported XBM definition");
	}
	if (!set_prefix(parser, &name, prefix_length)) return false;

	int64_t value;
	if (kind == DEFINE_WIDTH || kind == DEFINE_HEIGHT) {
		if (!parse_integer(&value_token, false, UINT_MAX, 0, &value) || value <= 0) {
			return scanner_error(&parser->scanner, value_token.line,
				value_token.column, "invalid bitmap dimension");
		}
		if ((uint64_t)value > WTWM_XBM_MAX_DIMENSION) {
			return scanner_error(&parser->scanner, value_token.line,
				value_token.column, "bitmap dimension exceeds limit %u",
				WTWM_XBM_MAX_DIMENSION);
		}
		bool *present = kind == DEFINE_WIDTH ? &parser->have_width :
			&parser->have_height;
		unsigned *destination = kind == DEFINE_WIDTH ? &parser->width :
			&parser->height;
		if (*present) {
			return scanner_error(&parser->scanner, name.line, name.column,
				"duplicate bitmap dimension");
		}
		*present = true;
		*destination = (unsigned)value;
	} else {
		if (!parse_integer(&value_token, true, INT_MAX, INT_MIN, &value)) {
			return scanner_error(&parser->scanner, value_token.line,
				value_token.column, "invalid bitmap hotspot");
		}
		bool *present = kind == DEFINE_X_HOT ? &parser->have_x_hot :
			&parser->have_y_hot;
		int *destination = kind == DEFINE_X_HOT ? &parser->x_hot : &parser->y_hot;
		if (*present) {
			return scanner_error(&parser->scanner, name.line, name.column,
				"duplicate bitmap hotspot");
		}
		*present = true;
		*destination = (int)value;
	}
	return true;
}

static bool parse_data(struct parser *parser, bool short_data,
		const struct token *declaration_name) {
	if (!parser->have_width || !parser->have_height) {
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column,
			"bitmap width and height must precede data");
	}
	if (parser->have_bits) {
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column, "duplicate bitmap data");
	}
	size_t prefix_length;
	if (!macro_suffix(declaration_name, "_bits", &prefix_length)) {
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column, "expected a name ending in '_bits'");
	}
	if (!set_prefix(parser, declaration_name, prefix_length)) return false;

	size_t stride = ((size_t)parser->width + 7u) / 8u;
	if ((size_t)parser->height > SIZE_MAX / stride) {
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column, "bitmap data size overflows");
	}
	size_t data_size = stride * parser->height;
	if (data_size > WTWM_XBM_MAX_DATA_BYTES) {
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column, "bitmap data exceeds limit %u",
			WTWM_XBM_MAX_DATA_BYTES);
	}
	unsigned char *data = calloc(data_size, 1);
	if (!data) {
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column, "out of memory");
	}

	size_t units_per_row = short_data ? ((size_t)parser->width + 15u) / 16u :
		stride;
	if ((size_t)parser->height > SIZE_MAX / units_per_row) {
		free(data);
		return scanner_error(&parser->scanner, declaration_name->line,
			declaration_name->column, "bitmap element count overflows");
	}
	size_t expected = units_per_row * parser->height;
	size_t count = 0;
	struct token token;
	if (!next_non_newline(&parser->scanner, &token)) {
		free(data);
		return false;
	}
	if (token.kind == TOKEN_PUNCTUATION && token.punctuation == '}') {
		free(data);
		return scanner_error(&parser->scanner, token.line, token.column,
			"truncated bitmap data: expected %zu elements, found 0", expected);
	}

	for (;;) {
		int64_t value;
		uint64_t maximum = short_data ? UINT16_MAX : UINT8_MAX;
		if (!parse_integer(&token, false, maximum, 0, &value)) {
			free(data);
			return scanner_error(&parser->scanner, token.line, token.column,
				"invalid bitmap data value");
		}
		if (count >= expected) {
			free(data);
			return scanner_error(&parser->scanner, token.line, token.column,
				"excessive bitmap data: expected %zu elements", expected);
		}
		if (short_data) {
			size_t row = count / units_per_row;
			size_t unit = count % units_per_row;
			size_t output = row * stride + unit * 2u;
			data[output] = (unsigned char)((uint64_t)value & 0xffu);
			if (output + 1u < (row + 1u) * stride) {
				data[output + 1u] = (unsigned char)((uint64_t)value >> 8);
			}
		} else {
			data[count] = (unsigned char)value;
		}
		count++;

		if (!next_non_newline(&parser->scanner, &token)) {
			free(data);
			return false;
		}
		if (token.kind == TOKEN_PUNCTUATION && token.punctuation == '}') break;
		if (token.kind != TOKEN_PUNCTUATION || token.punctuation != ',') {
			free(data);
			return scanner_error(&parser->scanner, token.line, token.column,
				"expected ',' or '}' after bitmap data value");
		}
		if (!next_non_newline(&parser->scanner, &token)) {
			free(data);
			return false;
		}
		if (token.kind == TOKEN_PUNCTUATION && token.punctuation == '}') break;
	}
	if (count != expected) {
		free(data);
		return scanner_error(&parser->scanner, token.line, token.column,
			"truncated bitmap data: expected %zu elements, found %zu",
			expected, count);
	}
	if (!expect_punctuation(&parser->scanner, ';', &token)) {
		free(data);
		return false;
	}

	parser->result.name = parser->prefix;
	parser->prefix = NULL;
	parser->result.width = parser->width;
	parser->result.height = parser->height;
	parser->result.x_hot = parser->have_x_hot ? parser->x_hot : -1;
	parser->result.y_hot = parser->have_y_hot ? parser->y_hot : -1;
	parser->result.stride = stride;
	parser->result.data_size = data_size;
	parser->result.data = data;
	parser->have_bits = true;
	return true;
}

static bool parse_declaration(struct parser *parser, const struct token *start) {
	struct token token;
	if (!next_non_newline(&parser->scanner, &token)) return false;
	bool is_unsigned = false;
	if (token_equals(&token, "unsigned")) {
		is_unsigned = true;
		if (!next_non_newline(&parser->scanner, &token)) return false;
	}
	bool short_data;
	if (token_equals(&token, "char")) {
		short_data = false;
	} else if (token_equals(&token, "short") && !is_unsigned) {
		short_data = true;
	} else {
		return scanner_error(&parser->scanner, token.line, token.column,
			"unsupported XBM declaration; expected char, unsigned char, or short");
	}
	if (!next_non_newline(&parser->scanner, &token)) return false;
	if (token.kind != TOKEN_IDENTIFIER) {
		return scanner_error(&parser->scanner, token.line, token.column,
			"expected bitmap data name");
	}
	struct token name = token;
	if (!expect_punctuation(&parser->scanner, '[', &token) ||
			!expect_punctuation(&parser->scanner, ']', &token) ||
			!expect_punctuation(&parser->scanner, '=', &token) ||
			!expect_punctuation(&parser->scanner, '{', &token)) {
		return false;
	}
	(void)start;
	return parse_data(parser, short_data, &name);
}

static bool parse_source(struct wtwm_xbm *result, const char *filename,
		const char *source, size_t length, char *error, size_t error_size) {
	struct parser parser = {
		.scanner = {
			.filename = filename,
			.source = source,
			.length = length,
			.line = 1,
			.column = 1,
			.error = error,
			.error_size = error_size,
		},
	};
	wtwm_xbm_init(&parser.result);

	struct token token;
	while (next_non_newline(&parser.scanner, &token) && token.kind != TOKEN_EOF) {
		if (parser.have_bits) {
			scanner_error(&parser.scanner, token.line, token.column,
				"unexpected content after bitmap data");
			break;
		}
		if (token.kind == TOKEN_PUNCTUATION && token.punctuation == '#') {
			if (!parse_define(&parser, &token)) break;
		} else if (token_equals(&token, "static")) {
			if (!parse_declaration(&parser, &token)) break;
		} else {
			scanner_error(&parser.scanner, token.line, token.column,
				"expected XBM definition or static data declaration");
			break;
		}
	}
	if (!parser.scanner.failed && !parser.have_bits) {
		scanner_error(&parser.scanner, parser.scanner.line, parser.scanner.column,
			"missing bitmap data declaration");
	}
	if (parser.scanner.failed) {
		free(parser.prefix);
		wtwm_xbm_finish(&parser.result);
		return false;
	}
	*result = parser.result;
	return true;
}

static bool read_file(const char *filename, char **source, size_t *length,
		char *error, size_t error_size) {
	FILE *file = fopen(filename, "rb");
	if (!file) {
		set_error(error, error_size, "%s: unable to open: %s", filename,
			strerror(errno));
		return false;
	}
	size_t capacity = 4096;
	char *buffer = malloc(capacity + 1u);
	if (!buffer) {
		set_error(error, error_size, "%s: out of memory", filename);
		(void)fclose(file);
		return false;
	}
	size_t used = 0;
	for (;;) {
		if (used == capacity) {
			if (capacity == WTWM_XBM_MAX_FILE_BYTES) {
				int next = fgetc(file);
				if (next != EOF) {
					set_error(error, error_size,
						"%s: file exceeds limit %u", filename,
						WTWM_XBM_MAX_FILE_BYTES);
					free(buffer);
					(void)fclose(file);
					return false;
				}
				break;
			}
			size_t next_capacity = capacity * 2u;
			if (next_capacity > WTWM_XBM_MAX_FILE_BYTES) {
				next_capacity = WTWM_XBM_MAX_FILE_BYTES;
			}
			char *replacement = realloc(buffer, next_capacity + 1u);
			if (!replacement) {
				set_error(error, error_size, "%s: out of memory", filename);
				free(buffer);
				(void)fclose(file);
				return false;
			}
			buffer = replacement;
			capacity = next_capacity;
		}
		size_t count = fread(buffer + used, 1, capacity - used, file);
		used += count;
		if (count == 0) {
			if (ferror(file)) {
				set_error(error, error_size, "%s: unable to read: %s", filename,
					strerror(errno));
				free(buffer);
				(void)fclose(file);
				return false;
			}
			break;
		}
	}
	if (fclose(file) != 0) {
		set_error(error, error_size, "%s: unable to close: %s", filename,
			strerror(errno));
		free(buffer);
		return false;
	}
	buffer[used] = '\0';
	*source = buffer;
	*length = used;
	return true;
}

void wtwm_xbm_init(struct wtwm_xbm *xbm) {
	if (!xbm) return;
	memset(xbm, 0, sizeof(*xbm));
	xbm->x_hot = -1;
	xbm->y_hot = -1;
}

void wtwm_xbm_finish(struct wtwm_xbm *xbm) {
	if (!xbm) return;
	free(xbm->name);
	free(xbm->data);
	wtwm_xbm_init(xbm);
}

bool wtwm_xbm_load(struct wtwm_xbm *xbm, const char *filename,
		char *error, size_t error_size) {
	if (error && error_size > 0) error[0] = '\0';
	if (!xbm || !filename || filename[0] == '\0') {
		set_error(error, error_size, "%s: invalid loader argument",
			filename ? filename : "(null)");
		return false;
	}
	char *source;
	size_t length;
	if (!read_file(filename, &source, &length, error, error_size)) return false;

	struct wtwm_xbm replacement;
	wtwm_xbm_init(&replacement);
	bool success = parse_source(&replacement, filename, source, length,
		error, error_size);
	free(source);
	if (!success) return false;
	wtwm_xbm_finish(xbm);
	*xbm = replacement;
	return true;
}
