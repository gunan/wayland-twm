/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE

#include "wtwm/config.h"

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef WTWM_SOURCE_ROOT
#define WTWM_SOURCE_ROOT ""
#endif

static void parse_lexical_reference_forms(void) {
	static const char source[] =
		"# comment consumes its newline\n"
		"mOvEdElTa 7\n"
		"GREYSCALE { TitleForeground \"line\\n\\t\\101\\x42\\\"\\\\\" }\n"
		"Button1 = Mod 5|Shift : Root : ! \"printf ok\"\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "lexical.twmrc", source, error, sizeof(error)));
	assert(config.move_delta == 7);
	assert(strcmp(config.title_foreground, "line\n\tAB\"\\") == 0);
	assert(config.binding_count == 1);
	assert(config.bindings[0].modifiers == (WTWM_MOD_META5 | WTWM_MOD_SHIFT));
	assert(config.bindings[0].action.type == WTWM_ACTION_EXEC);
	assert(strcmp(config.bindings[0].action.argument, "printf ok") == 0);
	assert(config.directives[0].line == 2);
	wtwm_config_finish(&config);
}

static void rejects_reference_lexical_errors(void) {
	static const struct {
		const char *text;
		const char *message;
		const char *line;
	} cases[] = {
		{"MoveDelta @\n", "invalid character", ":1:"},
		{"UnknownThing\n", "unknown keyword", ":1:"},
		{"TitleFont \"unterminated", "unterminated quoted", ":1:"},
		{"MoveDelta 999999999999999999999999999999\n", "out of range", ":1:"},
		{"BorderWidth -1\n", "expected a number", ":1:"},
		{"# comment without reference newline", "invalid character", ":1:"},
		{"MoveDelta 1\f", "invalid character", ":1:"},
	};
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
		struct wtwm_config config;
		wtwm_config_init(&config);
		char error[512];
		assert(!wtwm_config_parse(&config, "bad.twmrc", cases[i].text,
			error, sizeof(error)));
		assert(strstr(error, cases[i].message) != NULL);
		assert(strstr(error, cases[i].line) != NULL);
		wtwm_config_finish(&config);
	}
}

