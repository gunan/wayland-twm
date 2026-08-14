/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "wtwm/config.h"

#include <ctype.h>
#include <errno.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#ifndef WTWM_SYSTEM_CONFIG
#define WTWM_SYSTEM_CONFIG "/usr/share/wtwm/system.twmrc"
#endif

enum token_type {
	TOK_EOF,
	TOK_NEWLINE,
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
	char text[WTWM_ACTION_MAX];
	long number;
	size_t line;
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
};

struct named_action {
	const char *name;
	enum wtwm_action_type type;
	bool takes_argument;
};

static const struct named_action actions[] = {
	{"f.beep", WTWM_ACTION_BEEP, false},
	{"f.delete", WTWM_ACTION_DELETE, false},
	{"f.deiconify", WTWM_ACTION_DEICONIFY, false},
	{"f.deltastop", WTWM_ACTION_DELTASTOP, false},
	{"f.destroy", WTWM_ACTION_DESTROY, false},
	{"f.exec", WTWM_ACTION_EXEC, true},
	{"f.focus", WTWM_ACTION_FOCUS, false},
	{"f.forcemove", WTWM_ACTION_FORCEMOVE, false},
	{"f.fullzoom", WTWM_ACTION_FULLZOOM, false},
	{"f.function", WTWM_ACTION_FUNCTION, true},
	{"f.hbzoom", WTWM_ACTION_BOTTOMZOOM, false},
	{"f.horizoom", WTWM_ACTION_ZOOM, false},
	{"f.htzoom", WTWM_ACTION_TOPZOOM, false},
	{"f.hzoom", WTWM_ACTION_ZOOM, false},
	{"f.iconify", WTWM_ACTION_ICONIFY, false},
	{"f.leftzoom", WTWM_ACTION_LEFTZOOM, false},
	{"f.lower", WTWM_ACTION_LOWER, false},
	{"f.menu", WTWM_ACTION_MENU, true},
	{"f.move", WTWM_ACTION_MOVE, false},
	{"f.nop", WTWM_ACTION_NOP, false},
	{"f.quit", WTWM_ACTION_QUIT, false},
	{"f.raise", WTWM_ACTION_RAISE, false},
	{"f.raiselower", WTWM_ACTION_RAISELOWER, false},
	{"f.refresh", WTWM_ACTION_REFRESH, false},
	{"f.resize", WTWM_ACTION_RESIZE, false},
	{"f.restart", WTWM_ACTION_RESTART, false},
	{"f.rightzoom", WTWM_ACTION_RIGHTZOOM, false},
	{"f.title", WTWM_ACTION_TITLE, false},
	{"f.topzoom", WTWM_ACTION_TOPZOOM, false},
	{"f.twmrc", WTWM_ACTION_RESTART, false},
	{"f.unfocus", WTWM_ACTION_UNFOCUS, false},
	{"f.warpnext", WTWM_ACTION_WARPNEXT, false},
	{"f.warpprev", WTWM_ACTION_WARPPREV, false},
	{"f.warpto", WTWM_ACTION_WARPTO, true},
	{"f.zoom", WTWM_ACTION_ZOOM, false},
};

static bool equal_ci(const char *a, const char *b) {
	for (; *a && *b; ++a, ++b) {
		if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) {
			return false;
		}
	}
	return *a == *b;
}

static void copy_text(char *dest, size_t size, const char *source) {
	if (size == 0) {
		return;
	}
	snprintf(dest, size, "%s", source ? source : "");
}

static bool fail(struct parser *parser, const char *format, ...) {
	if (parser->error != NULL && parser->error_size > 0 && parser->error[0] == '\0') {
		int used = snprintf(parser->error, parser->error_size, "%s:%zu: ",
			parser->source_name, parser->token.line);
		if (used < 0 || (size_t)used >= parser->error_size) {
			return false;
		}
		va_list args;
		va_start(args, format);
		vsnprintf(parser->error + used, parser->error_size - (size_t)used,
			format, args);
		va_end(args);
	}
	return false;
}

