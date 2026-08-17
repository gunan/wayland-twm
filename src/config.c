/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "wtwm/config.h"

#include <errno.h>
#include <limits.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#ifndef WTWM_SYSTEM_CONFIG
#define WTWM_SYSTEM_CONFIG "/usr/share/wtwm/system.twmrc"
#endif

enum token_type {
	TOK_EOF,
	TOK_WORD,
	TOK_STRING,
	TOK_NUMBER,
	TOK_LBRACE,
	TOK_RBRACE,
	TOK_LPAREN,
	TOK_RPAREN,
	TOK_COLON,
	TOK_EQUALS,
	TOK_OR,
	TOK_PLUS,
	TOK_MINUS,
};

struct token {
	enum token_type type;
	char *text;
	long number;
	size_t line;
	size_t begin;
	size_t trivia_begin;
	bool number_overflow;
};

struct parser {
	struct wtwm_config *config;
	const char *source_name;
	const char *input;
	size_t offset;
	size_t line;
	struct token token;
	char *error;
	size_t error_size;
	struct wtwm_directive *record;
};

struct named_action {
	const char *name;
	enum wtwm_action_type type;
	bool takes_argument;
	enum wtwm_compatibility compatibility;
};

#define ACT(name, type) {name, type, false, WTWM_COMPAT_EFFECTIVE}
#define ACT_ARG(name, type) {name, type, true, WTWM_COMPAT_EFFECTIVE}
static const struct named_action actions[] = {
	ACT("f.autoraise", WTWM_ACTION_AUTORAISE),
	ACT("f.backiconmgr", WTWM_ACTION_ICONMGR_BACKWARD),
	ACT("f.beep", WTWM_ACTION_BEEP), ACT("f.bottomzoom", WTWM_ACTION_BOTTOMZOOM),
	ACT("f.circledown", WTWM_ACTION_CIRCLEDOWN),
	ACT("f.circleup", WTWM_ACTION_CIRCLEUP),
	ACT_ARG("f.colormap", WTWM_ACTION_COLORMAP),
	ACT_ARG("f.cut", WTWM_ACTION_CUT),
	ACT("f.cutfile", WTWM_ACTION_CUTFILE),
	ACT("f.deiconify", WTWM_ACTION_DEICONIFY),
	{"f.delete", WTWM_ACTION_DELETE, false, WTWM_COMPAT_WAYLAND_TRANSLATED},
	ACT("f.deltastop", WTWM_ACTION_DELTASTOP),
	{"f.destroy", WTWM_ACTION_DESTROY, false, WTWM_COMPAT_WAYLAND_TRANSLATED},
	ACT("f.downiconmgr", WTWM_ACTION_ICONMGR_DOWN),
	ACT_ARG("f.exec", WTWM_ACTION_EXEC),
	ACT_ARG("f.file", WTWM_ACTION_FILE),
	ACT("f.focus", WTWM_ACTION_FOCUS), ACT("f.forcemove", WTWM_ACTION_FORCEMOVE),
	ACT("f.forwiconmgr", WTWM_ACTION_ICONMGR_FORWARD),
	ACT("f.fullzoom", WTWM_ACTION_FULLZOOM),
	ACT_ARG("f.function", WTWM_ACTION_FUNCTION),
	ACT("f.hbzoom", WTWM_ACTION_BOTTOMZOOM),
	ACT("f.hideiconmgr", WTWM_ACTION_ICONMGR_HIDE),
	ACT("f.horizoom", WTWM_ACTION_HORIZOOM),
	ACT("f.htzoom", WTWM_ACTION_TOPZOOM),
	ACT("f.hzoom", WTWM_ACTION_HORIZOOM), ACT("f.iconify", WTWM_ACTION_ICONIFY),
	ACT("f.identify", WTWM_ACTION_IDENTIFY),
	ACT("f.lefticonmgr", WTWM_ACTION_ICONMGR_LEFT),
	ACT("f.leftzoom", WTWM_ACTION_LEFTZOOM), ACT("f.lower", WTWM_ACTION_LOWER),
	ACT_ARG("f.menu", WTWM_ACTION_MENU), ACT("f.move", WTWM_ACTION_MOVE),
	ACT("f.nexticonmgr", WTWM_ACTION_ICONMGR_NEXT), ACT("f.nop", WTWM_ACTION_NOP),
	ACT("f.previconmgr", WTWM_ACTION_ICONMGR_PREVIOUS),
	ACT_ARG("f.priority", WTWM_ACTION_PRIORITY),
	ACT("f.quit", WTWM_ACTION_QUIT), ACT("f.raise", WTWM_ACTION_RAISE),
	ACT("f.raiselower", WTWM_ACTION_RAISELOWER), ACT("f.refresh", WTWM_ACTION_REFRESH),
	ACT("f.resize", WTWM_ACTION_RESIZE), ACT("f.restart", WTWM_ACTION_RESTART),
	ACT("f.righticonmgr", WTWM_ACTION_ICONMGR_RIGHT),
	ACT("f.rightzoom", WTWM_ACTION_RIGHTZOOM),
	{"f.saveyourself", WTWM_ACTION_SAVEYOURSELF, false,
		WTWM_COMPAT_WAYLAND_TRANSLATED},
	ACT("f.showiconmgr", WTWM_ACTION_ICONMGR_SHOW),
	ACT("f.sorticonmgr", WTWM_ACTION_ICONMGR_SORT),
	{"f.source", WTWM_ACTION_BEEP, true, WTWM_COMPAT_WAYLAND_TRANSLATED},
	ACT_ARG("f.startwm", WTWM_ACTION_STARTWM), ACT("f.title", WTWM_ACTION_TITLE),
	ACT("f.topzoom", WTWM_ACTION_TOPZOOM), ACT("f.twmrc", WTWM_ACTION_RESTART),
	ACT("f.unfocus", WTWM_ACTION_UNFOCUS),
	ACT("f.upiconmgr", WTWM_ACTION_ICONMGR_UP),
	ACT("f.version", WTWM_ACTION_VERSION), ACT("f.vlzoom", WTWM_ACTION_LEFTZOOM),
	ACT("f.vrzoom", WTWM_ACTION_RIGHTZOOM), ACT("f.warpnext", WTWM_ACTION_WARPNEXT),
	ACT("f.warpprev", WTWM_ACTION_WARPPREV),
	ACT_ARG("f.warpring", WTWM_ACTION_WARPRING),
	ACT_ARG("f.warpto", WTWM_ACTION_WARPTO),
	ACT_ARG("f.warptoiconmgr", WTWM_ACTION_WARPTOICONMGR),
	ACT_ARG("f.warptoscreen", WTWM_ACTION_WARPTOSCREEN),
	ACT("f.winrefresh", WTWM_ACTION_WINREFRESH),
	ACT("f.zoom", WTWM_ACTION_ZOOM),
};
#undef ACT
#undef ACT_ARG

static bool equal_ci(const char *a, const char *b) {
	for (; *a && *b; ++a, ++b) {
		unsigned char ca = (unsigned char)*a, cb = (unsigned char)*b;
		if (ca >= 'A' && ca <= 'Z') ca = (unsigned char)(ca - 'A' + 'a');
		if (cb >= 'A' && cb <= 'Z') cb = (unsigned char)(cb - 'A' + 'a');
		if (ca != cb) return false;
	}
	return *a == *b;
}

static bool lex_space(char ch) {
	return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n';
}

static bool word_char(char ch) {
	return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch == '.';
}

static void copy_text(char *dest, size_t size, const char *source) {
	if (size > 0) snprintf(dest, size, "%s", source ? source : "");
}

static void project_text(struct parser *parser, char *dest, size_t size,
	const char *source) {
	if (source != NULL && strlen(source) >= size) {
		++parser->config->projection_truncation_count;
		++parser->config->warning_count;
	}
	copy_text(dest, size, source);
}

static bool fail_at(struct parser *parser, size_t line, const char *format, ...) {
	if (parser->error != NULL && parser->error_size > 0 && parser->error[0] == '\0') {
		int used = snprintf(parser->error, parser->error_size, "%s:%zu: ",
			parser->source_name, line);
		if (used >= 0 && (size_t)used < parser->error_size) {
			va_list args;
			va_start(args, format);
			vsnprintf(parser->error + used, parser->error_size - (size_t)used,
				format, args);
			va_end(args);
		}
	}
	return false;
}

static bool fail(struct parser *parser, const char *format, ...) {
	if (parser->error != NULL && parser->error_size > 0 && parser->error[0] == '\0') {
		int used = snprintf(parser->error, parser->error_size, "%s:%zu: ",
			parser->source_name, parser->token.line);
		if (used >= 0 && (size_t)used < parser->error_size) {
			va_list args;
			va_start(args, format);
			vsnprintf(parser->error + used, parser->error_size - (size_t)used,
				format, args);
			va_end(args);
		}
	}
	return false;
}

static bool token_set_text(struct parser *parser, struct token *token,
	const char *start, size_t length) {
	token->text = malloc(length + 1);
	if (token->text == NULL) return fail_at(parser, token->line, "out of memory");
	memcpy(token->text, start, length);
	token->text[length] = '\0';
	return true;
}

static bool append_char(struct parser *parser, char **text, size_t *length,
	size_t *capacity, char value, size_t line) {
	if (*length + 1 >= *capacity) {
		size_t next = *capacity == 0 ? 32 : *capacity * 2;
		if (next <= *capacity) return fail_at(parser, line, "string is too large");
		char *grown = realloc(*text, next);
		if (grown == NULL) return fail_at(parser, line, "out of memory");
		*text = grown;
		*capacity = next;
	}
	(*text)[(*length)++] = value;
	return true;
}

static bool hex_digit(char ch, unsigned *value) {
	if (ch >= '0' && ch <= '9') *value = (unsigned)(ch - '0');
	else if (ch >= 'a' && ch <= 'f') *value = (unsigned)(ch - 'a') + 10;
	else if (ch >= 'A' && ch <= 'F') *value = (unsigned)(ch - 'A') + 10;
	else return false;
	return true;
}