static void parses_every_construct_family(void) {
	static const char source[] =
		"AutoRelativeResize\nClientBorderWidth\nDecorateTransients\nDontMoveOff\n"
		"ForceIcons\nInterpolateMenuColors\nNoBackingStore\nNoCaseSensitive\n"
		"NoDefaults\nNoGrabServer\nNoIconManagers\nNoMenuShadows\n"
		"NoRaiseOnDeiconify\nNoRaiseOnMove\nNoRaiseOnResize\nNoRaiseOnWarp\n"
		"NoSaveUnders\nNoTitleFocus\nNoVersion\nOpaqueMove\nRandomPlacement\n"
		"RestartPreviousState\nShowIconManager\nSortIconManager\nWarpUnmapped\n"
		"BorderWidth 4\nButtonIndent 2\nConstrainedMoveTime 500\nFramePadding 3\n"
		"IconBorderWidth 1\nMenuBorderWidth 3\nMoveDelta 8\nPriority 4\n"
		"TitleButtonBorderWidth 2\nTitlePadding 6\nXorValue 123\n"
		"IconDirectory \"~/icons\"\nIconFont \"ifont\"\nIconManagerFont \"imfont\"\n"
		"MaxWindowSize \"1000x800\"\nMenuFont \"mfont\"\nResizeFont \"rfont\"\n"
		"TitleFont \"tfont\"\nUnknownIcon \"unknown\"\nUsePPosition \"on\"\n"
		"Color {\n"
		" BorderColor \"red\" { \"XTerm\" \"blue\" }\n"
		" BorderTileBackground \"black\" BorderTileForeground \"white\"\n"
		" DefaultBackground \"black\" DefaultForeground \"white\"\n"
		" IconBackground \"black\" IconBorderColor \"white\" IconForeground \"green\"\n"
		" IconManagerBackground \"black\" IconManagerForeground \"white\"\n"
		" IconManagerHighlight \"yellow\" MenuBackground \"black\"\n"
		" MenuBorderColor \"white\" MenuForeground \"green\" MenuShadowColor \"gray\"\n"
		" MenuTitleBackground \"navy\" MenuTitleForeground \"white\"\n"
		" PointerBackground \"black\" PointerForeground \"white\"\n"
		" TitleBackground \"navy\" { \"xterm\" \"purple\" } TitleForeground \"white\"\n}\n"
		"Monochrome { BorderColor \"white\" }\n"
		"SaveColor { \"cyan\" BorderColor TitleForeground }\n"
		"Cursors { Frame \"cursor\" \"mask\" Title \"left_ptr\" Destroy \"pirate\" }\n"
		"Pixmaps { TitleHighlight \"highlight.xbm\" }\n"
		"IconRegion \"100x100+0+0\" North West 64 48\n"
		"IconManagerGeometry \"200x5+0+0\" 3\n"
		"IconManagers { \"XTerm\" \"term\" \"200x5+0+0\" 2 \"Emacs\" \"300x5\" 1 }\n"
		"Icons { \"xterm\" \"xterm.xbm\" \"xclock\" \"clock.xbm\" }\n"
		"SqueezeTitle { \"xterm\" Center -1 2 \"emacs\" Left +0 0 }\n"
		"DontSqueezeTitle { \"fixed\" }\n"
		"AutoRaise { \"xterm\" }\nDontIconifyByUnmapping { \"xclock\" }\n"
		"IconifyByUnmapping\nIconManagerDontShow\nIconManagerShow { \"emacs\" }\n"
		"MakeTitle { \"special\" }\nNoHighlight\nNoStackMode { \"stacked\" }\n"
		"NoTitle { \"xclock\" }\nNoTitleHighlight\nStartIconified { \"mail\" }\n"
		"WarpCursor\nWindowRing { \"xterm\" }\n"
		"Function \"ops\" { f.move f.deltastop f.raise f.circleup f.circledown f.colormap \"next\" }\n"
		"Function \"ops\" { f.lower }\n"
		"Menu \"main\" (\"white\":\"black\") { \"Title\" f.title \"Run\" ! \"xterm &\" }\n"
		"Menu \"main\" { \"Quit\" f.quit }\n"
		"DefaultFunction f.nop\nWindowFunction f.deiconify\n"
		"LeftTitleButton \"dot\" = f.iconify\nRightTitleButton \"resize\" = f.resize\n"
		"Button1 \"main\"\nButton2 f.resize\n"
		"Button3 = m : window|icon : f.function \"ops\"\n"
		"\"F1\" = control : all|\"xterm\" : f.exec \"xterm &\"\n"
		"Zoom 4\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "families.twmrc", source, error, sizeof(error)));
	assert(config.border_width == 4);
	assert(config.color_count == 22);
	assert(config.colors[0].override_count == 1);
	assert(config.saved_colors.count == 3);
	assert(config.cursor_count == 3);
	assert(config.pixmap_count == 1);
	assert(config.icon_region_count == 1);
	assert(config.icon_manager_count == 2);
	assert(strcmp(config.icon_managers[0].window_name, "Emacs") == 0);
	assert(config.icon_managers[0].icon_name[0] == '\0');
	assert(strcmp(config.icon_managers[0].geometry, "300x5") == 0);
	assert(strcmp(config.icon_managers[1].window_name, "XTerm") == 0);
	assert(strcmp(config.icon_managers[1].icon_name, "term") == 0);
	assert(strcmp(config.icon_managers[1].geometry, "200x5+0+0") == 0);
	assert(config.icon_count == 2);
	assert(config.squeeze_entry_count == 2);
	assert(config.window_list_count == 14);
	assert(config.function_count == 1);
	assert(config.functions[0].action_count == 7);
	assert(config.functions[0].actions[3].type == WTWM_ACTION_CIRCLEUP);
	assert(config.functions[0].actions[4].type == WTWM_ACTION_CIRCLEDOWN);
	assert(config.menu_count == 1);
	assert(config.menus[0].item_count == 3);
	assert(config.title_button_count == 2);
	assert(config.binding_count == 4);
	assert(config.zoom && config.zoom_count == 4);
	assert(config.directive_count > 60);
	assert(config.warning_count > 0);
	bool saw_effective = false, saw_translated = false;
	bool saw_parsed = false, saw_unsupported = false;
	for (size_t i = 0; i < config.directive_count; ++i) {
		switch (config.directives[i].compatibility) {
		case WTWM_COMPAT_EFFECTIVE: saw_effective = true; break;
		case WTWM_COMPAT_WAYLAND_TRANSLATED: saw_translated = true; break;
		case WTWM_COMPAT_PARSED_ONLY: saw_parsed = true; break;
		case WTWM_COMPAT_UNSUPPORTED: saw_unsupported = true; break;
		}
	}
	assert(saw_effective && saw_translated && saw_parsed && saw_unsupported);
	wtwm_config_finish(&config);
}