static void next_token(struct parser *parser) {
	const char *input = parser->input;
	size_t pos = parser->offset;
	for (;;) {
		while (input[pos] == ' ' || input[pos] == '\t' || input[pos] == '\r') {
			++pos;
		}
		if (input[pos] != '#') {
			break;
		}
		while (input[pos] && input[pos] != '\n') {
			++pos;
		}
	}
	struct token token = {.line = parser->line};
	char ch = input[pos];
	if (ch == '\0') {
		token.type = TOK_EOF;
	} else if (ch == '\n') {
		token.type = TOK_NEWLINE;
		++parser->line;
		++pos;
	} else if (ch == '"') {
		token.type = TOK_STRING;
		++pos;
		size_t out = 0;
		while (input[pos] && input[pos] != '"') {
			char value = input[pos++];
			if (value == '\\' && input[pos]) {
				value = input[pos++];
			}
			if (value == '\n') {
				++parser->line;
			}
			if (out + 1 < sizeof(token.text)) {
				token.text[out++] = value;
			}
		}
		if (input[pos] == '"') {
			++pos;
		}
		token.text[out] = '\0';
	} else if (isdigit((unsigned char)ch)) {
		token.type = TOK_NUMBER;
		char *end = NULL;
		errno = 0;
		token.number = strtol(input + pos, &end, 0);
		size_t length = (size_t)(end - (input + pos));
		if (length >= sizeof(token.text)) {
			length = sizeof(token.text) - 1;
		}
		memcpy(token.text, input + pos, length);
		token.text[length] = '\0';
		pos = (size_t)(end - input);
	} else {
		switch (ch) {
		case '{': token.type = TOK_LBRACE; ++pos; break;
		case '}': token.type = TOK_RBRACE; ++pos; break;
		case '(': token.type = TOK_LPAREN; ++pos; break;
		case ')': token.type = TOK_RPAREN; ++pos; break;
		case ':': token.type = TOK_COLON; ++pos; break;
		case '=': token.type = TOK_EQUALS; ++pos; break;
		case '|': token.type = TOK_OR; ++pos; break;
		case '+': token.type = TOK_PLUS; ++pos; break;
		case '-': token.type = TOK_MINUS; ++pos; break;
		default: {
			token.type = TOK_WORD;
			size_t out = 0;
			while (input[pos] && !isspace((unsigned char)input[pos]) &&
				strchr("{}():=|+#\"", input[pos]) == NULL) {
				if (out + 1 < sizeof(token.text)) {
					token.text[out++] = input[pos];
				}
				++pos;
			}
			token.text[out] = '\0';
			break;
		}
		}
	}
	parser->offset = pos;
	parser->token = token;
}

static void skip_newlines(struct parser *parser) {
	while (parser->token.type == TOK_NEWLINE) {
		next_token(parser);
	}
}

static bool accept(struct parser *parser, enum token_type type) {
	if (parser->token.type != type) {
		return false;
	}
	next_token(parser);
	return true;
}

static bool expect(struct parser *parser, enum token_type type, const char *name) {
	if (!accept(parser, type)) {
		return fail(parser, "expected %s", name);
	}
	return true;
}

static bool take_text(struct parser *parser, char *dest, size_t size) {
	if (parser->token.type != TOK_STRING && parser->token.type != TOK_WORD) {
		return fail(parser, "expected a string");
	}
	copy_text(dest, size, parser->token.text);
	next_token(parser);
	return true;
}

static void *grow_array(void *old, size_t count, size_t item_size) {
	if (count > SIZE_MAX / item_size) {
		return NULL;
	}
	return realloc(old, count * item_size);
}

static bool append_string(struct parser *parser, struct wtwm_string_list *list,
	const char *value) {
	char **items = grow_array(list->items, list->count + 1, sizeof(*items));
	if (items == NULL) {
		return fail(parser, "out of memory");
	}
	list->items = items;
	list->items[list->count] = strdup(value);
	if (list->items[list->count] == NULL) {
		return fail(parser, "out of memory");
	}
	++list->count;
	return true;
}