static bool lex_string(struct parser *parser, struct token *token, size_t *position) {
	size_t pos = *position + 1;
	size_t length = 0, capacity = 0;
	char *text = NULL;
	while (parser->input[pos] != '\0' && parser->input[pos] != '"') {
		unsigned char value = (unsigned char)parser->input[pos++];
		if (value == '\n') ++parser->line;
		if (value == '\\') {
			char escaped = parser->input[pos];
			if (escaped == '\0') {
				free(text);
				return fail_at(parser, token->line, "unterminated escape in string");
			}
			++pos;
			switch (escaped) {
			case 'n': value = '\n'; break;
			case 'b': value = '\b'; break;
			case 'r': value = '\r'; break;
			case 't': value = '\t'; break;
			case 'f': value = '\f'; break;
			case '\n': ++parser->line; continue;
			case 'x': {
				unsigned total = 0, digit = 0, count = 0;
				while (count < 2 && hex_digit(parser->input[pos], &digit)) {
					total = total * 16 + digit;
					++pos; ++count;
				}
				value = (unsigned char)total;
				break;
			}
			default:
				if (escaped >= '0' && escaped <= '7') {
					unsigned total = (unsigned)(escaped - '0'), count = 1;
					if (escaped == '0' && parser->input[pos] == 'x') {
						unsigned digit = 0;
						++pos; total = 0; count = 0;
						while (count < 2 && hex_digit(parser->input[pos], &digit)) {
							total = total * 16 + digit;
							++pos; ++count;
						}
					} else {
						while (count < 3 && parser->input[pos] >= '0' &&
							parser->input[pos] <= '7') {
							total = total * 8 + (unsigned)(parser->input[pos++] - '0');
							++count;
						}
					}
					value = (unsigned char)total;
				} else value = (unsigned char)escaped;
				break;
			}
		}
		if (!append_char(parser, &text, &length, &capacity, (char)value, token->line)) {
			free(text);
			return false;
		}
	}
	if (parser->input[pos] != '"') {
		free(text);
		return fail_at(parser, token->line, "unterminated quoted string");
	}
	if (!append_char(parser, &text, &length, &capacity, '\0', token->line)) {
		free(text);
		return false;
	}
	token->text = text;
	*position = pos + 1;
	return true;
}

static bool next_token(struct parser *parser) {
	free(parser->token.text);
	memset(&parser->token, 0, sizeof(parser->token));
	const char *input = parser->input;
	size_t pos = parser->offset;
	size_t trivia_begin = pos;
	for (;;) {
		while (lex_space(input[pos])) {
			if (input[pos] == '\n') ++parser->line;
			++pos;
		}
		if (input[pos] != '#') break;
		while (input[pos] != '\0' && input[pos] != '\n') ++pos;
		if (input[pos] == '\0')
			return fail_at(parser, parser->line, "invalid character '#'");
	}
	struct token token = {.line = parser->line, .begin = pos,
		.trivia_begin = trivia_begin};
	char ch = input[pos];
	if (ch == '\0') token.type = TOK_EOF;
	else if (ch == '"') {
		token.type = TOK_STRING;
		if (!lex_string(parser, &token, &pos)) return false;
	} else if (ch >= '0' && ch <= '9') {
		token.type = TOK_NUMBER;
		errno = 0;
		char *end = NULL;
		token.number = strtol(input + pos, &end, 10);
		token.number_overflow = errno == ERANGE;
		size_t length = (size_t)(end - (input + pos));
		if (!token_set_text(parser, &token, input + pos, length)) return false;
		pos = (size_t)(end - input);
	} else if (word_char(ch)) {
		token.type = TOK_WORD;
		size_t start = pos;
		while (word_char(input[pos])) ++pos;
		if (!token_set_text(parser, &token, input + start, pos - start)) return false;
	} else {
		switch (ch) {
		case '{': token.type = TOK_LBRACE; break;
		case '}': token.type = TOK_RBRACE; break;
		case '(': token.type = TOK_LPAREN; break;
		case ')': token.type = TOK_RPAREN; break;
		case ':': token.type = TOK_COLON; break;
		case '=': token.type = TOK_EQUALS; break;
		case '|': token.type = TOK_OR; break;
		case '+': token.type = TOK_PLUS; break;
		case '-': token.type = TOK_MINUS; break;
		case '!': case '^':
			token.type = TOK_WORD;
			if (!token_set_text(parser, &token, input + pos, 1)) return false;
			break;
		default:
			return fail_at(parser, token.line, "invalid character '%c'", ch);
		}
		++pos;
	}
	parser->offset = pos;
	parser->token = token;
	return true;
}

static bool expect(struct parser *parser, enum token_type type, const char *name) {
	if (parser->token.type != type) return fail(parser, "expected %s", name);
	return next_token(parser);
}

static bool take_string(struct parser *parser, char *dest, size_t size) {
	if (parser->token.type != TOK_STRING) return fail(parser, "expected a quoted string");
	project_text(parser, dest, size, parser->token.text);
	return next_token(parser);
}

static bool take_number(struct parser *parser, int *value) {
	if (parser->token.type != TOK_NUMBER) return fail(parser, "expected a number");
	if (parser->token.number_overflow || parser->token.number > INT_MAX) {
		return fail(parser, "number '%s' is out of range", parser->token.text);
	}
	*value = (int)parser->token.number;
	return next_token(parser);
}

static void *grow_array(void *old, size_t count, size_t item_size) {
	if (item_size != 0 && count > SIZE_MAX / item_size) return NULL;
	return realloc(old, count * item_size);
}

static bool append_string(struct parser *parser, struct wtwm_string_list *list,
	const char *value) {
	char **items = grow_array(list->items, list->count + 1, sizeof(*items));
	if (items == NULL) return fail(parser, "out of memory");
	list->items = items;
	items[list->count] = strdup(value);
	if (items[list->count] == NULL) return fail(parser, "out of memory");
	++list->count;
	return true;
}

static enum wtwm_compatibility directive_compatibility(const char *name) {
	static const char *const unsupported[] = {
		"NoBackingStore", "NoGrabServer", "NoSaveUnders", "NoVersion",
		"RestartPreviousState", "Priority", "SaveColor",
	};
	static const char *const effective[] = {
		"BorderWidth", "ButtonIndent", "ClientBorderWidth", "Color",
		"Button", "Cursors", "Key",
		"DecorateTransients", "DontSqueezeTitle", "FramePadding", "Function",
		"Grayscale", "Greyscale", "IconBorderWidth", "IconDirectory",
		"IconFont", "IconManagerFont", "Icons", "InterpolateMenuColors",
		"LeftTitleButton", "MakeTitle", "Menu", "MenuBackground", "MenuBorderColor",
		"MenuBorderWidth", "MenuFont", "MenuForeground", "MenuTitleBackground",
		"MenuTitleForeground", "Monochrome", "MoveDelta", "NoDefaults",
		"NoHighlight", "NoMenuShadows", "NoRaiseOnDeiconify", "NoRaiseOnMove",
		"NoRaiseOnResize", "NoTitle", "NoTitleFocus", "NoTitleHighlight",
		"OpaqueMove", "Pixmaps", "RandomPlacement", "ResizeFont",
		"RightTitleButton", "SqueezeTitle", "StartIconified", "TitleBackground",
		"TitleButtonBorderWidth", "TitleFont", "TitleForeground", "TitlePadding",
		"UnknownIcon", "AutoRaise", "AutoRelativeResize", "ConstrainedMoveTime",
		"DontMoveOff", "MaxWindowSize", "UsePPosition",
	};
	static const char *const translated[] = {
		"ClientBorderWidth", "DecorateTransients", "IconFont", "IconManagerFont",
		"MenuFont", "ResizeFont", "TitleFont",
	};
	for (size_t i = 0; i < sizeof(unsupported) / sizeof(unsupported[0]); ++i)
		if (equal_ci(name, unsupported[i])) return WTWM_COMPAT_UNSUPPORTED;
	for (size_t i = 0; i < sizeof(translated) / sizeof(translated[0]); ++i)
		if (equal_ci(name, translated[i])) return WTWM_COMPAT_WAYLAND_TRANSLATED;
	for (size_t i = 0; i < sizeof(effective) / sizeof(effective[0]); ++i)
		if (equal_ci(name, effective[i])) return WTWM_COMPAT_EFFECTIVE;
	return WTWM_COMPAT_PARSED_ONLY;
}

static struct wtwm_directive *append_directive(struct parser *parser,
	const char *name, size_t line) {
	struct wtwm_directive *items = grow_array(parser->config->directives,
		parser->config->directive_count + 1, sizeof(*items));
	if (items == NULL) {
		fail(parser, "out of memory");
		return NULL;
	}
	parser->config->directives = items;
	struct wtwm_directive *record = &items[parser->config->directive_count];
	memset(record, 0, sizeof(*record));
	copy_text(record->name, sizeof(record->name), name);
	record->compatibility = directive_compatibility(name);
	record->line = line;
	record->ordinal = parser->config->directive_count++;
	if (record->compatibility != WTWM_COMPAT_EFFECTIVE) ++parser->config->warning_count;
	return record;
}

static bool set_record_value(struct parser *parser, const char *value) {
	if (parser->record == NULL) return true;
	free(parser->record->value);
	parser->record->value = strdup(value ? value : "");
	if (parser->record->value == NULL) return fail(parser, "out of memory");
	return true;
}

static bool finish_record_source(struct parser *parser, size_t start) {
	if (parser->record == NULL) return true;
	size_t end = parser->token.trivia_begin;
	while (end > start && lex_space(parser->input[end - 1])) --end;
	parser->record->source = strndup(parser->input + start, end - start);
	if (parser->record->source == NULL) return fail(parser, "out of memory");
	return true;
}

static const struct named_action *find_action(const char *name) {
	for (size_t i = 0; i < sizeof(actions) / sizeof(actions[0]); ++i)
		if (equal_ci(name, actions[i].name)) return &actions[i];
	return NULL;
}