static void preserves_order_and_replacement_rules(void) {
	static const char source[] =
		"BorderWidth 1\nBorderWidth 9\n"
		"Color { TitleForeground \"red\" TitleForeground \"blue\" }\n"
		"Button1 = : root|window : f.raise\n"
		"Button1 = : root : f.lower\n"
		"\"F1\" = : root : f.raise\n\"f1\" = : root : f.lower\n"
		"Menu \"m\" { \"one\" f.nop }\nMenu \"m\" { \"two\" f.nop }\n"
		"Menu \"M\" { \"upper\" f.nop }\n"
		"Function \"f\" { f.raise }\nFunction \"f\" { f.lower }\n"
		"Function \"F\" { f.nop }\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "order", source, error, sizeof(error)));
	assert(config.border_width == 9);
	assert(strcmp(config.title_foreground, "blue") == 0);
	assert(config.binding_count == 4);
	assert(config.bindings[0].contexts == WTWM_CONTEXT_WINDOW);
	assert(config.bindings[1].contexts == WTWM_CONTEXT_ROOT);
	assert(config.bindings[1].action.type == WTWM_ACTION_LOWER);
	assert(strcmp(config.bindings[2].key, "F1") == 0);
	assert(strcmp(config.bindings[3].key, "f1") == 0);
	assert(config.menu_count == 2 && config.menus[0].item_count == 2);
	assert(strcmp(config.menus[1].name, "M") == 0 && config.menus[1].item_count == 1);
	assert(config.function_count == 2 && config.functions[0].action_count == 2);
	assert(strcmp(config.functions[1].name, "F") == 0 && config.functions[1].action_count == 1);
	assert(config.directives[0].ordinal == 0);
	assert(strcmp(config.directives[0].name, "BorderWidth") == 0);
	assert(strcmp(config.directives[1].name, "BorderWidth") == 0);
	wtwm_config_finish(&config);
}

static void uses_reference_intrinsic_defaults_and_aliases(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	assert(config.title_padding == 8);
	assert(config.move_delta == 1);
	char error[512];
	assert(wtwm_config_parse(&config, "aliases",
		"Button16 = : root : f.nop\n"
		"Cursors { F \"a\" T \"b\" I \"c\" M \"d\" Meta \"e\" Mod \"f\" }\n",
		error, sizeof(error)));
	assert(config.title_padding == 8 && config.move_delta == 1);
	assert(config.binding_count == 1 && config.bindings[0].button == 16);
	assert(config.cursor_count == 6);
	wtwm_config_finish(&config);
}

static void failed_parse_is_atomic_and_leak_safe(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "valid", "BorderWidth 7\nMenu \"ok\" { \"x\" f.nop }\n",
		error, sizeof(error)));
	struct wtwm_menu *menus = config.menus;
	char *source_text = config.source_text;
	for (unsigned i = 0; i < 40; ++i) {
		const char *bad = i % 2 ?
			"Menu \"partial\" { \"x\" f.nop \"truncated\"" :
			"Function \"partial\" { f.move f.exec";
		assert(!wtwm_config_parse(&config, "replacement", bad, error, sizeof(error)));
		assert(strstr(error, "replacement:1:") != NULL);
		assert(config.border_width == 7);
		assert(config.menu_count == 1);
		assert(config.menus == menus);
		assert(config.source_text == source_text);
	}
	for (unsigned i = 0; i < 40; ++i) {
		char source[64];
		snprintf(source, sizeof(source), "BorderWidth %u\n", i + 1);
		assert(wtwm_config_parse(&config, "reload", source, error, sizeof(error)));
		assert(config.border_width == (int)i + 1);
	}
	wtwm_config_finish(&config);
}