static bool parse_action(struct parser *parser, struct wtwm_action *action) {
	if (parser->token.type != TOK_WORD) {
		return fail(parser, "expected an f.action");
	}
	memset(action, 0, sizeof(*action));
	copy_text(action->name, sizeof(action->name), parser->token.text);
	action->type = WTWM_ACTION_UNSUPPORTED;
	bool takes_argument = false;
	if (strcmp(action->name, "!") == 0) {
		action->type = WTWM_ACTION_EXEC;
		takes_argument = true;
		copy_text(action->name, sizeof(action->name), "f.exec");
	} else if (strcmp(action->name, "^") == 0) {
		takes_argument = true;
		copy_text(action->name, sizeof(action->name), "f.cut");
	}
	for (size_t i = 0; i < sizeof(actions) / sizeof(actions[0]); ++i) {
		if (equal_ci(action->name, actions[i].name)) {
			action->type = actions[i].type;
			takes_argument = actions[i].takes_argument;
			break;
		}
	}
	if (strncmp(action->name, "f.", 2) != 0 && strncmp(action->name, "F.", 2) != 0) {
		return fail(parser, "expected an f.action, got '%s'", action->name);
	}
	next_token(parser);
	if (takes_argument) {
		if (!take_text(parser, action->argument, sizeof(action->argument))) {
			return false;
		}
	} else if (action->type == WTWM_ACTION_UNSUPPORTED &&
		(parser->token.type == TOK_STRING)) {
		take_text(parser, action->argument, sizeof(action->argument));
	}
	return true;
}

static uint32_t modifier_for(const char *name) {
	if (equal_ci(name, "s") || equal_ci(name, "shift")) return WTWM_MOD_SHIFT;
	if (equal_ci(name, "l") || equal_ci(name, "lock")) return WTWM_MOD_LOCK;
	if (equal_ci(name, "c") || equal_ci(name, "control")) return WTWM_MOD_CONTROL;
	if (equal_ci(name, "m") || equal_ci(name, "meta") || equal_ci(name, "mod")) return WTWM_MOD_META1;
	if (equal_ci(name, "m1")) return WTWM_MOD_META1;
	if (equal_ci(name, "m2")) return WTWM_MOD_META2;
	if (equal_ci(name, "m3")) return WTWM_MOD_META3;
	if (equal_ci(name, "m4")) return WTWM_MOD_META4;
	if (equal_ci(name, "m5")) return WTWM_MOD_META5;
	if (equal_ci(name, "mod1")) return WTWM_MOD_META1;
	if (equal_ci(name, "mod2")) return WTWM_MOD_META2;
	if (equal_ci(name, "mod3")) return WTWM_MOD_META3;
	if (equal_ci(name, "mod4")) return WTWM_MOD_META4;
	if (equal_ci(name, "mod5")) return WTWM_MOD_META5;
	return 0;
}

static uint32_t context_for(const char *name) {
	if (equal_ci(name, "r") || equal_ci(name, "root")) return WTWM_CONTEXT_ROOT;
	if (equal_ci(name, "w") || equal_ci(name, "window")) return WTWM_CONTEXT_WINDOW;
	if (equal_ci(name, "t") || equal_ci(name, "title")) return WTWM_CONTEXT_TITLE;
	if (equal_ci(name, "i") || equal_ci(name, "icon")) return WTWM_CONTEXT_ICON;
	if (equal_ci(name, "frame")) return WTWM_CONTEXT_FRAME;
	if (equal_ci(name, "iconmgr")) return WTWM_CONTEXT_ICONMGR;
	if (equal_ci(name, "m") || equal_ci(name, "meta")) return WTWM_CONTEXT_ICONMGR;
	if (equal_ci(name, "all")) return WTWM_CONTEXT_ALL;
	return 0;
}