static void lowercase_ascii(char *text) {
	for (; *text != '\0'; ++text)
		if (*text >= 'A' && *text <= 'Z') *text = (char)(*text - 'A' + 'a');
}

static bool decimal_string(const char *text) {
	for (; *text != '\0'; ++text)
		if (*text < '0' || *text > '9') return false;
	return true;
}

static bool validate_action_argument(struct parser *parser,
		struct wtwm_action *action) {
	bool valid = true;
	switch (action->type) {
	case WTWM_ACTION_WARPRING:
		lowercase_ascii(action->argument);
		valid = strcmp(action->argument, "next") == 0 ||
			strcmp(action->argument, "prev") == 0;
		break;
	case WTWM_ACTION_WARPTOSCREEN:
		lowercase_ascii(action->argument);
		valid = strcmp(action->argument, "next") == 0 ||
			strcmp(action->argument, "prev") == 0 ||
			strcmp(action->argument, "back") == 0 ||
			decimal_string(action->argument);
		break;
	case WTWM_ACTION_COLORMAP:
		lowercase_ascii(action->argument);
		valid = strcmp(action->argument, "next") == 0 ||
			strcmp(action->argument, "prev") == 0 ||
			strcmp(action->argument, "default") == 0;
		break;
	default:
		break;
	}
	if (!valid) {
		action->type = WTWM_ACTION_NOP;
		action->compatibility = WTWM_COMPAT_EFFECTIVE;
		copy_text(action->name, sizeof(action->name), "f.nop");
		++parser->config->warning_count;
	}
	return valid;
}

static bool parse_action(struct parser *parser, struct wtwm_action *action) {
	if (parser->token.type != TOK_WORD) return fail(parser, "expected an f.action");
	const char *spelling = parser->token.text;
	const struct named_action *named = NULL;
	if (strcmp(spelling, "!") == 0) named = find_action("f.exec");
	else if (strcmp(spelling, "^") == 0) named = find_action("f.cut");
	else named = find_action(spelling);
	if (named == NULL) return fail(parser, "unknown action '%s'", spelling);
	memset(action, 0, sizeof(*action));
	action->type = named->type;
	action->compatibility = named->compatibility;
	project_text(parser, action->name, sizeof(action->name), named->name);
	if (!next_token(parser)) return false;
	if (named->takes_argument) {
		if (parser->token.type != TOK_STRING) return fail(parser, "expected action string argument");
		project_text(parser, action->argument, sizeof(action->argument), parser->token.text);
		if (!next_token(parser)) return false;
	}
	bool valid_argument = validate_action_argument(parser, action);
	if (valid_argument && named->compatibility != WTWM_COMPAT_EFFECTIVE)
		++parser->config->warning_count;
	return true;
}

static uint32_t context_for(const char *name) {
	if (equal_ci(name, "r") || equal_ci(name, "root")) return WTWM_CONTEXT_ROOT;
	if (equal_ci(name, "w") || equal_ci(name, "window")) return WTWM_CONTEXT_WINDOW;
	if (equal_ci(name, "t") || equal_ci(name, "title")) return WTWM_CONTEXT_TITLE;
	if (equal_ci(name, "i") || equal_ci(name, "icon")) return WTWM_CONTEXT_ICON;
	if (equal_ci(name, "f") || equal_ci(name, "frame")) return WTWM_CONTEXT_FRAME;
	if (equal_ci(name, "iconmgr") || equal_ci(name, "m") ||
		equal_ci(name, "meta") || equal_ci(name, "mod")) return WTWM_CONTEXT_ICONMGR;
	if (equal_ci(name, "all")) return WTWM_CONTEXT_ALL;
	return 0;
}

static bool take_modifier(struct parser *parser, uint32_t *modifiers) {
	if (parser->token.type != TOK_WORD) return fail(parser, "invalid modifier");
	const char *name = parser->token.text;
	uint32_t value = 0;
	bool meta = equal_ci(name, "m") || equal_ci(name, "meta") || equal_ci(name, "mod");
	if (equal_ci(name, "s") || equal_ci(name, "shift")) value = WTWM_MOD_SHIFT;
	else if (equal_ci(name, "l") || equal_ci(name, "lock")) value = WTWM_MOD_LOCK;
	else if (equal_ci(name, "c") || equal_ci(name, "control")) value = WTWM_MOD_CONTROL;
	else if (!meta) return fail(parser, "unknown modifier '%s'", name);
	if (!next_token(parser)) return false;
	if (meta) {
		int number = 1;
		if (parser->token.type == TOK_NUMBER && !take_number(parser, &number)) return false;
		if (number < 1 || number > 5) return fail(parser, "modifier number must be 1-5");
		value = WTWM_MOD_META1 << (number - 1);
	}
	*modifiers |= value;
	return true;
}

static bool same_trigger(const struct wtwm_binding *a, const struct wtwm_binding *b) {
	if (a->type != b->type || a->modifiers != b->modifiers ||
		strcmp(a->window_name, b->window_name) != 0) return false;
	if (a->type == WTWM_BINDING_BUTTON) return a->button == b->button;
	return strcmp(a->key, b->key) == 0;
}

static bool add_binding(struct parser *parser, struct wtwm_binding *binding) {
	for (size_t i = 0; i < parser->config->binding_count;) {
		struct wtwm_binding *old = &parser->config->bindings[i];
		if (same_trigger(old, binding)) old->contexts &= ~binding->contexts;
		if (old->contexts == 0) {
			memmove(old, old + 1, (parser->config->binding_count - i - 1) * sizeof(*old));
			--parser->config->binding_count;
			continue;
		}
		++i;
	}
	struct wtwm_binding *items = grow_array(parser->config->bindings,
		parser->config->binding_count + 1, sizeof(*items));
	if (items == NULL) return fail(parser, "out of memory");
	parser->config->bindings = items;
	items[parser->config->binding_count++] = *binding;
	return true;
}

static bool parse_binding_tail(struct parser *parser, struct wtwm_binding *binding,
	bool allow_named_context) {
	if (!expect(parser, TOK_EQUALS, "'='")) return false;
	while (parser->token.type != TOK_COLON) {
		if (parser->token.type == TOK_EOF) return fail(parser, "expected ':' after modifiers");
		if (parser->token.type == TOK_OR) {
			if (!next_token(parser)) return false;
			continue;
		}
		if (!take_modifier(parser, &binding->modifiers)) return false;
	}
	if (!next_token(parser)) return false;
	while (parser->token.type != TOK_COLON) {
		if (parser->token.type == TOK_EOF) return fail(parser, "expected ':' after contexts");
		if (parser->token.type == TOK_OR) {
			if (!next_token(parser)) return false;
			continue;
		}
		if (allow_named_context && parser->token.type == TOK_STRING) {
			project_text(parser, binding->window_name, sizeof(binding->window_name),
				parser->token.text);
			binding->contexts |= WTWM_CONTEXT_WINDOW;
			if (!next_token(parser)) return false;
			continue;
		}
		if (parser->token.type != TOK_WORD) return fail(parser, "invalid context");
		uint32_t context = context_for(parser->token.text);
		if (context == 0) return fail(parser, "unknown context '%s'", parser->token.text);
		binding->contexts |= context;
		if (!next_token(parser)) return false;
	}
	if (!next_token(parser)) return false;
	if (!parse_action(parser, &binding->action)) return false;
	return add_binding(parser, binding);
}

static bool parse_button(struct parser *parser) {
	int number = 0;
	if (!take_number(parser, &number)) return false;
	if (number < 1 || number > 16) return fail(parser, "button number must be 1-16");
	struct wtwm_binding binding = {
		.type = WTWM_BINDING_BUTTON,
		.button = (unsigned)number,
	};
	if (parser->token.type == TOK_EQUALS)
		return parse_binding_tail(parser, &binding, false);
	binding.contexts = WTWM_CONTEXT_ROOT;
	if (parser->token.type == TOK_STRING) {
		binding.action.type = WTWM_ACTION_MENU;
		binding.action.compatibility = WTWM_COMPAT_EFFECTIVE;
		copy_text(binding.action.name, sizeof(binding.action.name), "f.menu");
		project_text(parser, binding.action.argument, sizeof(binding.action.argument),
			parser->token.text);
		if (!set_record_value(parser, parser->token.text) || !next_token(parser)) return false;
	} else if (!parse_action(parser, &binding.action)) return false;
	return add_binding(parser, &binding);
}

static bool parse_key(struct parser *parser, const char *key) {
	struct wtwm_binding binding = {.type = WTWM_BINDING_KEY};
	project_text(parser, binding.key, sizeof(binding.key), key);
	return parse_binding_tail(parser, &binding, true);
}

static bool parse_menu_colors(struct parser *parser, char *foreground,
	size_t foreground_size, char *background, size_t background_size) {
	if (parser->token.type != TOK_LPAREN) return true;
	if (!next_token(parser) || !take_string(parser, foreground, foreground_size) ||
		!expect(parser, TOK_COLON, "':'") ||
		!take_string(parser, background, background_size) ||
		!expect(parser, TOK_RPAREN, "')'")) return false;
	return true;
}

static struct wtwm_menu *get_menu(struct parser *parser, const char *name) {
	for (size_t i = 0; i < parser->config->menu_count; ++i)
		if (strcmp(parser->config->menus[i].name, name) == 0) return &parser->config->menus[i];
	struct wtwm_menu *items = grow_array(parser->config->menus,
		parser->config->menu_count + 1, sizeof(*items));
	if (items == NULL) {
		fail(parser, "out of memory");
		return NULL;
	}
	parser->config->menus = items;
	struct wtwm_menu *menu = &items[parser->config->menu_count++];
	memset(menu, 0, sizeof(*menu));
	project_text(parser, menu->name, sizeof(menu->name), name);
	return menu;
}