static void rejects_malformed_and_truncated_constructs(void) {
	static const char *const malformed[] = {
		"Color { BorderColor \"red\" { \"xterm\" } }\n",
		"Color { MenuBackground \"red\" { \"x\" \"blue\" } }\n",
		"SaveColor { NotAColor }\n",
		"Cursors { Unknown \"left_ptr\" }\n",
		"Cursors { Frame }\n",
		"Pixmaps { TitleHighlight }\n",
		"Pixmaps { Other \"x\" }\n",
		"IconRegion \"10x10\" North West 2\n",
		"IconRegion \"10x10\" Center West 2 2\n",
		"IconManagerGeometry 12\n",
		"IconManagers { \"XTerm\" \"geom\" }\n",
		"Icons { \"XTerm\" }\n",
		"SqueezeTitle { \"XTerm\" North 0 0 }\n",
		"NoTitle { \"XTerm\"\n",
		"AutoRaise\n",
		"LeftTitleButton \"dot\" f.iconify\n",
		"Button1 = banana : root : f.move\n",
		"Button1 = : nowhere : f.move\n",
		"Button1 = : root : f.unknown\n",
		"Menu \"m\" { \"entry\" }\n",
		"Function \"f\" { f.exec }\n",
		"Button0 = : root : f.nop\n",
		"Button17 = : root : f.nop\n",
	};
	for (size_t i = 0; i < sizeof(malformed) / sizeof(malformed[0]); ++i) {
		struct wtwm_config config;
		wtwm_config_init(&config);
		char error[512];
		assert(!wtwm_config_parse(&config, "malformed.twmrc", malformed[i],
			error, sizeof(error)));
		assert(strstr(error, "malformed.twmrc:") != NULL);
		wtwm_config_finish(&config);
	}
}

static void matches_reference_selection_rules(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "match",
		"NoTitle { \"Exact\" \"XTerm\" \"*\" }\n", error, sizeof(error)));
	const struct wtwm_string_list *list = &config.no_title_windows;
	assert(wtwm_config_match_x11(list, "Exact", "other", "Other"));
	assert(wtwm_config_match_x11(list, "other", "x", "XTerm"));
	assert(!wtwm_config_match_x11(list, "exact", "xterm", "anything"));
	assert(!wtwm_config_match_x11(list, "anything", "x", "Class"));
	assert(wtwm_config_match_x11(list, "*", "x", "Class"));
	assert(wtwm_config_match_native(list, "Exact", "org.example.App"));
	assert(wtwm_config_match_native(list, "title", "XTerm"));
	assert(!wtwm_config_match_native(list, "exact", "xterm"));
	assert(wtwm_config_prefix_x11("Term", "Terminal", "other", "Other"));
	assert(wtwm_config_prefix_x11("Xt", "none", "Xterm", "Other"));
	assert(!wtwm_config_prefix_x11("xt", "none", "Xterm", "Other"));
	assert(wtwm_config_prefix_native("org.example", "title", "org.example.App"));
	wtwm_config_finish(&config);
}

static void write_config(const char *path, int width) {
	FILE *file = fopen(path, "wb");
	assert(file != NULL);
	fprintf(file, "BorderWidth %d\n", width);
	assert(fclose(file) == 0);
}

static void join_path(char *path, size_t path_size, const char *directory,
	const char *suffix) {
	size_t directory_length = strlen(directory);
	size_t suffix_length = strlen(suffix);
	assert(directory_length + suffix_length + 1 <= path_size);
	memcpy(path, directory, directory_length);
	memcpy(path + directory_length, suffix, suffix_length + 1);
}

