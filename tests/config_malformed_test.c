/* SPDX-License-Identifier: MIT */
#include "wtwm/config.h"

#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

struct malformed_case {
	const char *name;
	const char *text;
	size_t line;
	const char *diagnostic;
};

/* Keep this table focused on token and structural boundaries. */
static const struct malformed_case cases[] = {
	/* Lexer/token boundaries. */
	{"top-level punctuation", "{\n", 1, "expected a directive"},
	{"unterminated quoted menu name", "Menu \"broken", 1, "unterminated quoted string"},
	{"trailing escape in quoted name", "Menu \"broken\\", 1, "unterminated escape in string"},
	{"newline in quote advances line", "Menu \"broken\nname\"", 2, "expected '{'"},

	/* Scalars and flags. */
	{"integer value missing", "BorderWidth\n", 2, "expected a number"},
	{"integer sign without value", "MoveDelta -\n", 1, "expected a number"},
	{"integer token invalid", "TitlePadding many\n", 1, "expected a number"},
	{"string value missing", "TitleFont\n", 2, "expected a quoted string"},

	/* Color and nested compatibility blocks. */
	{"color opening brace missing", "Color\nBorderColor \"red\"\n", 2, "expected '{'"},
	{"color value missing", "Color {\n BorderColor\n}\n", 3, "expected a quoted string"},
	{"color block truncated", "Color {\n BorderColor \"red\"\n", 3, "unterminated color block"},
	{"color window block truncated", "Color {\n BorderColor \"red\" { \"xterm\" \"blue\"\n", 3, "unterminated window color list"},
	{"cursor block truncated", "Cursors {\n Frame \"left_ptr\"\n", 3, "unterminated Cursors block"},

	/* Menus and menu item color tuples. */
	{"menu name missing", "Menu {\n}\n", 1, "expected menu name"},
	{"menu color colon missing", "Menu \"m\" (\"white\" \"black\") { }\n", 1, "expected ':'"},
	{"menu color close missing", "Menu \"m\" (\"white\":\"black\" { }\n", 1, "expected ')'"},
	{"menu opening brace missing", "Menu \"m\"\nBorderWidth 1\n", 2, "expected '{'"},
	{"menu item action missing", "Menu \"m\" {\n \"item\"\n}\n", 3, "expected an f.action"},
	{"menu action argument missing", "Menu \"m\" {\n \"item\" f.exec\n}\n", 3, "expected action string argument"},
	{"menu truncated after allocation", "Menu \"m\" {\n \"item\" f.move\n", 3, "unterminated menu"},

	/* Functions and actions. */
	{"function name missing", "Function {\n}\n", 1, "expected function name"},
	{"function opening brace missing", "Function \"f\"\nf.move\n", 2, "expected '{'"},
	{"function action invalid", "Function \"f\" {\n move\n}\n", 2, "unknown action"},
	{"function action argument missing", "Function \"f\" {\n f.exec\n}\n", 3, "expected action string argument"},
	{"function truncated after allocation", "Function \"f\" {\n f.move\n", 3, "unterminated function"},

	/* Window lists and title buttons. */
	{"window list member invalid", "NoTitle {\n (\n}\n", 2, "expected a window name"},
	{"window list truncated after allocation", "StartIconified {\n \"xterm\"\n", 3, "unterminated StartIconified list"},
	{"title button bitmap missing", "LeftTitleButton = f.move\n", 1, "expected title-button bitmap"},
	{"title button equals missing", "RightTitleButton \"resize\" f.resize\n", 1, "expected '='"},
	{"title button action missing", "RightTitleButton \"resize\" =\n", 2, "expected an f.action"},
	{"title button argument missing", "RightTitleButton \"x\" = f.menu\n", 2, "expected action string argument"},

	/* Key and button binding fields. */
	{"key binding modifier colon missing", "\"F1\" = m", 1, "expected ':'"},
	{"key binding modifier invalid", "\"F1\" = banana : all : f.move\n", 1, "unknown modifier"},
	{"key binding modifier token invalid", "\"F1\" = 1 : all : f.move\n", 1, "invalid modifier"},
	{"key binding context colon missing", "\"F1\" = m : all", 1, "expected ':'"},
	{"key binding context invalid", "\"F1\" = m : desktop : f.move\n", 1, "unknown context"},
	{"key binding context token invalid", "\"F1\" = m : 1 : f.move\n", 1, "invalid context"},
	{"key binding action missing", "\"F1\" = m : all :", 1, "expected an f.action"},
	{"key binding action argument missing", "\"F1\" = m : all : f.exec", 1, "expected action string argument"},
	{"button number zero", "Button0 = : root : f.move\n", 1, "button number must be 1-16"},
	{"button number too large", "Button17 = : root : f.move\n", 1, "button number must be 1-16"},
};

static void rejects_case(const struct malformed_case *test_case) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	bool parsed = wtwm_config_parse(&config, "malformed", test_case->text,
		error, sizeof(error));
	if (parsed || strstr(error, test_case->diagnostic) == NULL) {
		fprintf(stderr, "%s: parsed=%d diagnostic='%s' (wanted '%s')\n",
			test_case->name, parsed, error, test_case->diagnostic);
		assert(!"malformed input did not produce the expected diagnostic");
	}
	char location[64];
	snprintf(location, sizeof(location), "malformed:%zu:", test_case->line);
	if (strstr(error, location) != error) {
		fprintf(stderr, "%s: diagnostic '%s' did not start with '%s'\n",
			test_case->name, error, location);
		assert(!"malformed input diagnostic has the wrong location");
	}
	wtwm_config_finish(&config);
}

int main(void) {
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
		rejects_case(&cases[i]);
	}
	printf("checked %zu malformed and truncated configurations\n",
		sizeof(cases) / sizeof(cases[0]));
	return 0;
}