static bool parse_binding(struct parser *parser, const char *trigger,
	bool button, unsigned button_number) {
	struct wtwm_binding binding = {
		.type = button ? WTWM_BINDING_BUTTON : WTWM_BINDING_KEY,
		.button = button_number,
	};
	if (!button) copy_text(binding.key, sizeof(binding.key), trigger);
	if (!expect(parser, TOK_EQUALS, "'='")) return false;
	while (parser->token.type != TOK_COLON && parser->token.type != TOK_EOF) {
		if (parser->token.type == TOK_OR) {
			next_token(parser);
			continue;
		}
		if (parser->token.type != TOK_WORD) return fail(parser, "invalid modifier");
		uint32_t modifier = modifier_for(parser->token.text);
		if (modifier == 0) return fail(parser, "unknown modifier '%s'", parser->token.text);
		binding.modifiers |= modifier;
		next_token(parser);
	}
	if (!expect(parser, TOK_COLON, "':'")) return false;
	while (parser->token.type != TOK_COLON && parser->token.type != TOK_EOF) {
		if (parser->token.type == TOK_OR) {
			next_token(parser);
			continue;
		}
		if (parser->token.type == TOK_STRING) {
			copy_text(binding.window_name, sizeof(binding.window_name), parser->token.text);
			binding.contexts |= WTWM_CONTEXT_WINDOW;
			next_token(parser);
			continue;
		}
		if (parser->token.type != TOK_WORD) return fail(parser, "invalid context");
		uint32_t context = context_for(parser->token.text);
		if (context == 0) return fail(parser, "unknown context '%s'", parser->token.text);
		binding.contexts |= context;
		next_token(parser);
	}
	if (!expect(parser, TOK_COLON, "':'")) return false;
	if (!parse_action(parser, &binding.action)) return false;
	struct wtwm_binding *items = grow_array(parser->config->bindings,
		parser->config->binding_count + 1, sizeof(*items));
	if (items == NULL) return fail(parser, "out of memory");
	parser->config->bindings = items;
	items[parser->config->binding_count++] = binding;
	return true;
}

static bool parse_menu_colors(struct parser *parser, char *foreground,
	size_t foreground_size, char *background, size_t background_size) {
	if (!accept(parser, TOK_LPAREN)) return true;
	if (!take_text(parser, foreground, foreground_size)) return false;
	if (!expect(parser, TOK_COLON, "':'")) return false;
	if (!take_text(parser, background, background_size)) return false;
	return expect(parser, TOK_RPAREN, "')'");
}