static bool parse_menu(struct parser *parser) {
	if (parser->token.type != TOK_STRING) return fail(parser, "expected menu name");
	char *name = strdup(parser->token.text);
	if (name == NULL) return fail(parser, "out of memory");
	if (!set_record_value(parser, name) || !next_token(parser)) { free(name); return false; }
	struct wtwm_menu *menu = get_menu(parser, name);
	free(name);
	if (menu == NULL) return false;
	if (!parse_menu_colors(parser, menu->foreground, sizeof(menu->foreground),
		menu->background, sizeof(menu->background))) return false;
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated menu");
		struct wtwm_menu_item item = {0};
		if (!take_string(parser, item.label, sizeof(item.label)) ||
			!parse_menu_colors(parser, item.foreground, sizeof(item.foreground),
				item.background, sizeof(item.background)) ||
			!parse_action(parser, &item.action)) return false;
		struct wtwm_menu_item *items = grow_array(menu->items,
			menu->item_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		menu->items = items;
		items[menu->item_count++] = item;
	}
	return next_token(parser);
}

static struct wtwm_function *get_function(struct parser *parser, const char *name) {
	for (size_t i = 0; i < parser->config->function_count; ++i)
		if (strcmp(parser->config->functions[i].name, name) == 0)
			return &parser->config->functions[i];
	struct wtwm_function *items = grow_array(parser->config->functions,
		parser->config->function_count + 1, sizeof(*items));
	if (items == NULL) {
		fail(parser, "out of memory");
		return NULL;
	}
	parser->config->functions = items;
	struct wtwm_function *function = &items[parser->config->function_count++];
	memset(function, 0, sizeof(*function));
	project_text(parser, function->name, sizeof(function->name), name);
	return function;
}

static bool parse_function(struct parser *parser) {
	if (parser->token.type != TOK_STRING) return fail(parser, "expected function name");
	char *name = strdup(parser->token.text);
	if (name == NULL) return fail(parser, "out of memory");
	if (!set_record_value(parser, name) || !next_token(parser)) { free(name); return false; }
	struct wtwm_function *function = get_function(parser, name);
	free(name);
	if (function == NULL || !expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated function");
		struct wtwm_action action = {0};
		if (!parse_action(parser, &action)) return false;
		struct wtwm_action *items = grow_array(function->actions,
			function->action_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		function->actions = items;
		items[function->action_count++] = action;
	}
	return next_token(parser);
}

static bool parse_title_button(struct parser *parser, bool right_side) {
	struct wtwm_title_button *items = grow_array(parser->config->title_buttons,
		parser->config->title_button_count + 1, sizeof(*items));
	if (items == NULL) return fail(parser, "out of memory");
	parser->config->title_buttons = items;
	struct wtwm_title_button *button = &items[parser->config->title_button_count++];
	memset(button, 0, sizeof(*button));
	button->right_side = right_side;
	if (parser->token.type != TOK_STRING) return fail(parser, "expected title-button bitmap");
	if (!set_record_value(parser, parser->token.text) ||
		!take_string(parser, button->bitmap, sizeof(button->bitmap)) ||
		!expect(parser, TOK_EQUALS, "'='")) return false;
	return parse_action(parser, &button->action);
}

static struct wtwm_string_list *exposed_list(struct wtwm_config *config,
	const char *name) {
	if (equal_ci(name, "NoTitle")) return &config->no_title_windows;
	if (equal_ci(name, "MakeTitle")) return &config->make_title_windows;
	if (equal_ci(name, "AutoRaise")) return &config->auto_raise_windows;
	if (equal_ci(name, "StartIconified")) return &config->start_iconified_windows;
	return NULL;
}

static bool parse_window_list(struct parser *parser, const char *name,
	bool optional, bool bare_sets_no_title) {
	struct wtwm_window_list *items = grow_array(parser->config->window_lists,
		parser->config->window_list_count + 1, sizeof(*items));
	if (items == NULL) return fail(parser, "out of memory");
	parser->config->window_lists = items;
	struct wtwm_window_list *list = &items[parser->config->window_list_count++];
	memset(list, 0, sizeof(*list));
	copy_text(list->directive, sizeof(list->directive), name);
	if (parser->token.type != TOK_LBRACE) {
		if (!optional) return fail(parser, "expected '{' after %s", name);
		list->bare = true;
		if (bare_sets_no_title) parser->config->no_title = true;
		if (equal_ci(name, "DontSqueezeTitle"))
			parser->config->squeeze_title = false;
		return true;
	}
	if (!next_token(parser)) return false;
	struct wtwm_string_list *exposed = exposed_list(parser->config, name);
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated %s list", name);
		if (parser->token.type != TOK_STRING) return fail(parser, "expected a window name");
		if (!append_string(parser, &list->names, parser->token.text) ||
			(exposed != NULL && !append_string(parser, exposed, parser->token.text)) ||
			!next_token(parser)) return false;
	}
	return next_token(parser);
}

struct flag_option {
	const char *name;
	size_t offset;
	bool value;
};

#define FLAG(name, field, value) {name, offsetof(struct wtwm_config, field), value}
#define FLAG_ONLY(name) {name, SIZE_MAX, true}
static const struct flag_option flag_options[] = {
	FLAG("AutoRelativeResize", auto_relative_resize, true),
	FLAG("ClientBorderWidth", client_border_width, true),
	FLAG("DecorateTransients", decorate_transients, true),
	FLAG("DontMoveOff", dont_move_off, true), FLAG("ForceIcons", force_icons, true),
	FLAG("InterpolateMenuColors", interpolate_menu_colors, true),
	FLAG("NoBackingStore", no_backing_store, true), FLAG("NoCaseSensitive", case_sensitive, false),
	FLAG("NoDefaults", no_defaults, true), FLAG("NoGrabServer", no_grab_server, true),
	FLAG("NoIconManagers", no_icon_managers, true), FLAG("NoMenuShadows", no_menu_shadows, true),
	FLAG("NoRaiseOnDeiconify", no_raise_on_deiconify, true),
	FLAG("NoRaiseOnMove", no_raise_on_move, true), FLAG("NoRaiseOnResize", no_raise_on_resize, true),
	FLAG("NoRaiseOnWarp", no_raise_on_warp, true), FLAG("NoSaveUnders", no_save_unders, true),
	FLAG("NoTitleFocus", no_title_focus, true), FLAG_ONLY("NoVersion"),
	FLAG("OpaqueMove", opaque_move, true), FLAG("RandomPlacement", random_placement, true),
	FLAG("RestartPreviousState", restart_previous_state, true),
	FLAG("ShowIconManager", show_icon_manager, true), FLAG("SortIconManager", sort_icon_manager, true),
	FLAG("WarpUnmapped", warp_unmapped, true),
};
#undef FLAG
#undef FLAG_ONLY

struct int_option { const char *name; size_t offset; };
#define INT_OPT(name, field) {name, offsetof(struct wtwm_config, field)}
static const struct int_option int_options[] = {
	INT_OPT("BorderWidth", border_width), INT_OPT("ButtonIndent", button_indent),
	INT_OPT("ConstrainedMoveTime", constrained_move_time), INT_OPT("FramePadding", frame_padding),
	INT_OPT("IconBorderWidth", icon_border_width), INT_OPT("MenuBorderWidth", menu_border_width),
	INT_OPT("MoveDelta", move_delta), INT_OPT("Priority", priority),
	INT_OPT("TitleButtonBorderWidth", title_button_border_width),
	INT_OPT("TitlePadding", title_padding), INT_OPT("XorValue", xor_value),
};
#undef INT_OPT

struct string_option { const char *name; size_t offset; };
#define STRING_OPT(name, field) {name, offsetof(struct wtwm_config, field)}
static const struct string_option string_options[] = {
	STRING_OPT("IconDirectory", icon_directory), STRING_OPT("IconFont", icon_font),
	STRING_OPT("IconManagerFont", icon_manager_font),
	STRING_OPT("MenuFont", menu_font), STRING_OPT("ResizeFont", resize_font),
	STRING_OPT("TitleFont", title_font), STRING_OPT("UnknownIcon", unknown_icon),
};
#undef STRING_OPT

struct color_option { const char *name; size_t offset; bool list; };
#define COLOR_OPT(name, field, list) {name, offsetof(struct wtwm_config, field), list}
static const struct color_option color_options[] = {
	COLOR_OPT("BorderColor", border_color, true),
	COLOR_OPT("BorderTileBackground", border_tile_background, true),
	COLOR_OPT("BorderTileForeground", border_tile_foreground, true),
	COLOR_OPT("DefaultBackground", default_background, false),
	COLOR_OPT("DefaultForeground", default_foreground, false),
	COLOR_OPT("IconBackground", icon_background, true),
	COLOR_OPT("IconBorderColor", icon_border_color, true),
	COLOR_OPT("IconForeground", icon_foreground, true),
	COLOR_OPT("IconManagerBackground", icon_manager_background, true),
	COLOR_OPT("IconManagerForeground", icon_manager_foreground, true),
	COLOR_OPT("IconManagerHighlight", icon_manager_highlight, true),
	COLOR_OPT("MenuBackground", menu_background, false),
	COLOR_OPT("MenuBorderColor", menu_border_color, false),
	COLOR_OPT("MenuForeground", menu_foreground, false),
	COLOR_OPT("MenuShadowColor", menu_shadow_color, false),
	COLOR_OPT("MenuTitleBackground", menu_title_background, false),
	COLOR_OPT("MenuTitleForeground", menu_title_foreground, false),
	COLOR_OPT("PointerBackground", pointer_background, false),
	COLOR_OPT("PointerForeground", pointer_foreground, false),
	COLOR_OPT("TitleBackground", title_background, true),
	COLOR_OPT("TitleForeground", title_foreground, true),
};
#undef COLOR_OPT

static const struct color_option *find_color_option(const char *name) {
	for (size_t i = 0; i < sizeof(color_options) / sizeof(color_options[0]); ++i)
		if (equal_ci(name, color_options[i].name)) return &color_options[i];
	return NULL;
}

