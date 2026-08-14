/* SPDX-License-Identifier: MIT */
#ifndef WTWM_CONFIG_H
#define WTWM_CONFIG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define WTWM_NAME_MAX 256
#define WTWM_ACTION_MAX 256

enum wtwm_context {
	WTWM_CONTEXT_ROOT = 1u << 0,
	WTWM_CONTEXT_WINDOW = 1u << 1,
	WTWM_CONTEXT_TITLE = 1u << 2,
	WTWM_CONTEXT_ICON = 1u << 3,
	WTWM_CONTEXT_FRAME = 1u << 4,
	WTWM_CONTEXT_ICONMGR = 1u << 5,
	WTWM_CONTEXT_ALL = (1u << 6) - 1,
};

enum wtwm_modifier {
	WTWM_MOD_SHIFT = 1u << 0,
	WTWM_MOD_LOCK = 1u << 1,
	WTWM_MOD_CONTROL = 1u << 2,
	WTWM_MOD_META1 = 1u << 3,
	WTWM_MOD_META2 = 1u << 4,
	WTWM_MOD_META3 = 1u << 5,
	WTWM_MOD_META4 = 1u << 6,
	WTWM_MOD_META5 = 1u << 7,
};

enum wtwm_action_type {
	WTWM_ACTION_NOP,
	WTWM_ACTION_BEEP,
	WTWM_ACTION_MOVE,
	WTWM_ACTION_FORCEMOVE,
	WTWM_ACTION_RESIZE,
	WTWM_ACTION_RAISE,
	WTWM_ACTION_LOWER,
	WTWM_ACTION_RAISELOWER,
	WTWM_ACTION_ICONIFY,
	WTWM_ACTION_DEICONIFY,
	WTWM_ACTION_FOCUS,
	WTWM_ACTION_UNFOCUS,
	WTWM_ACTION_DESTROY,
	WTWM_ACTION_DELETE,
	WTWM_ACTION_EXEC,
	WTWM_ACTION_MENU,
	WTWM_ACTION_FUNCTION,
	WTWM_ACTION_QUIT,
	WTWM_ACTION_RESTART,
	WTWM_ACTION_REFRESH,
	WTWM_ACTION_ZOOM,
	WTWM_ACTION_FULLZOOM,
	WTWM_ACTION_LEFTZOOM,
	WTWM_ACTION_RIGHTZOOM,
	WTWM_ACTION_TOPZOOM,
	WTWM_ACTION_BOTTOMZOOM,
	WTWM_ACTION_WARPNEXT,
	WTWM_ACTION_WARPPREV,
	WTWM_ACTION_WARPTO,
	WTWM_ACTION_DELTASTOP,
	WTWM_ACTION_TITLE,
	WTWM_ACTION_UNSUPPORTED,
};

struct wtwm_action {
	enum wtwm_action_type type;
	char name[WTWM_NAME_MAX];
	char argument[WTWM_ACTION_MAX];
};

enum wtwm_binding_type {
	WTWM_BINDING_BUTTON,
	WTWM_BINDING_KEY,
};

struct wtwm_binding {
	enum wtwm_binding_type type;
	unsigned button;
	char key[WTWM_NAME_MAX];
	uint32_t modifiers;
	uint32_t contexts;
	char window_name[WTWM_NAME_MAX];
	struct wtwm_action action;
};

struct wtwm_menu_item {
	char label[WTWM_NAME_MAX];
	char foreground[WTWM_NAME_MAX];
	char background[WTWM_NAME_MAX];
	struct wtwm_action action;
};

struct wtwm_menu {
	char name[WTWM_NAME_MAX];
	char foreground[WTWM_NAME_MAX];
	char background[WTWM_NAME_MAX];
	struct wtwm_menu_item *items;
	size_t item_count;
};

struct wtwm_function {
	char name[WTWM_NAME_MAX];
	struct wtwm_action *actions;
	size_t action_count;
};

struct wtwm_title_button {
	bool right_side;
	char bitmap[WTWM_NAME_MAX];
	struct wtwm_action action;
};

struct wtwm_string_list {
	char **items;
	size_t count;
};

struct wtwm_config {
	/* The defaults deliberately match historic twm, not a modern desktop. */
	int border_width;
	int title_button_border_width;
	int title_padding;
	int frame_padding;
	int button_indent;
	int move_delta;
	int constrained_move_time;
	int menu_border_width;
	bool no_title;
	bool auto_raise;
	bool decorate_transients;
	bool opaque_move;
	bool random_placement;
	bool dont_move_off;
	bool no_raise_on_move;
	bool no_raise_on_resize;
	bool no_raise_on_deiconify;
	bool no_menu_shadows;
	bool no_title_focus;
	bool auto_relative_resize;
	bool client_border_width;
	bool case_sensitive;
	bool show_icon_manager;
	char title_font[WTWM_NAME_MAX];
	char menu_font[WTWM_NAME_MAX];
	char resize_font[WTWM_NAME_MAX];
	char icon_font[WTWM_NAME_MAX];
	char icon_manager_font[WTWM_NAME_MAX];
	char border_color[WTWM_NAME_MAX];
	char title_background[WTWM_NAME_MAX];
	char title_foreground[WTWM_NAME_MAX];
	char menu_background[WTWM_NAME_MAX];
	char menu_foreground[WTWM_NAME_MAX];
	char menu_border_color[WTWM_NAME_MAX];
	char menu_title_background[WTWM_NAME_MAX];
	char menu_title_foreground[WTWM_NAME_MAX];
	struct wtwm_binding *bindings;
	size_t binding_count;
	struct wtwm_menu *menus;
	size_t menu_count;
	struct wtwm_function *functions;
	size_t function_count;
	struct wtwm_title_button *title_buttons;
	size_t title_button_count;
	struct wtwm_string_list no_title_windows;
	struct wtwm_string_list make_title_windows;
	struct wtwm_string_list auto_raise_windows;
	struct wtwm_string_list start_iconified_windows;
	size_t warning_count;
};

void wtwm_config_init(struct wtwm_config *config);
void wtwm_config_finish(struct wtwm_config *config);

/* Parse a named file, or follow twm's ~/.twmrc.0, ~/.twmrc search if path is NULL. */
bool wtwm_config_load(struct wtwm_config *config, const char *path,
	char *error, size_t error_size);
bool wtwm_config_parse(struct wtwm_config *config, const char *source_name,
	const char *text, char *error, size_t error_size);

/* Emit a stable, human-readable representation used by wtwm-config and tests. */
void wtwm_config_dump(const struct wtwm_config *config, FILE *stream);

#endif