static bool parse_menu(struct parser *parser) {
	struct wtwm_menu menu = {0};
	if (!take_text(parser, menu.name, sizeof(menu.name))) return false;
	if (!parse_menu_colors(parser, menu.foreground, sizeof(menu.foreground),
		menu.background, sizeof(menu.background))) return false;
	skip_newlines(parser);
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	for (;;) {
		skip_newlines(parser);
		if (accept(parser, TOK_RBRACE)) break;
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated menu");
		struct wtwm_menu_item item = {0};
		if (!take_text(parser, item.label, sizeof(item.label))) return false;
		if (!parse_menu_colors(parser, item.foreground, sizeof(item.foreground),
			item.background, sizeof(item.background))) return false;
		if (!parse_action(parser, &item.action)) return false;
		struct wtwm_menu_item *items = grow_array(menu.items,
			menu.item_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		menu.items = items;
		items[menu.item_count++] = item;
	}
	struct wtwm_menu *menus = grow_array(parser->config->menus,
		parser->config->menu_count + 1, sizeof(*menus));
	if (menus == NULL) return fail(parser, "out of memory");
	parser->config->menus = menus;
	menus[parser->config->menu_count++] = menu;
	return true;
}

static bool parse_function(struct parser *parser) {
	struct wtwm_function function = {0};
	if (!take_text(parser, function.name, sizeof(function.name))) return false;
	skip_newlines(parser);
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	for (;;) {
		skip_newlines(parser);
		if (accept(parser, TOK_RBRACE)) break;
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated function");
		struct wtwm_action action = {0};
		if (!parse_action(parser, &action)) return false;
		struct wtwm_action *items = grow_array(function.actions,
			function.action_count + 1, sizeof(*items));
		if (items == NULL) return fail(parser, "out of memory");
		function.actions = items;
		items[function.action_count++] = action;
	}
	struct wtwm_function *functions = grow_array(parser->config->functions,
		parser->config->function_count + 1, sizeof(*functions));
	if (functions == NULL) return fail(parser, "out of memory");
	parser->config->functions = functions;
	functions[parser->config->function_count++] = function;
	return true;
}

static bool parse_title_button(struct parser *parser, bool right_side) {
	struct wtwm_title_button title_button = {.right_side = right_side};
	if (!take_text(parser, title_button.bitmap, sizeof(title_button.bitmap))) return false;
	if (!expect(parser, TOK_EQUALS, "'='")) return false;
	if (!parse_action(parser, &title_button.action)) return false;
	struct wtwm_title_button *buttons = grow_array(parser->config->title_buttons,
		parser->config->title_button_count + 1, sizeof(*buttons));
	if (buttons == NULL) return fail(parser, "out of memory");
	parser->config->title_buttons = buttons;
	buttons[parser->config->title_button_count++] = title_button;
	return true;
}

static bool parse_window_list(struct parser *parser, struct wtwm_string_list *list) {
	skip_newlines(parser);
	if (!accept(parser, TOK_LBRACE)) return true;
	for (;;) {
		skip_newlines(parser);
		if (accept(parser, TOK_RBRACE)) return true;
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated window list");
		char name[WTWM_NAME_MAX];
		if (!take_text(parser, name, sizeof(name))) return false;
		if (!append_string(parser, list, name)) return false;
	}
}

static char *color_slot(struct wtwm_config *config, const char *name) {
	if (equal_ci(name, "BorderColor")) return config->border_color;
	if (equal_ci(name, "TitleBackground")) return config->title_background;
	if (equal_ci(name, "TitleForeground")) return config->title_foreground;
	if (equal_ci(name, "MenuBackground")) return config->menu_background;
	if (equal_ci(name, "MenuForeground")) return config->menu_foreground;
	if (equal_ci(name, "MenuBorderColor")) return config->menu_border_color;
	if (equal_ci(name, "MenuTitleBackground")) return config->menu_title_background;
	if (equal_ci(name, "MenuTitleForeground")) return config->menu_title_foreground;
	return NULL;
}

static bool skip_balanced_block(struct parser *parser) {
	if (!accept(parser, TOK_LBRACE)) return true;
	unsigned depth = 1;
	while (depth > 0 && parser->token.type != TOK_EOF) {
		if (parser->token.type == TOK_LBRACE) ++depth;
		if (parser->token.type == TOK_RBRACE) --depth;
		next_token(parser);
	}
	return depth == 0 || fail(parser, "unterminated block");
}

static bool parse_color_block(struct parser *parser) {
	skip_newlines(parser);
	if (!expect(parser, TOK_LBRACE, "'{'")) return false;
	for (;;) {
		skip_newlines(parser);
		if (accept(parser, TOK_RBRACE)) return true;
		if (parser->token.type == TOK_EOF) return fail(parser, "unterminated color block");
		if (parser->token.type != TOK_WORD) return fail(parser, "expected a color name");
		char key[WTWM_NAME_MAX];
		copy_text(key, sizeof(key), parser->token.text);
		next_token(parser);
		char value[WTWM_NAME_MAX];
		if (!take_text(parser, value, sizeof(value))) return false;
		char *slot = color_slot(parser->config, key);
		if (slot != NULL) copy_text(slot, WTWM_NAME_MAX, value);
		skip_newlines(parser);
		if (parser->token.type == TOK_LBRACE && !skip_balanced_block(parser)) return false;
	}
}

struct bool_option {
	const char *name;
	size_t offset;
	bool value;
};

#define BOOL_OPTION(name, field, value) {name, offsetof(struct wtwm_config, field), value}
static const struct bool_option bool_options[] = {
	BOOL_OPTION("AutoRelativeResize", auto_relative_resize, true),
	BOOL_OPTION("ClientBorderWidth", client_border_width, true),
	BOOL_OPTION("DecorateTransients", decorate_transients, true),
	BOOL_OPTION("DontMoveOff", dont_move_off, true),
	BOOL_OPTION("NoCaseSensitive", case_sensitive, false),
	BOOL_OPTION("NoMenuShadows", no_menu_shadows, true),
	BOOL_OPTION("NoRaiseOnDeiconify", no_raise_on_deiconify, true),
	BOOL_OPTION("NoRaiseOnMove", no_raise_on_move, true),
	BOOL_OPTION("NoRaiseOnResize", no_raise_on_resize, true),
	BOOL_OPTION("NoTitleFocus", no_title_focus, true),
	BOOL_OPTION("OpaqueMove", opaque_move, true),
	BOOL_OPTION("RandomPlacement", random_placement, true),
	BOOL_OPTION("ShowIconManager", show_icon_manager, true),
};

struct int_option { const char *name; size_t offset; };
#define INT_OPTION(name, field) {name, offsetof(struct wtwm_config, field)}
static const struct int_option int_options[] = {
	INT_OPTION("BorderWidth", border_width),
	INT_OPTION("ButtonIndent", button_indent),
	INT_OPTION("ConstrainedMoveTime", constrained_move_time),
	INT_OPTION("FramePadding", frame_padding),
	INT_OPTION("MenuBorderWidth", menu_border_width),
	INT_OPTION("MoveDelta", move_delta),
	INT_OPTION("TitleButtonBorderWidth", title_button_border_width),
	INT_OPTION("TitlePadding", title_padding),
};

struct string_option { const char *name; size_t offset; };
#define STRING_OPTION(name, field) {name, offsetof(struct wtwm_config, field)}
static const struct string_option string_options[] = {
	STRING_OPTION("IconFont", icon_font),
	STRING_OPTION("IconManagerFont", icon_manager_font),
	STRING_OPTION("MenuFont", menu_font),
	STRING_OPTION("ResizeFont", resize_font),
	STRING_OPTION("TitleFont", title_font),
};

static void skip_statement(struct parser *parser) {
	while (parser->token.type != TOK_EOF && parser->token.type != TOK_NEWLINE &&
		parser->token.type != TOK_RBRACE) {
		if (parser->token.type == TOK_LBRACE) {
			skip_balanced_block(parser);
			continue;
		}
		next_token(parser);
	}
}

static bool parse_statement(struct parser *parser) {
	if (parser->token.type != TOK_WORD && parser->token.type != TOK_STRING) {
		return fail(parser, "expected a directive");
	}
	char keyword[WTWM_NAME_MAX];
	copy_text(keyword, sizeof(keyword), parser->token.text);
	enum token_type keyword_type = parser->token.type;
	next_token(parser);

	if (equal_ci(keyword, "Color") || equal_ci(keyword, "Monochrome") ||
		equal_ci(keyword, "Grayscale") || equal_ci(keyword, "Greyscale")) {
		return parse_color_block(parser);
	}
	if (equal_ci(keyword, "Menu")) return parse_menu(parser);
	if (equal_ci(keyword, "Function")) return parse_function(parser);
	if (equal_ci(keyword, "LeftTitleButton")) return parse_title_button(parser, false);
	if (equal_ci(keyword, "RightTitleButton")) return parse_title_button(parser, true);
	if (equal_ci(keyword, "NoTitle")) {
		skip_newlines(parser);
		if (parser->token.type == TOK_LBRACE) {
			return parse_window_list(parser, &parser->config->no_title_windows);
		}
		parser->config->no_title = true;
		return true;
	}
	if (equal_ci(keyword, "MakeTitle")) {
		return parse_window_list(parser, &parser->config->make_title_windows);
	}
	if (equal_ci(keyword, "AutoRaise")) {
		skip_newlines(parser);
		if (parser->token.type == TOK_LBRACE)
			return parse_window_list(parser, &parser->config->auto_raise_windows);
		parser->config->auto_raise = true;
		return true;
	}
	if (equal_ci(keyword, "StartIconified"))
		return parse_window_list(parser, &parser->config->start_iconified_windows);
	static const char *const compatible_blocks[] = {
		"AutoRaise", "Cursors", "DontIconifyByUnmapping", "DontSqueezeTitle",
		"IconifyByUnmapping", "IconManagerDontShow", "IconManagerShow",
		"IconManagers", "Icons", "NoHighlight", "NoStackMode",
		"NoTitleHighlight", "Pixmaps", "SaveColor", "SqueezeTitle",
		"WarpCursor", "WindowRing",
	};
	for (size_t i = 0; i < sizeof(compatible_blocks) / sizeof(compatible_blocks[0]); ++i) {
		if (equal_ci(keyword, compatible_blocks[i])) {
			++parser->config->warning_count;
			skip_newlines(parser);
			if (parser->token.type == TOK_LBRACE) return skip_balanced_block(parser);
			return true;
		}
	}

	if ((keyword_type == TOK_STRING || strncasecmp(keyword, "Button", 6) == 0) &&
		parser->token.type == TOK_EQUALS) {
		if (keyword_type == TOK_STRING) return parse_binding(parser, keyword, false, 0);
		char *end = NULL;
		unsigned long button = strtoul(keyword + 6, &end, 10);
		if (*end != '\0' || button == 0 || button > 32) return fail(parser, "invalid button '%s'", keyword);
		return parse_binding(parser, keyword, true, (unsigned)button);
	}

	for (size_t i = 0; i < sizeof(bool_options) / sizeof(bool_options[0]); ++i) {
		if (equal_ci(keyword, bool_options[i].name)) {
			bool *slot = (bool *)((char *)parser->config + bool_options[i].offset);
			*slot = bool_options[i].value;
			return true;
		}
	}
	for (size_t i = 0; i < sizeof(int_options) / sizeof(int_options[0]); ++i) {
		if (equal_ci(keyword, int_options[i].name)) {
			bool negative = accept(parser, TOK_MINUS);
			accept(parser, TOK_PLUS);
			if (parser->token.type != TOK_NUMBER) return fail(parser, "expected a number after %s", keyword);
			long value = negative ? -parser->token.number : parser->token.number;
			int *slot = (int *)((char *)parser->config + int_options[i].offset);
			*slot = (int)value;
			next_token(parser);
			return true;
		}
	}
	for (size_t i = 0; i < sizeof(string_options) / sizeof(string_options[0]); ++i) {
		if (equal_ci(keyword, string_options[i].name)) {
			char *slot = (char *)parser->config + string_options[i].offset;
			return take_text(parser, slot, WTWM_NAME_MAX);
		}
	}

	/* X11-only or not-yet-effective statements remain accepted so old files load. */
	++parser->config->warning_count;
	skip_statement(parser);
	return true;
}

void wtwm_config_init(struct wtwm_config *config) {
	memset(config, 0, sizeof(*config));
	config->border_width = 2;
	config->title_button_border_width = 1;
	config->title_padding = 5;
	config->frame_padding = 2;
	config->button_indent = 1;
	config->move_delta = 3;
	config->constrained_move_time = 400;
	config->menu_border_width = 2;
	config->case_sensitive = true;
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
	free(config->bindings);
	free(config->menus);
	free(config->functions);
	free(config->title_buttons);
	finish_string_list(&config->no_title_windows);
	finish_string_list(&config->make_title_windows);
	finish_string_list(&config->auto_raise_windows);
	finish_string_list(&config->start_iconified_windows);
	memset(config, 0, sizeof(*config));
}

bool wtwm_config_parse(struct wtwm_config *config, const char *source_name,
	const char *text, char *error, size_t error_size) {
	if (error != NULL && error_size > 0) error[0] = '\0';
	struct parser parser = {
		.config = config,
		.source_name = source_name ? source_name : "<config>",
		.input = text,
		.line = 1,
		.error = error,
		.error_size = error_size,
	};
	next_token(&parser);
	while (parser.token.type != TOK_EOF) {
		skip_newlines(&parser);
		if (parser.token.type == TOK_EOF) break;
		if (!parse_statement(&parser)) return false;
	}
	return true;
}

bool wtwm_config_load(struct wtwm_config *config, const char *path,
	char *error, size_t error_size) {
	char selected[4096];
	if (path != NULL) {
		copy_text(selected, sizeof(selected), path);
	} else {
		const char *home = getenv("HOME");
		FILE *probe = NULL;
		if (home != NULL) {
			snprintf(selected, sizeof(selected), "%s/.twmrc.0", home);
			probe = fopen(selected, "rb");
			if (probe != NULL) fclose(probe);
			else {
				snprintf(selected, sizeof(selected), "%s/.twmrc", home);
				probe = fopen(selected, "rb");
				if (probe != NULL) fclose(probe);
			}
		}
		if (probe == NULL) copy_text(selected, sizeof(selected), WTWM_SYSTEM_CONFIG);
	}
	FILE *file = fopen(selected, "rb");
	if (file == NULL) {
		if (path == NULL && errno == ENOENT) return true;
		if (error && error_size) snprintf(error, error_size, "%s: %s", selected, strerror(errno));
		return false;
	}
	if (fseek(file, 0, SEEK_END) != 0) {
		fclose(file);
		return false;
	}
	long length = ftell(file);
	if (length < 0 || fseek(file, 0, SEEK_SET) != 0) {
		fclose(file);
		return false;
	}
	char *text = malloc((size_t)length + 1);
	if (text == NULL) {
		fclose(file);
		return false;
	}
	size_t read_count = fread(text, 1, (size_t)length, file);
	text[read_count] = '\0';
	fclose(file);
	bool result = wtwm_config_parse(config, selected, text, error, error_size);
	free(text);
	return result;
}

static const char *action_name(enum wtwm_action_type type) {
	for (size_t i = 0; i < sizeof(actions) / sizeof(actions[0]); ++i) {
		if (actions[i].type == type) return actions[i].name;
	}
	return "unsupported";
}

void wtwm_config_dump(const struct wtwm_config *config, FILE *stream) {
	fprintf(stream, "border-width=%d\n", config->border_width);
	fprintf(stream, "title-padding=%d\n", config->title_padding);
	fprintf(stream, "move-delta=%d\n", config->move_delta);
	fprintf(stream, "title-background=%s\n", config->title_background);
	fprintf(stream, "title-foreground=%s\n", config->title_foreground);
	fprintf(stream, "bindings=%zu\n", config->binding_count);
	for (size_t i = 0; i < config->binding_count; ++i) {
		const struct wtwm_binding *binding = &config->bindings[i];
		if (binding->type == WTWM_BINDING_BUTTON)
			fprintf(stream, "  button=%u", binding->button);
		else
			fprintf(stream, "  key=%s", binding->key);
		fprintf(stream, " mods=0x%x contexts=0x%x action=%s",
			binding->modifiers, binding->contexts, action_name(binding->action.type));
		if (binding->action.argument[0]) fprintf(stream, " %s", binding->action.argument);
		fputc('\n', stream);
	}
	fprintf(stream, "menus=%zu\n", config->menu_count);
	for (size_t i = 0; i < config->menu_count; ++i)
		fprintf(stream, "  %s items=%zu\n", config->menus[i].name, config->menus[i].item_count);
	fprintf(stream, "functions=%zu\n", config->function_count);
	for (size_t i = 0; i < config->function_count; ++i)
		fprintf(stream, "  %s actions=%zu\n", config->functions[i].name, config->functions[i].action_count);
	fprintf(stream, "compatibility-warnings=%zu\n", config->warning_count);
}