static bool parse_color_block(struct parser *parser, enum wtwm_color_mode mode) {
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated color block");
		if (parser->token.type != TOK_WORD) return fail(parser, "expected a color keyword");
		const struct color_option *option = find_color_option(parser->token.text);
		if (option == NULL) return fail(parser, "unknown color keyword '%s'", parser->token.text);
		struct wtwm_color_setting *items = grow_array(parser->config->colors,
			parser->config->color_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		parser->config->colors = items;
		struct wtwm_color_setting *setting = &items[parser->config->color_count++];
		memset(setting, 0, sizeof(*setting));
		copy_text(setting->name, sizeof(setting->name), option->name);
		setting->mode = mode;
		if (!next_token(parser) || !take_string(parser, setting->value,
			sizeof(setting->value))) return false;
		char *slot = (char *)parser->config + option->offset;
		copy_text(slot, WTWM_NAME_MAX, setting->value);
		if (parser->token.type == TOK_LBRACE) {
			if (!option->list) return fail(parser, "%s does not accept a window color list", option->name);
			if (!next_token(parser)) return false;
			while (parser->token.type != TOK_RBRACE) {
				struct wtwm_window_value pair = {0};
				if (parser->token.type == TOK_EOF) return fail(parser, "unterminated window color list");
				if (!take_string(parser, pair.name, sizeof(pair.name)) ||
					!take_string(parser, pair.value, sizeof(pair.value))) return false;
				struct wtwm_window_value *pairs = grow_array(setting->overrides,
					setting->override_count + 1, sizeof(*pairs));
				if (pairs == NULL) return fail(parser, "out of memory");
				setting->overrides = pairs;
				memmove(pairs + 1, pairs, setting->override_count * sizeof(*pairs));
				pairs[0] = pair;
				++setting->override_count;
			}
			if (!next_token(parser)) return false;
		}
	}
	return next_token(parser);
}

static bool parse_save_color(struct parser *parser) {
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated SaveColor block");
		if (parser->token.type == TOK_STRING) {
			if (!append_string(parser, &parser->config->saved_colors, parser->token.text) ||
				!next_token(parser)) return false;
		} else if (parser->token.type == TOK_WORD) {
			const struct color_option *option = find_color_option(parser->token.text);
			if (option == NULL || !option->list)
				return fail(parser, "invalid SaveColor keyword '%s'", parser->token.text);
			if (!append_string(parser, &parser->config->saved_colors, option->name) ||
				!next_token(parser)) return false;
		} else return fail(parser, "expected a color name");
	}
	return next_token(parser);
}

static bool cursor_role(const char *name) {
	static const char *const roles[] = {
		"F", "Frame", "T", "Title", "I", "Icon", "IconMgr", "M", "Meta",
		"Mod", "Button", "Move", "Resize", "Wait", "Menu", "Select", "Destroy",
	};
	for (size_t i = 0; i < sizeof(roles) / sizeof(roles[0]); ++i)
		if (equal_ci(name, roles[i])) return true;
	return false;
}

static bool parse_cursors(struct parser *parser) {
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated Cursors block");
		if (parser->token.type != TOK_WORD || !cursor_role(parser->token.text))
			return fail(parser, "unknown cursor role '%s'", parser->token.text ? parser->token.text : "");
		struct wtwm_cursor *items = grow_array(parser->config->cursors,
			parser->config->cursor_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		parser->config->cursors = items;
		struct wtwm_cursor *cursor = &items[parser->config->cursor_count++];
		memset(cursor, 0, sizeof(*cursor));
		project_text(parser, cursor->role, sizeof(cursor->role), parser->token.text);
		if (!next_token(parser) || !take_string(parser, cursor->source, sizeof(cursor->source)))
			return false;
		if (parser->token.type == TOK_STRING &&
			!take_string(parser, cursor->mask, sizeof(cursor->mask))) return false;
	}
	return next_token(parser);
}

static bool parse_pixmaps(struct parser *parser) {
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated Pixmaps block");
		if (parser->token.type != TOK_WORD || !equal_ci(parser->token.text, "TitleHighlight"))
			return fail(parser, "expected TitleHighlight pixmap");
		struct wtwm_pixmap *items = grow_array(parser->config->pixmaps,
			parser->config->pixmap_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		parser->config->pixmaps = items;
		struct wtwm_pixmap *pixmap = &items[parser->config->pixmap_count++];
		memset(pixmap, 0, sizeof(*pixmap));
		copy_text(pixmap->name, sizeof(pixmap->name), "TitleHighlight");
		if (!next_token(parser) || !take_string(parser, pixmap->value, sizeof(pixmap->value)))
			return false;
	}
	return next_token(parser);
}

static bool is_direction(const char *name) {
	return equal_ci(name, "North") || equal_ci(name, "South") ||
		equal_ci(name, "East") || equal_ci(name, "West");
}

static bool parse_icon_region(struct parser *parser) {
	struct wtwm_icon_region *items = grow_array(parser->config->icon_regions,
		parser->config->icon_region_count + 1, sizeof(*items));
	if (items == NULL) return fail(parser, "out of memory");
	parser->config->icon_regions = items;
	struct wtwm_icon_region *region = &items[parser->config->icon_region_count++];
	memset(region, 0, sizeof(*region));
	if (!take_string(parser, region->geometry, sizeof(region->geometry))) return false;
	if (parser->token.type != TOK_WORD || !is_direction(parser->token.text))
		return fail(parser, "expected vertical gravity");
	project_text(parser, region->vertical_gravity, sizeof(region->vertical_gravity), parser->token.text);
	if (!next_token(parser)) return false;
	if (parser->token.type != TOK_WORD || !is_direction(parser->token.text))
		return fail(parser, "expected horizontal gravity");
	project_text(parser, region->horizontal_gravity, sizeof(region->horizontal_gravity), parser->token.text);
	return next_token(parser) && take_number(parser, &region->grid_width) &&
		take_number(parser, &region->grid_height);
}

static bool parse_icon_manager_geometry(struct parser *parser) {
	if (!take_string(parser, parser->config->icon_manager_geometry,
		sizeof(parser->config->icon_manager_geometry))) return false;
	parser->config->icon_manager_columns = 0;
	if (parser->token.type == TOK_NUMBER)
		return take_number(parser, &parser->config->icon_manager_columns);
	return true;
}

static bool parse_icon_managers(struct parser *parser) {
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated IconManagers block");
		struct wtwm_icon_manager *items = grow_array(parser->config->icon_managers,
			parser->config->icon_manager_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		parser->config->icon_managers = items;
		memmove(items + 1, items, parser->config->icon_manager_count * sizeof(*items));
		struct wtwm_icon_manager *manager = &items[0];
		++parser->config->icon_manager_count;
		memset(manager, 0, sizeof(*manager));
		char second[WTWM_NAME_MAX];
		if (!take_string(parser, manager->window_name, sizeof(manager->window_name)) ||
			!take_string(parser, second, sizeof(second))) return false;
		if (parser->token.type == TOK_STRING) {
			copy_text(manager->icon_name, sizeof(manager->icon_name), second);
			if (!take_string(parser, manager->geometry, sizeof(manager->geometry))) return false;
		} else {
			copy_text(manager->geometry, sizeof(manager->geometry), second);
		}
		if (!take_number(parser, &manager->columns)) return false;
	}
	return next_token(parser);
}

static bool parse_icons(struct parser *parser) {
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated Icons block");
		struct wtwm_icon_mapping *items = grow_array(parser->config->icons,
			parser->config->icon_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		parser->config->icons = items;
		memmove(items + 1, items, parser->config->icon_count * sizeof(*items));
		struct wtwm_icon_mapping *icon = &items[0];
		++parser->config->icon_count;
		memset(icon, 0, sizeof(*icon));
		if (!take_string(parser, icon->window_name, sizeof(icon->window_name)) ||
			!take_string(parser, icon->bitmap, sizeof(icon->bitmap))) return false;
	}
	return next_token(parser);
}

static bool is_justification(const char *name) {
	return equal_ci(name, "Left") || equal_ci(name, "Center") || equal_ci(name, "Right");
}

static bool take_signed_number(struct parser *parser, int *value) {
	bool negative = false;
	if (parser->token.type == TOK_PLUS || parser->token.type == TOK_MINUS) {
		negative = parser->token.type == TOK_MINUS;
		if (!next_token(parser)) return false;
	}
	int number = 0;
	if (!take_number(parser, &number)) return false;
	*value = negative ? -number : number;
	return true;
}

