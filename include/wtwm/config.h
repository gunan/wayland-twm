/* SPDX-License-Identifier: MIT */
#ifndef WTWM_CONFIG_H
#define WTWM_CONFIG_H

#include <wtwm/placement.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define WTWM_NAME_MAX 256
#define WTWM_ACTION_MAX 256
#define WTWM_CONFIG_MAX_FILE_BYTES (32u * 1024u * 1024u)

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

enum wtwm_compatibility {
	WTWM_COMPAT_EFFECTIVE,
	WTWM_COMPAT_WAYLAND_TRANSLATED,
	WTWM_COMPAT_PARSED_ONLY,
	WTWM_COMPAT_UNSUPPORTED,
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
	WTWM_ACTION_CIRCLEUP,
	WTWM_ACTION_CIRCLEDOWN,
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
	WTWM_ACTION_WINREFRESH,
	WTWM_ACTION_ZOOM,
	WTWM_ACTION_HORIZOOM,
	WTWM_ACTION_FULLZOOM,
	WTWM_ACTION_LEFTZOOM,
	WTWM_ACTION_RIGHTZOOM,
	WTWM_ACTION_TOPZOOM,
	WTWM_ACTION_BOTTOMZOOM,
	WTWM_ACTION_WARPNEXT,
	WTWM_ACTION_WARPPREV,
	WTWM_ACTION_WARPTO,
	WTWM_ACTION_WARPRING,
	WTWM_ACTION_WARPTOSCREEN,
	WTWM_ACTION_WARPTOICONMGR,
	WTWM_ACTION_DELTASTOP,
	WTWM_ACTION_TITLE,
	WTWM_ACTION_AUTORAISE,
	WTWM_ACTION_ICONMGR_UP,
	WTWM_ACTION_ICONMGR_DOWN,
	WTWM_ACTION_ICONMGR_LEFT,
	WTWM_ACTION_ICONMGR_RIGHT,
	WTWM_ACTION_ICONMGR_FORWARD,
	WTWM_ACTION_ICONMGR_BACKWARD,
	WTWM_ACTION_ICONMGR_NEXT,
	WTWM_ACTION_ICONMGR_PREVIOUS,
	WTWM_ACTION_ICONMGR_SHOW,
	WTWM_ACTION_ICONMGR_HIDE,
	WTWM_ACTION_ICONMGR_SORT,
	WTWM_ACTION_IDENTIFY,
	WTWM_ACTION_VERSION,
	WTWM_ACTION_PRIORITY,
	WTWM_ACTION_STARTWM,
	WTWM_ACTION_SAVEYOURSELF,
	WTWM_ACTION_CUT,
	WTWM_ACTION_CUTFILE,
	WTWM_ACTION_FILE,
	WTWM_ACTION_COLORMAP,
	WTWM_ACTION_UNSUPPORTED,
};

