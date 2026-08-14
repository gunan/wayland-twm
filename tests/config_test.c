/* SPDX-License-Identifier: MIT */
#include "wtwm/config.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void parse_defaults(void) {
	static const char source[] =
		"# representative system.twmrc\n"
		"NoGrabServer\n"
		"DecorateTransients\n"
		"TitleFont \"-adobe-helvetica-bold-r-normal--*-120-*\"\n"
		"MoveDelta 3\n"
		"Color {\n"
		"  BorderColor \"slategrey\"\n"
		"  TitleBackground \"rgb:2/a/9\"\n"
		"  TitleForeground \"gray85\"\n"
		"}\n"
		"Function \"move-or-raise\" { f.move f.deltastop f.raise }\n"
		"Button1 = : root : f.menu \"defops\"\n"
		"Button1 = m : window|icon : f.function \"move-or-raise\"\n"
		"\"F1\" = m|s : all : f.exec \"xterm &\"\n"
		"Menu \"defops\" {\n"
		"  \"Twm\" f.title\n"
		"  \"Move\" f.move\n"
		"  \"Exit\" f.quit\n"
		"}\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "test", source, error, sizeof(error)));
	assert(config.decorate_transients);
	assert(config.move_delta == 3);
	assert(strcmp(config.title_background, "rgb:2/a/9") == 0);
	assert(config.function_count == 1);
	assert(config.functions[0].action_count == 3);
	assert(config.binding_count == 3);
	assert(config.bindings[0].button == 1);
	assert(config.bindings[0].contexts == WTWM_CONTEXT_ROOT);
	assert(config.bindings[1].modifiers == WTWM_MOD_META1);
	assert(config.bindings[1].contexts == (WTWM_CONTEXT_WINDOW | WTWM_CONTEXT_ICON));
	assert(config.bindings[2].modifiers == (WTWM_MOD_META1 | WTWM_MOD_SHIFT));
	assert(config.menu_count == 1);
	assert(config.menus[0].item_count == 3);
	assert(config.warning_count == 1); /* NoGrabServer: accepted X11-only directive. */
	wtwm_config_finish(&config);
}

static void parse_rules_and_title_buttons(void) {
	static const char source[] =
		"NoTitle { \"xclock\" \"xload\" }\n"
		"AutoRaise { \"xterm\" }\n"
		"StartIconified { \"mail\" }\n"
		"LeftTitleButton \"xlogo11\" = f.iconify\n"
		"RightTitleButton \"resize\" = f.resize\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "rules", source, error, sizeof(error)));
	assert(!config.no_title);
	assert(config.no_title_windows.count == 2);
	assert(config.auto_raise_windows.count == 1);
	assert(config.start_iconified_windows.count == 1);
	assert(config.title_button_count == 2);
	assert(!config.title_buttons[0].right_side);
	assert(config.title_buttons[1].right_side);
	wtwm_config_finish(&config);
}

static void rejects_invalid_binding(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(!wtwm_config_parse(&config, "bad", "Button1 = banana : root : f.move\n",
		error, sizeof(error)));
	assert(strstr(error, "unknown modifier") != NULL);
	wtwm_config_finish(&config);
}

static void accepts_legacy_syntax(void) {
	static const char source[] =
		"SqueezeTitle\n{ \"xterm\" center 0 0 }\n"
		"Cursors\n{ Button \"left_ptr\" Frame \"left_ptr\" }\n"
		"\"KP_Add\" = mod5 : all : f.colormap \"next\"\n"
		"Button1 = : m : f.iconify\n"
		"Menu \"hosts\" { \"host\" !\"ssh host &\" }\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "legacy", source, error, sizeof(error)));
	assert(config.binding_count == 2);
	assert(config.bindings[0].modifiers == WTWM_MOD_META5);
	assert(config.bindings[1].contexts == WTWM_CONTEXT_ICONMGR);
	assert(config.menu_count == 1);
	assert(config.menus[0].items[0].action.type == WTWM_ACTION_EXEC);
	assert(strcmp(config.menus[0].items[0].action.argument, "ssh host &") == 0);
	assert(config.warning_count == 2);
	wtwm_config_finish(&config);
}

static void applies_global_and_exception_rules(void) {
	static const char source[] =
		"NoTitle\n"
		"MakeTitle { \"special\" }\n"
		"AutoRaise\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "rules", source, error, sizeof(error)));
	assert(config.no_title);
	assert(config.auto_raise);
	assert(config.make_title_windows.count == 1);
	wtwm_config_finish(&config);
}

int main(void) {
	parse_defaults();
	parse_rules_and_title_buttons();
	rejects_invalid_binding();
	accepts_legacy_syntax();
	applies_global_and_exception_rules();
	puts("config tests passed");
	return 0;
}
