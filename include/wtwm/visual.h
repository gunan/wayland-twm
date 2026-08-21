/* SPDX-License-Identifier: MIT */
#ifndef WTWM_VISUAL_H
#define WTWM_VISUAL_H

#include <stdbool.h>

/* Frozen twm 1.0.13.1 defaults from src/twm.c and src/menus.c. */
#define WTWM_VISUAL_DEFAULT_BORDER_WIDTH 2
#define WTWM_VISUAL_DEFAULT_FRAME_PADDING 2
#define WTWM_VISUAL_DEFAULT_TITLE_PADDING 8
#define WTWM_VISUAL_DEFAULT_BUTTON_INDENT 1
#define WTWM_VISUAL_DEFAULT_TITLE_BUTTON_BORDER_WIDTH 1
#define WTWM_VISUAL_DEFAULT_MENU_BORDER_WIDTH 2
#define WTWM_VISUAL_MENU_SHADOW_OFFSET 5
#define WTWM_VISUAL_MENU_HORIZONTAL_PADDING 10
#define WTWM_VISUAL_MENU_PULL_ALLOWANCE 26

struct wtwm_visual_config {
	int border_width;
	int frame_padding;
	int title_padding;
	int button_indent;
	int title_button_border_width;
	int menu_border_width;
	bool menu_shadows;
};

struct wtwm_visual_box {
	int x;
	int y;
	int width;
	int height;
};

enum wtwm_title_justification {
	WTWM_TITLE_JUSTIFY_LEFT,
	WTWM_TITLE_JUSTIFY_CENTER,
	WTWM_TITLE_JUSTIFY_RIGHT,
};

struct wtwm_title_layout {
	struct wtwm_visual_box title;
	struct wtwm_visual_box text;
	struct wtwm_visual_box focus_highlight;
	int text_baseline_y;
	int title_extent;
	int button_width;
	int button_inner_size;
	int button_stride;
	int button_border_width;
	int button_y;
	int left_button_x;
	int right_button_x;
	int squeezed_title_width;
	unsigned int left_button_count;
	unsigned int right_button_count;
	bool button_geometry_valid;
	bool focus_highlight_visible;
};

struct wtwm_menu_layout {
	/* All boxes are relative to the menu window's outer-border origin. */
	struct wtwm_visual_box content;
	struct wtwm_visual_box outer;
	struct wtwm_visual_box shadow;
	struct wtwm_visual_box visible_bounds;
	int row_height;
	int text_x;
	int text_baseline_offset;
	int border_width;
	unsigned int row_count;
	bool shadow_visible;
};

struct wtwm_visual_config wtwm_visual_config_defaults(void);

/*
 * Reproduce InitTitlebarButtons, ComputeCommonTitleOffsets, and
 * ComputeWindowTitleOffsets. Invalid negative dimensions are normalized to a
 * safe portable value; button_geometry_valid reports configurations that twm
 * would pass to XCreateWindow with a non-positive button interior.
 */
void wtwm_title_layout_compute(const struct wtwm_visual_config *config,
	int title_width, int font_height, int font_ascent, int text_width,
	unsigned int left_button_count, unsigned int right_button_count,
	bool has_focus_highlight, struct wtwm_title_layout *layout);

/* Return a title button's full border-inclusive hit box. */
bool wtwm_title_button_box(const struct wtwm_title_layout *layout,
	bool right_side, unsigned int index, struct wtwm_visual_box *box);

/* Return twm's title-window x coordinate, including its negative border. */
int wtwm_title_squeeze_x(int frame_width, int title_width, int frame_border,
	enum wtwm_title_justification justification, int numerator,
	int denominator);

/*
 * Reproduce MakeMenu's dimensions. max_text_width is the largest measured
 * entry width and has_pull_entry corresponds to MenuRoot.pull.
 */
void wtwm_menu_layout_compute(const struct wtwm_visual_config *config,
	int font_height, int font_ascent, int max_text_width,
	unsigned int row_count, bool has_pull_entry,
	struct wtwm_menu_layout *layout);

bool wtwm_menu_row_box(const struct wtwm_menu_layout *layout,
	unsigned int index, struct wtwm_visual_box *box);

/* Return the baseline origin for a normal or centered F_TITLE menu entry. */
bool wtwm_menu_text_origin(const struct wtwm_menu_layout *layout,
	unsigned int index, int text_width, bool title_entry, int *x, int *y);

/*
 * Convert twm's menu invocation anchor to the menu's outer-border origin.
 * Root menus center their content width and first row on the pointer;
 * pull-right callers already supply the submenu origin.
 */
bool wtwm_menu_popup_origin(const struct wtwm_menu_layout *layout,
	bool submenu, int anchor_x, int anchor_y, int *x, int *y);

/*
 * Project logical compatibility pixels onto a fractional-scale output.  Scale
 * is expressed in Wayland's conventional 120ths; zero selects canonical 1x.
 * Boxes are projected by their edges so adjacent logical boxes stay adjacent.
 */
int wtwm_visual_scale_edge(int logical, unsigned int scale_120);
struct wtwm_visual_box wtwm_visual_scale_box(struct wtwm_visual_box logical,
	unsigned int scale_120);

#endif