struct wtwm_action {
	enum wtwm_action_type type;
	enum wtwm_compatibility compatibility;
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

struct wtwm_window_list {
	char directive[WTWM_NAME_MAX];
	bool bare;
	struct wtwm_string_list names;
};

struct wtwm_window_value {
	char name[WTWM_NAME_MAX];
	char value[WTWM_NAME_MAX];
};

enum wtwm_color_mode {
	WTWM_COLOR_MODE_COLOR,
	WTWM_COLOR_MODE_GRAYSCALE,
	WTWM_COLOR_MODE_MONOCHROME,
};

struct wtwm_color_setting {
	char name[WTWM_NAME_MAX];
	char value[WTWM_NAME_MAX];
	enum wtwm_color_mode mode;
	struct wtwm_window_value *overrides;
	size_t override_count;
};

struct wtwm_cursor {
	char role[WTWM_NAME_MAX];
	char source[WTWM_NAME_MAX];
	char mask[WTWM_NAME_MAX];
};

struct wtwm_pixmap {
	char name[WTWM_NAME_MAX];
	char value[WTWM_NAME_MAX];
};

struct wtwm_icon_region {
	char geometry[WTWM_NAME_MAX];
	char vertical_gravity[WTWM_NAME_MAX];
	char horizontal_gravity[WTWM_NAME_MAX];
	int grid_width;
	int grid_height;
};

struct wtwm_icon_manager {
	char window_name[WTWM_NAME_MAX];
	char icon_name[WTWM_NAME_MAX];
	char geometry[WTWM_NAME_MAX];
	int columns;
};

struct wtwm_icon_mapping {
	char window_name[WTWM_NAME_MAX];
	char bitmap[WTWM_NAME_MAX];
};

struct wtwm_squeeze_entry {
	char window_name[WTWM_NAME_MAX];
	char justification[WTWM_NAME_MAX];
	int numerator;
	int denominator;
};

enum wtwm_squeeze_justification {
	WTWM_SQUEEZE_LEFT,
	WTWM_SQUEEZE_CENTER,
	WTWM_SQUEEZE_RIGHT,
};

struct wtwm_squeeze_rule {
	enum wtwm_squeeze_justification justification;
	int numerator;
	int denominator;
};

struct wtwm_directive {
	char name[WTWM_NAME_MAX];
	enum wtwm_compatibility compatibility;
	size_t line;
	size_t ordinal;
	char *source;
	char *value;
};

struct wtwm_client_identity {
	const char *name;
	const char *resource_name;
	const char *resource_class;
	const char *title;
	const char *app_id;
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
	int icon_border_width;
	int priority;
	int xor_value;
	int zoom_count;
	int icon_manager_columns;
	bool zoom;
	bool no_title;
	bool auto_raise; /* retained for compositor ABI; reference AutoRaise is a list */
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
	bool case_sensitive; /* icon-manager sorting only, as in reference twm */
	bool show_icon_manager;
	bool force_icons;
	bool no_icon_managers;
	bool interpolate_menu_colors;
	bool no_grab_server;
	bool no_backing_store;
	bool no_save_unders;
	bool restart_previous_state;
	bool no_raise_on_warp;
	bool warp_unmapped;
	bool sort_icon_manager;
	bool no_defaults;
	bool squeeze_title;
	char title_font[WTWM_NAME_MAX];
	char menu_font[WTWM_NAME_MAX];
	char resize_font[WTWM_NAME_MAX];
	char icon_font[WTWM_NAME_MAX];
	char icon_manager_font[WTWM_NAME_MAX];
	char icon_directory[WTWM_NAME_MAX];
	char unknown_icon[WTWM_NAME_MAX];
	char max_window_size[WTWM_NAME_MAX];
	char use_p_position[WTWM_NAME_MAX];
	int max_window_width;
	int max_window_height;
	bool max_window_size_set;
	enum wtwm_use_p_position use_p_position_mode;
	char icon_manager_geometry[WTWM_NAME_MAX];
	char border_color[WTWM_NAME_MAX];
	char border_tile_background[WTWM_NAME_MAX];
	char border_tile_foreground[WTWM_NAME_MAX];
	char title_background[WTWM_NAME_MAX];
	char title_foreground[WTWM_NAME_MAX];
	char icon_background[WTWM_NAME_MAX];
	char icon_foreground[WTWM_NAME_MAX];
	char icon_border_color[WTWM_NAME_MAX];
	char icon_manager_background[WTWM_NAME_MAX];
	char icon_manager_foreground[WTWM_NAME_MAX];
	char icon_manager_highlight[WTWM_NAME_MAX];
	char default_background[WTWM_NAME_MAX];
	char default_foreground[WTWM_NAME_MAX];
	char menu_background[WTWM_NAME_MAX];
	char menu_foreground[WTWM_NAME_MAX];
	char menu_border_color[WTWM_NAME_MAX];
	char menu_shadow_color[WTWM_NAME_MAX];
	char menu_title_background[WTWM_NAME_MAX];
	char menu_title_foreground[WTWM_NAME_MAX];
	char pointer_background[WTWM_NAME_MAX];
	char pointer_foreground[WTWM_NAME_MAX];
	struct wtwm_action default_function;
	struct wtwm_action window_function;
	struct wtwm_binding *bindings;
	size_t binding_count;
	struct wtwm_menu *menus;
	size_t menu_count;
	struct wtwm_function *functions;
	size_t function_count;
	struct wtwm_title_button *title_buttons;
	size_t title_button_count;
	struct wtwm_window_list *window_lists;
	size_t window_list_count;
	struct wtwm_color_setting *colors;
	size_t color_count;
	struct wtwm_cursor *cursors;
	size_t cursor_count;
	struct wtwm_pixmap *pixmaps;
	size_t pixmap_count;
	struct wtwm_icon_region *icon_regions;
	size_t icon_region_count;
	struct wtwm_icon_manager *icon_managers;
	size_t icon_manager_count;
	struct wtwm_icon_mapping *icons;
	size_t icon_count;
	struct wtwm_squeeze_entry *squeeze_entries;
	size_t squeeze_entry_count;
	struct wtwm_string_list saved_colors;
	struct wtwm_directive *directives;
	size_t directive_count;
	char *source_text;
	/* Frequently consumed lists are also exposed directly. */
	struct wtwm_string_list no_title_windows;
	struct wtwm_string_list make_title_windows;
	struct wtwm_string_list auto_raise_windows;
	struct wtwm_string_list start_iconified_windows;
	size_t warning_count;
	size_t projection_truncation_count;
};

void wtwm_config_init(struct wtwm_config *config);
void wtwm_config_finish(struct wtwm_config *config);

/* Parse/load transactionally: on failure config is left usable and unchanged. */
bool wtwm_config_parse(struct wtwm_config *config, const char *source_name,
	const char *text, char *error, size_t error_size);
bool wtwm_config_load(struct wtwm_config *config, const char *path,
	char *error, size_t error_size);
bool wtwm_config_load_for_screen(struct wtwm_config *config, const char *path,
	unsigned screen, char *error, size_t error_size);

/* Reference lists match exact case-sensitive X11 name, res_name, then res_class. */
bool wtwm_config_match_x11(const struct wtwm_string_list *list,
	const char *name, const char *resource_name, const char *resource_class);
/* Native translation uses title first and app_id second, with the same rules. */
bool wtwm_config_match_native(const struct wtwm_string_list *list,
	const char *title, const char *app_id);
bool wtwm_config_match_client(const struct wtwm_string_list *list,
	const struct wtwm_client_identity *identity);
/* Match a generic optional window-list directive, including its bare form. */
bool wtwm_config_window_list_matches(const struct wtwm_config *config,
	const char *directive, const struct wtwm_client_identity *identity);
/* Resolve DontSqueezeTitle, per-window SqueezeTitle, then the bare default. */
bool wtwm_config_squeeze_rule(const struct wtwm_config *config,
	const struct wtwm_client_identity *identity, struct wtwm_squeeze_rule *rule);
/* Resolve the active display-mode color, including twm's window overrides. */
const char *wtwm_config_color_value(const struct wtwm_config *config,
	const char *name, enum wtwm_color_mode mode,
	const struct wtwm_client_identity *identity);
/* Named-key/f.warpto selectors are case-sensitive prefixes, not globs. */
bool wtwm_config_prefix_x11(const char *selector, const char *name,
	const char *resource_name, const char *resource_class);
bool wtwm_config_prefix_native(const char *selector, const char *title,
	const char *app_id);

/* Emit a stable, human-readable representation used by wtwm-config and tests. */
void wtwm_config_dump(const struct wtwm_config *config, FILE *stream);

#endif