static void loads_reference_search_order(void) {
	const char *temporary_root = getenv("TMPDIR");
	if (temporary_root == NULL || temporary_root[0] == '\0') temporary_root = "/tmp";
	char directory[PATH_MAX];
	snprintf(directory, sizeof(directory), "%s/wtwm-config-test-XXXXXX", temporary_root);
	assert(mkdtemp(directory) != NULL);
	char screen_path[PATH_MAX], general_path[PATH_MAX], system_path[PATH_MAX];
	char explicit_path[PATH_MAX], missing_path[PATH_MAX];
	join_path(screen_path, sizeof(screen_path), directory, "/.twmrc.3");
	join_path(general_path, sizeof(general_path), directory, "/.twmrc");
	join_path(system_path, sizeof(system_path), directory, "/system.twmrc");
	join_path(explicit_path, sizeof(explicit_path), directory, "/explicit.twmrc");
	join_path(missing_path, sizeof(missing_path), directory, "/missing.twmrc");
	write_config(screen_path, 3); write_config(general_path, 4);
	write_config(system_path, 5); write_config(explicit_path, 2);
	const char *old_home_value = getenv("HOME");
	const char *old_system_value = getenv("WTWM_SYSTEM_CONFIG");
	char *old_home = old_home_value ? strdup(old_home_value) : NULL;
	char *old_system = old_system_value ? strdup(old_system_value) : NULL;
	assert(setenv("HOME", directory, 1) == 0);
	assert(setenv("WTWM_SYSTEM_CONFIG", system_path, 1) == 0);
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_load_for_screen(&config, explicit_path, 3, error, sizeof(error)));
	assert(config.border_width == 2);
	FILE *invalid = fopen(explicit_path, "wb");
	assert(invalid != NULL);
	fputs("BorderWidth invalid\n", invalid);
	assert(fclose(invalid) == 0);
	assert(!wtwm_config_load_for_screen(&config, explicit_path, 3, error, sizeof(error)));
	assert(config.border_width == 2);
	assert(wtwm_config_load_for_screen(&config, missing_path, 3, error, sizeof(error)));
	assert(config.border_width == 5);
	assert(wtwm_config_load_for_screen(&config, NULL, 3, error, sizeof(error)));
	assert(config.border_width == 3);
	assert(unlink(screen_path) == 0);
	assert(wtwm_config_load_for_screen(&config, NULL, 3, error, sizeof(error)));
	assert(config.border_width == 4);
	assert(unlink(general_path) == 0);
	assert(wtwm_config_load_for_screen(&config, NULL, 3, error, sizeof(error)));
	assert(config.border_width == 5);
	assert(unlink(system_path) == 0);
	assert(wtwm_config_load_for_screen(&config, NULL, 3, error, sizeof(error)));
	assert(config.binding_count > 0);
	assert(config.menu_count == 1);
	assert(config.move_delta == 3);
	assert(strcmp(config.menus[0].name, "defops") == 0);
	wtwm_config_finish(&config);
	if (old_home) { assert(setenv("HOME", old_home, 1) == 0); free(old_home); }
	else assert(unsetenv("HOME") == 0);
	if (old_system) { assert(setenv("WTWM_SYSTEM_CONFIG", old_system, 1) == 0); free(old_system); }
	else assert(unsetenv("WTWM_SYSTEM_CONFIG") == 0);
	assert(unlink(explicit_path) == 0);
	assert(rmdir(directory) == 0);
}

static void preserves_long_source_without_silent_lexical_truncation(void) {
	size_t length = 2048;
	char *value = malloc(length + 1);
	char *source = malloc(length + 32);
	assert(value != NULL && source != NULL);
	memset(value, 'x', length);
	value[length] = '\0';
	snprintf(source, length + 32, "TitleFont \"%s\"\n", value);
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "long", source, error, sizeof(error)));
	assert(config.directive_count == 1);
	assert(strlen(config.directives[0].value) == length);
	assert(strstr(config.source_text, value) != NULL);
	assert(config.projection_truncation_count == 1);
	wtwm_config_finish(&config);
	free(source);
	free(value);
}