static bool parse_squeeze_title(struct parser *parser) {
	if (parser->token.type != TOK_LBRACE) {
		parser->config->squeeze_title = true;
		return true;
	}
	if (!next_token(parser)) return false;
	while (parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated SqueezeTitle block");
		struct wtwm_squeeze_entry *items = grow_array(parser->config->squeeze_entries,
			parser->config->squeeze_entry_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		parser->config->squeeze_entries = items;
		struct wtwm_squeeze_entry *entry = &items[parser->config->squeeze_entry_count++];
		memset(entry, 0, sizeof(*entry));
		if (!take_string(parser, entry->window_name, sizeof(entry->window_name))) return false;
		if (parser->token.type != TOK_WORD || !is_justification(parser->token.text))
			return fail(parser, "expected squeeze justification");
		project_text(parser, entry->justification, sizeof(entry->justification), parser->token.text);
		if (!next_token(parser) || !take_signed_number(parser, &entry->numerator) ||
			!take_number(parser, &entry->denominator)) return false;
	}
	return next_token(parser);
}

static bool is_window_list_directive(const char *name, bool *optional,
	bool *no_title_bare) {
	static const struct { const char *name; bool optional; } lists[] = {
		{"AutoRaise", false}, {"DontIconifyByUnmapping", false},
		{"DontSqueezeTitle", true}, {"IconifyByUnmapping", true},
		{"IconManagerDontShow", true}, {"IconManagerShow", false},
		{"MakeTitle", false}, {"NoHighlight", true}, {"NoStackMode", true},
		{"NoTitle", true}, {"NoTitleHighlight", true}, {"StartIconified", false},
		{"WarpCursor", true}, {"WindowRing", false},
	};
	for (size_t i = 0; i < sizeof(lists) / sizeof(lists[0]); ++i) {
		if (equal_ci(name, lists[i].name)) {
			*optional = lists[i].optional;
			*no_title_bare = equal_ci(name, "NoTitle");
			return true;
		}
	}
	return false;
}

static bool parse_statement_body(struct parser *parser, const char *keyword,
	enum token_type keyword_type) {
	if (keyword_type == TOK_STRING) return parse_key(parser, keyword);
	if (equal_ci(keyword, "Button")) return parse_button(parser);
	if (equal_ci(keyword, "Color"))
		return parse_color_block(parser, WTWM_COLOR_MODE_COLOR);
	if (equal_ci(keyword, "Grayscale") || equal_ci(keyword, "Greyscale"))
		return parse_color_block(parser, WTWM_COLOR_MODE_GRAYSCALE);
	if (equal_ci(keyword, "Monochrome"))
		return parse_color_block(parser, WTWM_COLOR_MODE_MONOCHROME);
	if (equal_ci(keyword, "SaveColor")) return parse_save_color(parser);
	if (equal_ci(keyword, "Menu")) return parse_menu(parser);
	if (equal_ci(keyword, "Function")) return parse_function(parser);
	if (equal_ci(keyword, "LeftTitleButton")) return parse_title_button(parser, false);
	if (equal_ci(keyword, "RightTitleButton")) return parse_title_button(parser, true);
	if (equal_ci(keyword, "Cursors")) return parse_cursors(parser);
	if (equal_ci(keyword, "Pixmaps")) return parse_pixmaps(parser);
	if (equal_ci(keyword, "IconRegion")) return parse_icon_region(parser);
	if (equal_ci(keyword, "IconManagerGeometry")) return parse_icon_manager_geometry(parser);
	if (equal_ci(keyword, "IconManagers")) return parse_icon_managers(parser);
	if (equal_ci(keyword, "Icons")) return parse_icons(parser);
	if (equal_ci(keyword, "SqueezeTitle")) return parse_squeeze_title(parser);
	if (equal_ci(keyword, "DefaultFunction")) return parse_action(parser, &parser->config->default_function);
	if (equal_ci(keyword, "WindowFunction")) return parse_action(parser, &parser->config->window_function);
	if (equal_ci(keyword, "Zoom")) {
		parser->config->zoom = true;
		parser->config->zoom_count = 0;
		if (parser->token.type == TOK_NUMBER)
			return take_number(parser, &parser->config->zoom_count);
		return true;
	}
	if (equal_ci(keyword, "UsePPosition")) {
		if (parser->token.type != TOK_STRING)
			return fail(parser, "expected a quoted string");
		if (!set_record_value(parser, parser->token.text)) return false;
		enum wtwm_use_p_position mode;
		if (wtwm_parse_use_p_position(parser->token.text, &mode)) {
			parser->config->use_p_position_mode = mode;
		} else {
			/* Reference twm warns, keeps PPOS_OFF, and continues parsing. */
			++parser->config->warning_count;
		}
		return take_string(parser, parser->config->use_p_position,
			sizeof(parser->config->use_p_position));
	}
	if (equal_ci(keyword, "MaxWindowSize")) {
		if (parser->token.type != TOK_STRING)
			return fail(parser, "expected a quoted string");
		int width = 0, height = 0;
		if (!wtwm_parse_max_window_size(parser->token.text, &width, &height))
			return fail(parser, "MaxWindowSize must contain positive width and height");
		if (!set_record_value(parser, parser->token.text)) return false;
		parser->config->max_window_width = width;
		parser->config->max_window_height = height;
		parser->config->max_window_size_set = true;
		return take_string(parser, parser->config->max_window_size,
			sizeof(parser->config->max_window_size));
	}
	bool optional = false, no_title_bare = false;
	if (is_window_list_directive(keyword, &optional, &no_title_bare))
		return parse_window_list(parser, keyword, optional, no_title_bare);
	for (size_t i = 0; i < sizeof(flag_options) / sizeof(flag_options[0]); ++i) {
		if (equal_ci(keyword, flag_options[i].name)) {
			if (flag_options[i].offset != SIZE_MAX) {
				bool *slot = (bool *)((char *)parser->config + flag_options[i].offset);
				*slot = flag_options[i].value;
			}
			return true;
		}
	}
	for (size_t i = 0; i < sizeof(int_options) / sizeof(int_options[0]); ++i) {
		if (equal_ci(keyword, int_options[i].name)) {
			int value = 0;
			if (!take_number(parser, &value)) return false;
			*(int *)((char *)parser->config + int_options[i].offset) = value;
			char text[64];
			snprintf(text, sizeof(text), "%d", value);
			return set_record_value(parser, text);
		}
	}
	for (size_t i = 0; i < sizeof(string_options) / sizeof(string_options[0]); ++i) {
		if (equal_ci(keyword, string_options[i].name)) {
			if (parser->token.type != TOK_STRING) return fail(parser, "expected a quoted string");
			if (!set_record_value(parser, parser->token.text)) return false;
			char *slot = (char *)parser->config + string_options[i].offset;
			return take_string(parser, slot, WTWM_NAME_MAX);
		}
	}
	return fail_at(parser, parser->record ? parser->record->line : parser->token.line,
		"unknown keyword '%s'", keyword);
}

static bool parse_statement(struct parser *parser) {
	if (parser->token.type != TOK_WORD && parser->token.type != TOK_STRING)
		return fail(parser, "expected a directive");
	size_t statement_start = parser->token.begin;
	size_t line = parser->token.line;
	enum token_type keyword_type = parser->token.type;
	char *keyword = strdup(parser->token.text);
	if (keyword == NULL) return fail(parser, "out of memory");
	const char *record_name = keyword_type == TOK_STRING ? "Key" : keyword;
	parser->record = append_directive(parser, record_name, line);
	if (parser->record == NULL) { free(keyword); return false; }
	if (!next_token(parser)) { free(keyword); return false; }
	bool result = parse_statement_body(parser, keyword, keyword_type);
	free(keyword);
	if (!result) return false;
	return finish_record_source(parser, statement_start);
}

void wtwm_config_init(struct wtwm_config *config) {
	memset(config, 0, sizeof(*config));
	config->border_width = 2;
	config->title_button_border_width = 1;
	config->title_padding = 8;
	config->frame_padding = 2;
	config->button_indent = 1;
	config->move_delta = 1;
	config->constrained_move_time = 400;
	config->menu_border_width = 2;
	config->icon_border_width = 2;
	config->case_sensitive = true;
	config->use_p_position_mode = WTWM_USE_P_POSITION_OFF;
	copy_text(config->use_p_position, sizeof(config->use_p_position), "off");
	copy_text(config->title_font, sizeof(config->title_font), "Sans Bold 10");
	copy_text(config->menu_font, sizeof(config->menu_font), "Sans Bold 10");
	copy_text(config->resize_font, sizeof(config->resize_font), "Sans Bold 10");
	copy_text(config->icon_font, sizeof(config->icon_font), "Sans 10");
	copy_text(config->icon_manager_font, sizeof(config->icon_manager_font), "Sans 10");
	copy_text(config->border_color, sizeof(config->border_color), "slategrey");
	copy_text(config->title_background, sizeof(config->title_background), "rgb:2/a/9");
	copy_text(config->title_foreground, sizeof(config->title_foreground), "gray85");
	copy_text(config->menu_background, sizeof(config->menu_background), "rgb:2/a/9");
	copy_text(config->menu_foreground, sizeof(config->menu_foreground), "gray85");
	copy_text(config->menu_border_color, sizeof(config->menu_border_color), "slategrey");
	copy_text(config->menu_title_background, sizeof(config->menu_title_background), "gray70");
	copy_text(config->menu_title_foreground, sizeof(config->menu_title_foreground), "rgb:2/a/9");
}

static void finish_string_list(struct wtwm_string_list *list) {
	for (size_t i = 0; i < list->count; ++i) free(list->items[i]);
	free(list->items);
}

void wtwm_config_finish(struct wtwm_config *config) {
	for (size_t i = 0; i < config->menu_count; ++i) free(config->menus[i].items);
	for (size_t i = 0; i < config->function_count; ++i) free(config->functions[i].actions);
	for (size_t i = 0; i < config->window_list_count; ++i)
		finish_string_list(&config->window_lists[i].names);
	for (size_t i = 0; i < config->color_count; ++i) free(config->colors[i].overrides);
	for (size_t i = 0; i < config->directive_count; ++i) {
		free(config->directives[i].source);
		free(config->directives[i].value);
	}
	free(config->bindings);
	free(config->menus);
	free(config->functions);
	free(config->title_buttons);
	free(config->window_lists);
	free(config->colors);
	free(config->cursors);
	free(config->pixmaps);
	free(config->icon_regions);
	free(config->icon_managers);
	free(config->icons);
	free(config->squeeze_entries);
	free(config->directives);
	free(config->source_text);
	finish_string_list(&config->saved_colors);
	finish_string_list(&config->no_title_windows);
	finish_string_list(&config->make_title_windows);
	finish_string_list(&config->auto_raise_windows);
	finish_string_list(&config->start_iconified_windows);
	memset(config, 0, sizeof(*config));
}

static void replace_config(struct wtwm_config *destination,
	struct wtwm_config *replacement) {
	wtwm_config_finish(destination);
	*destination = *replacement;
	memset(replacement, 0, sizeof(*replacement));
}

bool wtwm_config_parse(struct wtwm_config *config, const char *source_name,
	const char *text, char *error, size_t error_size) {
	if (error != NULL && error_size > 0) error[0] = '\0';
	if (text == NULL) {
		if (error != NULL && error_size > 0) snprintf(error, error_size, "%s:1: null input",
			source_name ? source_name : "<config>");
		return false;
	}
	struct wtwm_config replacement;
	wtwm_config_init(&replacement);
	replacement.source_text = strdup(text);
	if (replacement.source_text == NULL) {
		wtwm_config_finish(&replacement);
		if (error != NULL && error_size > 0) snprintf(error, error_size, "%s:1: out of memory",
			source_name ? source_name : "<config>");
		return false;
	}
	struct parser parser = {
		.config = &replacement,
		.source_name = source_name ? source_name : "<config>",
		.input = text,
		.line = 1,
		.error = error,
		.error_size = error_size,
	};
	bool result = next_token(&parser);
	while (result && parser.token.type != TOK_EOF) result = parse_statement(&parser);
	free(parser.token.text);
	if (!result) {
		wtwm_config_finish(&replacement);
		return false;
	}
	replace_config(config, &replacement);
	return true;
}

static bool read_file(const char *path, char **text, char *error, size_t error_size) {
	FILE *file = fopen(path, "rb");
	if (file == NULL) return false;
	if (fseek(file, 0, SEEK_END) != 0) {
		if (error != NULL && error_size > 0) snprintf(error, error_size, "%s: %s", path, strerror(errno));
		fclose(file);
		return false;
	}
	long length = ftell(file);
	if (length < 0 || fseek(file, 0, SEEK_SET) != 0) {
		if (error != NULL && error_size > 0) snprintf(error, error_size, "%s: %s", path, strerror(errno));
		fclose(file);
		return false;
	}
	char *buffer = malloc((size_t)length + 1);
	if (buffer == NULL) {
		if (error != NULL && error_size > 0) snprintf(error, error_size, "%s: out of memory", path);
		fclose(file);
		return false;
	}
	size_t count = fread(buffer, 1, (size_t)length, file);
	if (count != (size_t)length && ferror(file)) {
		if (error != NULL && error_size > 0) snprintf(error, error_size, "%s: %s", path, strerror(errno));
		free(buffer);
		fclose(file);
		return false;
	}
	buffer[count] = '\0';
	fclose(file);
	*text = buffer;
	return true;
}

static const char built_in_twmrc[] =
	"NoGrabServer\n"
	"RestartPreviousState\n"
	"DecorateTransients\n"
	"TitleFont \"-adobe-helvetica-bold-r-normal--*-120-*-*-*-*-*-*\"\n"
	"ResizeFont \"-adobe-helvetica-bold-r-normal--*-120-*-*-*-*-*-*\"\n"
	"MenuFont \"-adobe-helvetica-bold-r-normal--*-120-*-*-*-*-*-*\"\n"
	"IconFont \"-adobe-helvetica-bold-r-normal--*-100-*-*-*-*-*-*\"\n"
	"IconManagerFont \"-adobe-helvetica-bold-r-normal--*-100-*-*-*\"\n"
	"Color {\n"
	" BorderColor \"slategrey\"\n DefaultBackground \"rgb:2/a/9\"\n"
	" DefaultForeground \"gray85\"\n TitleBackground \"rgb:2/a/9\"\n"
	" TitleForeground \"gray85\"\n MenuBackground \"rgb:2/a/9\"\n"
	" MenuForeground \"gray85\"\n MenuBorderColor \"slategrey\"\n"
	" MenuTitleBackground \"gray70\"\n MenuTitleForeground \"rgb:2/a/9\"\n"
	" IconBackground \"rgb:2/a/9\"\n IconForeground \"gray85\"\n"
	" IconBorderColor \"gray85\"\n IconManagerBackground \"rgb:2/a/9\"\n"
	" IconManagerForeground \"gray85\"\n}\n"
	"MoveDelta 3\n"
	"Function \"move-or-lower\" { f.move f.deltastop f.lower }\n"
	"Function \"move-or-raise\" { f.move f.deltastop f.raise }\n"
	"Function \"move-or-iconify\" { f.move f.deltastop f.iconify }\n"
	"Button1 = : root : f.menu \"defops\"\n"
	"Button1 = m : window|icon : f.function \"move-or-lower\"\n"
	"Button2 = m : window|icon : f.iconify\n"
	"Button3 = m : window|icon : f.function \"move-or-raise\"\n"
	"Button1 = : title : f.function \"move-or-raise\"\n"
	"Button2 = : title : f.raiselower\n"
	"Button1 = : icon : f.function \"move-or-iconify\"\n"
	"Button2 = : icon : f.iconify\n"
	"Button1 = : iconmgr : f.iconify\n"
	"Button2 = : iconmgr : f.iconify\n"
	"Menu \"defops\" {\n"
	" \"Twm\" f.title \"Iconify\" f.iconify \"Resize\" f.resize\n"
	" \"Move\" f.move \"Raise\" f.raise \"Lower\" f.lower \"\" f.nop\n"
	" \"Focus\" f.focus \"Unfocus\" f.unfocus\n"
	" \"Show Iconmgr\" f.showiconmgr \"Hide Iconmgr\" f.hideiconmgr\n"
	" \"\" f.nop \"Xterm\" f.exec \"exec xterm &\" \"\" f.nop\n"
	" \"Kill\" f.destroy \"Delete\" f.delete \"\" f.nop\n"
	" \"Restart\" f.restart \"Exit\" f.quit\n}\n";

bool wtwm_config_load_for_screen(struct wtwm_config *config, const char *path,
	unsigned screen, char *error, size_t error_size) {
	if (error != NULL && error_size > 0) error[0] = '\0';
	char screen_path[4096] = "";
	char general_path[4096] = "";
	const char *home = getenv("HOME");
	if (home != NULL) {
		snprintf(screen_path, sizeof(screen_path), "%s/.twmrc.%u", home, screen);
		snprintf(general_path, sizeof(general_path), "%s/.twmrc", home);
	}
	const char *system_override = getenv("WTWM_SYSTEM_CONFIG");
	const char *system_path = system_override && system_override[0] ?
		system_override : WTWM_SYSTEM_CONFIG;
	const char *candidates[] = {
		path,
		path == NULL ? screen_path : NULL,
		path == NULL ? general_path : NULL,
		system_path,
	};
	for (size_t i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
		const char *candidate = candidates[i];
		if (candidate == NULL || candidate[0] == '\0') continue;
		char *text = NULL;
		char io_error[512] = "";
		if (!read_file(candidate, &text, io_error, sizeof(io_error))) {
			if (io_error[0] != '\0') {
				if (error != NULL && error_size > 0) copy_text(error, error_size, io_error);
				return false;
			}
			continue;
		}
		bool result = wtwm_config_parse(config, candidate, text, error, error_size);
		free(text);
		return result;
	}
	return wtwm_config_parse(config, "<built-in defaults>", built_in_twmrc,
		error, error_size);
}

bool wtwm_config_load(struct wtwm_config *config, const char *path,
	char *error, size_t error_size) {
	return wtwm_config_load_for_screen(config, path, 0, error, error_size);
}

static bool exact_match(const struct wtwm_string_list *list, const char *value) {
	if (value == NULL) return false;
	for (size_t i = list->count; i > 0; --i)
		if (strcmp(list->items[i - 1], value) == 0) return true;
	return false;
}

bool wtwm_config_match_x11(const struct wtwm_string_list *list,
	const char *name, const char *resource_name, const char *resource_class) {
	return exact_match(list, name) || exact_match(list, resource_name) ||
		exact_match(list, resource_class);
}

bool wtwm_config_match_native(const struct wtwm_string_list *list,
	const char *title, const char *app_id) {
	return exact_match(list, title) || exact_match(list, app_id);
}

bool wtwm_config_match_client(const struct wtwm_string_list *list,
	const struct wtwm_client_identity *identity) {
	if (identity == NULL) return false;
	if (identity->name != NULL || identity->resource_name != NULL ||
		identity->resource_class != NULL)
		return wtwm_config_match_x11(list, identity->name, identity->resource_name,
			identity->resource_class);
	return wtwm_config_match_native(list, identity->title, identity->app_id);
}

bool wtwm_config_window_list_matches(const struct wtwm_config *config,
		const char *directive, const struct wtwm_client_identity *identity) {
	if (config == NULL || directive == NULL) return false;
	for (size_t i = config->window_list_count; i > 0; --i) {
		const struct wtwm_window_list *list = &config->window_lists[i - 1];
		if (!equal_ci(list->directive, directive)) continue;
		if (list->bare || wtwm_config_match_client(&list->names, identity))
			return true;
	}
	return false;
}

static bool identity_value_matches(const struct wtwm_client_identity *identity,
		const char *selector, unsigned pass) {
	if (identity == NULL || selector == NULL) return false;
	const char *value = NULL;
	bool x11 = identity->name != NULL || identity->resource_name != NULL ||
		identity->resource_class != NULL;
	if (x11) {
		if (pass == 0) value = identity->name;
		else if (pass == 1) value = identity->resource_name;
		else if (pass == 2) value = identity->resource_class;
	} else {
		if (pass == 0) value = identity->title;
		else if (pass == 1) value = identity->app_id;
	}
	return value != NULL && strcmp(selector, value) == 0;
}

static const struct wtwm_squeeze_entry *matching_squeeze_entry(
		const struct wtwm_config *config,
		const struct wtwm_client_identity *identity) {
	for (unsigned pass = 0; pass < 3; ++pass) {
		for (size_t i = config->squeeze_entry_count; i > 0; --i) {
			const struct wtwm_squeeze_entry *entry = &config->squeeze_entries[i - 1];
			if (identity_value_matches(identity, entry->window_name, pass))
				return entry;
		}
	}
	return NULL;
}

bool wtwm_config_squeeze_rule(const struct wtwm_config *config,
		const struct wtwm_client_identity *identity,
		struct wtwm_squeeze_rule *rule) {
	if (config == NULL || rule == NULL) return false;
	for (size_t i = config->window_list_count; i > 0; --i) {
		const struct wtwm_window_list *list = &config->window_lists[i - 1];
		if (equal_ci(list->directive, "DontSqueezeTitle") && !list->bare &&
			wtwm_config_match_client(&list->names, identity)) return false;
	}
	const struct wtwm_squeeze_entry *entry =
		matching_squeeze_entry(config, identity);
	if (entry == NULL && !config->squeeze_title) return false;
	*rule = (struct wtwm_squeeze_rule){WTWM_SQUEEZE_LEFT, 0, 0};
	if (entry == NULL) return true;
	if (equal_ci(entry->justification, "center"))
		rule->justification = WTWM_SQUEEZE_CENTER;
	else if (equal_ci(entry->justification, "right"))
		rule->justification = WTWM_SQUEEZE_RIGHT;
	rule->numerator = entry->numerator;
	rule->denominator = entry->denominator;
	return true;
}

const char *wtwm_config_color_value(const struct wtwm_config *config,
		const char *name, enum wtwm_color_mode mode,
		const struct wtwm_client_identity *identity) {
	if (config == NULL || name == NULL) return NULL;
	const char *base = NULL;
	for (size_t i = config->color_count; i > 0; --i) {
		const struct wtwm_color_setting *setting = &config->colors[i - 1];
		if (setting->mode != mode || !equal_ci(setting->name, name)) continue;
		if (base == NULL) base = setting->value;
	}
	if (identity == NULL) return base;
	for (unsigned pass = 0; pass < 3; ++pass)
		for (size_t i = config->color_count; i > 0; --i) {
			const struct wtwm_color_setting *setting = &config->colors[i - 1];
			if (setting->mode != mode || !equal_ci(setting->name, name)) continue;
			for (size_t j = 0; j < setting->override_count; ++j)
				if (identity_value_matches(identity,
						setting->overrides[j].name, pass))
					return setting->overrides[j].value;
		}
	return base;
}

static bool prefix_match(const char *selector, const char *value) {
	return selector != NULL && value != NULL &&
		strncmp(selector, value, strlen(selector)) == 0;
}

bool wtwm_config_prefix_x11(const char *selector, const char *name,
	const char *resource_name, const char *resource_class) {
	return prefix_match(selector, name) || prefix_match(selector, resource_name) ||
		prefix_match(selector, resource_class);
}

bool wtwm_config_prefix_native(const char *selector, const char *title,
	const char *app_id) {
	return prefix_match(selector, title) || prefix_match(selector, app_id);
}

static const char *action_name(enum wtwm_action_type type) {
	for (size_t i = 0; i < sizeof(actions) / sizeof(actions[0]); ++i)
		if (actions[i].type == type && actions[i].compatibility == WTWM_COMPAT_EFFECTIVE)
			return actions[i].name;
	return "unsupported";
}

static const char *compatibility_name(enum wtwm_compatibility compatibility) {
	switch (compatibility) {
	case WTWM_COMPAT_EFFECTIVE: return "effective";
	case WTWM_COMPAT_WAYLAND_TRANSLATED: return "wayland-translated";
	case WTWM_COMPAT_PARSED_ONLY: return "parsed-only";
	case WTWM_COMPAT_UNSUPPORTED: return "unsupported";
	}
	return "invalid";
}

static void dump_escaped(FILE *stream, const char *text) {
	fputc('"', stream);
	for (const unsigned char *p = (const unsigned char *)(text ? text : ""); *p; ++p) {
		switch (*p) {
		case '\n': fputs("\\n", stream); break;
		case '\r': fputs("\\r", stream); break;
		case '\t': fputs("\\t", stream); break;
		case '\\': fputs("\\\\", stream); break;
		case '"': fputs("\\\"", stream); break;
		default:
			if (*p < 0x20 || *p == 0x7f) fprintf(stream, "\\x%02x", *p);
			else fputc(*p, stream);
			break;
		}
	}
	fputc('"', stream);
}

void wtwm_config_dump(const struct wtwm_config *config, FILE *stream) {
	fprintf(stream, "border-width=%d\n", config->border_width);
	fprintf(stream, "title-button-border-width=%d\n", config->title_button_border_width);
	fprintf(stream, "title-padding=%d\nframe-padding=%d\nbutton-indent=%d\n",
		config->title_padding, config->frame_padding, config->button_indent);
	fprintf(stream, "move-delta=%d\nconstrained-move-time=%d\nmenu-border-width=%d\n",
		config->move_delta, config->constrained_move_time, config->menu_border_width);
	fprintf(stream, "icon-border-width=%d\npriority=%d\nxor-value=%d\nzoom=%d\nzoom-count=%d\n",
		config->icon_border_width, config->priority, config->xor_value,
		config->zoom, config->zoom_count);
	fprintf(stream, "no-defaults=%d\nno-grab-server=%d\nno-icon-managers=%d\ntitle-focus=%d\n",
		config->no_defaults, config->no_grab_server, config->no_icon_managers,
		!config->no_title_focus);
#define DUMP_BOOL(field) fprintf(stream, #field "=%d\n", config->field)
	DUMP_BOOL(no_title); DUMP_BOOL(decorate_transients); DUMP_BOOL(opaque_move);
	DUMP_BOOL(random_placement); DUMP_BOOL(dont_move_off); DUMP_BOOL(no_raise_on_move);
	DUMP_BOOL(no_raise_on_resize); DUMP_BOOL(no_raise_on_deiconify);
	DUMP_BOOL(no_menu_shadows); DUMP_BOOL(no_title_focus); DUMP_BOOL(auto_relative_resize);
	DUMP_BOOL(client_border_width); DUMP_BOOL(case_sensitive); DUMP_BOOL(show_icon_manager);
	DUMP_BOOL(force_icons); DUMP_BOOL(no_icon_managers); DUMP_BOOL(interpolate_menu_colors);
	DUMP_BOOL(no_grab_server); DUMP_BOOL(no_backing_store); DUMP_BOOL(no_save_unders);
	DUMP_BOOL(restart_previous_state); DUMP_BOOL(no_raise_on_warp); DUMP_BOOL(warp_unmapped);
	DUMP_BOOL(sort_icon_manager); DUMP_BOOL(no_defaults);
#undef DUMP_BOOL
#define DUMP_STRING(field) do { fputs(#field "=", stream); dump_escaped(stream, config->field); fputc('\n', stream); } while (0)
	DUMP_STRING(title_font); DUMP_STRING(menu_font); DUMP_STRING(resize_font);
	DUMP_STRING(icon_font); DUMP_STRING(icon_manager_font); DUMP_STRING(icon_directory);
	DUMP_STRING(unknown_icon); DUMP_STRING(max_window_size); DUMP_STRING(use_p_position);
	DUMP_STRING(icon_manager_geometry); DUMP_STRING(border_color);
	DUMP_STRING(border_tile_background); DUMP_STRING(border_tile_foreground);
	DUMP_STRING(title_background); DUMP_STRING(title_foreground); DUMP_STRING(icon_background);
	DUMP_STRING(icon_foreground); DUMP_STRING(icon_border_color);
	DUMP_STRING(icon_manager_background); DUMP_STRING(icon_manager_foreground);
	DUMP_STRING(icon_manager_highlight); DUMP_STRING(default_background);
	DUMP_STRING(default_foreground); DUMP_STRING(menu_background); DUMP_STRING(menu_foreground);
	DUMP_STRING(menu_border_color); DUMP_STRING(menu_shadow_color);
	DUMP_STRING(menu_title_background); DUMP_STRING(menu_title_foreground);
	DUMP_STRING(pointer_background); DUMP_STRING(pointer_foreground);
#undef DUMP_STRING
	fprintf(stream, "bindings=%zu\n", config->binding_count);
	for (size_t i = 0; i < config->binding_count; ++i) {
		const struct wtwm_binding *binding = &config->bindings[i];
		if (binding->type == WTWM_BINDING_BUTTON) fprintf(stream, "  button=%u", binding->button);
		else fprintf(stream, "  key=%s", binding->key);
		fprintf(stream, " mods=0x%x contexts=0x%x action=%s", binding->modifiers,
			binding->contexts, action_name(binding->action.type));
		if (binding->action.argument[0]) fprintf(stream, " %s", binding->action.argument);
		fputc('\n', stream);
	}
	fprintf(stream, "menus=%zu\n", config->menu_count);
	for (size_t i = 0; i < config->menu_count; ++i)
		fprintf(stream, "  %s items=%zu\n", config->menus[i].name, config->menus[i].item_count);
	fprintf(stream, "functions=%zu\n", config->function_count);
	for (size_t i = 0; i < config->function_count; ++i)
		fprintf(stream, "  %s actions=%zu\n", config->functions[i].name,
			config->functions[i].action_count);
	fprintf(stream, "title-buttons=%zu\n", config->title_button_count);
	fprintf(stream, "window-lists=%zu\n", config->window_list_count);
	for (size_t i = 0; i < config->window_list_count; ++i)
		fprintf(stream, "  %s bare=%d names=%zu\n", config->window_lists[i].directive,
			config->window_lists[i].bare, config->window_lists[i].names.count);
	fprintf(stream, "colors=%zu\ncursors=%zu\npixmaps=%zu\nicon-regions=%zu\n",
		config->color_count, config->cursor_count, config->pixmap_count,
		config->icon_region_count);
	fprintf(stream, "icon-managers=%zu\nicons=%zu\nsqueeze-entries=%zu\nsaved-colors=%zu\n",
		config->icon_manager_count, config->icon_count, config->squeeze_entry_count,
		config->saved_colors.count);
	fprintf(stream, "directives=%zu\n", config->directive_count);
	for (size_t i = 0; i < config->directive_count; ++i) {
		const struct wtwm_directive *directive = &config->directives[i];
		fprintf(stream, "  %zu name=%s line=%zu compatibility=%s value=", i,
			directive->name, directive->line,
			compatibility_name(directive->compatibility));
		dump_escaped(stream, directive->value);
		fputs(" source=", stream);
		dump_escaped(stream, directive->source);
		fputc('\n', stream);
	}
	fprintf(stream, "compatibility-warnings=%zu\n", config->warning_count);
	fprintf(stream, "projection-truncations=%zu\n", config->projection_truncation_count);
}