static void dumps_comprehensive_ordered_model(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "dump",
		"BorderWidth 8\nNoGrabServer\nTitleFont \"font\"\n",
		error, sizeof(error)));
	FILE *file = tmpfile();
	assert(file != NULL);
	wtwm_config_dump(&config, file);
	assert(fflush(file) == 0);
	assert(fseek(file, 0, SEEK_SET) == 0);
	char dump[16384];
	size_t count = fread(dump, 1, sizeof(dump) - 1, file);
	dump[count] = '\0';
	assert(strstr(dump, "border-width=8") != NULL);
	assert(strstr(dump, "button-indent=1") != NULL);
	assert(strstr(dump, "frame-padding=2") != NULL);
	assert(strstr(dump, "move-delta=1") != NULL);
	assert(strstr(dump, "no-defaults=0") != NULL);
	assert(strstr(dump, "no-grab-server=1") != NULL);
	assert(strstr(dump, "no-icon-managers=0") != NULL);
	assert(strstr(dump, "title-button-border-width=1") != NULL);
	assert(strstr(dump, "title-focus=1") != NULL);
	assert(strstr(dump, "title-padding=8") != NULL);
	assert(strstr(dump, "title_font=\"font\"") != NULL);
	assert(strstr(dump, "0 name=BorderWidth") != NULL);
	assert(strstr(dump, "1 name=NoGrabServer") != NULL);
	assert(strstr(dump, "compatibility=unsupported") != NULL);
	assert(strstr(dump, "compatibility=wayland-translated") != NULL);
	assert(fclose(file) == 0);
	wtwm_config_finish(&config);
}

static void parses_frozen_upstream_examples(void) {
	static const char *const paths[] = {
		"reference/upstream/twm-1.0.13.1/sample-twmrc/jim.twmrc",
		"reference/upstream/twm-1.0.13.1/sample-twmrc/keith.twmrc",
		"reference/upstream/twm-1.0.13.1/sample-twmrc/lemke.twmrc",
		"reference/upstream/twm-1.0.13.1/defaults/system.twmrc",
	};
	const char *source_root = getenv("WTWM_SOURCE_ROOT");
	if (source_root == NULL || source_root[0] == '\0') source_root = getenv("MESON_SOURCE_ROOT");
	if (source_root == NULL || source_root[0] == '\0') source_root = WTWM_SOURCE_ROOT;
	for (size_t i = 0; i < sizeof(paths) / sizeof(paths[0]); ++i) {
		char rooted[PATH_MAX], from_build[PATH_MAX];
		const char *path = paths[i];
		if (source_root[0] != '\0') {
			snprintf(rooted, sizeof(rooted), "%s/%s", source_root, paths[i]);
			path = rooted;
		}
		if (source_root[0] == '\0' && access(path, R_OK) != 0) {
			snprintf(from_build, sizeof(from_build), "../%s", paths[i]);
			path = from_build;
		}
		assert(access(path, R_OK) == 0);
		struct wtwm_config config;
		wtwm_config_init(&config);
		char error[512];
		assert(wtwm_config_load(&config, path, error, sizeof(error)));
		assert(config.directive_count > 0);
		wtwm_config_finish(&config);
	}
}

/*
 * Keep the stable M0 audit case names executable while the broader M2 cases
 * above provide the complete grammar coverage.
 */
static void parse_defaults(void) {
	static const char source[] =
		"NoGrabServer\nDecorateTransients\nTitleFont \"fixed\"\nMoveDelta 3\n"
		"Color { BorderColor \"slategrey\" TitleBackground \"navy\" }\n"
		"Function \"move-or-raise\" { f.move f.deltastop f.raise }\n"
		"Button1 = : root : f.menu \"defops\"\n"
		"Menu \"defops\" { \"Twm\" f.title \"Move\" f.move \"Exit\" f.quit }\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "defaults", source, error, sizeof(error)));
	assert(config.decorate_transients && config.move_delta == 3);
	assert(config.function_count == 1 && config.functions[0].action_count == 3);
	assert(config.menu_count == 1 && config.menus[0].item_count == 3);
	assert(config.warning_count == 3);
	wtwm_config_finish(&config);
}

static void parses_placement_options(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(config.use_p_position_mode == WTWM_USE_P_POSITION_OFF);
	assert(!config.max_window_size_set);
	assert(wtwm_config_parse(&config, "placement",
		"UsePPosition \"non-zero\"\nMaxWindowSize \"=800x600+1-2\"\n",
		error, sizeof(error)));
	assert(config.use_p_position_mode == WTWM_USE_P_POSITION_NON_ZERO);
	assert(config.max_window_size_set);
	assert(config.max_window_width == 800 && config.max_window_height == 600);
	assert(strcmp(config.use_p_position, "non-zero") == 0);

	assert(wtwm_config_parse(&config, "invalid-ppos",
		"UsePPosition \"sometimes\"\n", error, sizeof(error)));
	assert(config.use_p_position_mode == WTWM_USE_P_POSITION_OFF);
	assert(config.warning_count == 1);

	assert(!wtwm_config_parse(&config, "bad-maximum",
		"MaxWindowSize \"800x0\"\n", error, sizeof(error)));
	assert(strstr(error, "bad-maximum:1:") != NULL);
	/* Invalid replacement is atomic. */
	assert(config.use_p_position_mode == WTWM_USE_P_POSITION_OFF);
	assert(config.warning_count == 1);
	wtwm_config_finish(&config);
}

static void parse_rules_and_title_buttons(void) {
	static const char source[] =
		"NoTitle { \"xclock\" \"xload\" }\nAutoRaise { \"xterm\" }\n"
		"StartIconified { \"mail\" }\n"
		"LeftTitleButton \"xlogo11\" = f.iconify\n"
		"RightTitleButton \"resize\" = f.resize\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "rules", source, error, sizeof(error)));
	assert(config.no_title_windows.count == 2);
	assert(config.auto_raise_windows.count == 1);
	assert(config.start_iconified_windows.count == 1);
	assert(config.title_button_count == 2);
	wtwm_config_finish(&config);
}

static void rejects_invalid_binding(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(!wtwm_config_parse(&config, "bad",
		"Button1 = banana : root : f.move\n", error, sizeof(error)));
	assert(strstr(error, "unknown modifier") != NULL);
	wtwm_config_finish(&config);
}

static void accepts_legacy_syntax(void) {
	static const char source[] =
		"SqueezeTitle { \"xterm\" Center 0 0 }\n"
		"Cursors { Button \"left_ptr\" Frame \"left_ptr\" }\n"
		"\"KP_Add\" = mod5 : all : f.colormap \"next\"\n"
		"Button1 = : m : f.iconify\n"
		"Menu \"hosts\" { \"host\" ! \"ssh host &\" }\n";
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "legacy", source, error, sizeof(error)));
	assert(config.binding_count == 2 && config.squeeze_entry_count == 1);
	assert(config.menus[0].items[0].action.type == WTWM_ACTION_EXEC);
	assert(config.warning_count == 3);
	wtwm_config_finish(&config);
}

static void applies_global_and_exception_rules(void) {
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[512];
	assert(wtwm_config_parse(&config, "rules",
		"NoTitle\nMakeTitle { \"special\" }\nAutoRaise { \"raised\" }\n",
		error, sizeof(error)));
	assert(config.no_title);
	assert(config.make_title_windows.count == 1);
	assert(config.auto_raise_windows.count == 1);
	wtwm_config_finish(&config);
}

int main(void) {
	parse_lexical_reference_forms();
	rejects_reference_lexical_errors();
	parses_every_construct_family();
	preserves_order_and_replacement_rules();
	uses_reference_intrinsic_defaults_and_aliases();
	failed_parse_is_atomic_and_leak_safe();
	rejects_malformed_and_truncated_constructs();
	matches_reference_selection_rules();
	loads_reference_search_order();
	preserves_long_source_without_silent_lexical_truncation();
	dumps_comprehensive_ordered_model();
	parses_frozen_upstream_examples();
	parse_defaults();
	parses_placement_options();
	parse_rules_and_title_buttons();
	rejects_invalid_binding();
	accepts_legacy_syntax();
	applies_global_and_exception_rules();
	puts("config tests passed");
	return 0;
}
