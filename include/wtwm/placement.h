/* SPDX-License-Identifier: MIT */
#ifndef WTWM_PLACEMENT_H
#define WTWM_PLACEMENT_H

#include <stdbool.h>
#include <stddef.h>

enum wtwm_use_p_position {
	WTWM_USE_P_POSITION_OFF,
	WTWM_USE_P_POSITION_ON,
	WTWM_USE_P_POSITION_NON_ZERO,
};

enum wtwm_placement_kind {
	WTWM_PLACEMENT_REQUESTED,
	WTWM_PLACEMENT_RANDOM,
	WTWM_PLACEMENT_INTERACTIVE,
	WTWM_PLACEMENT_POINTER,
	WTWM_PLACEMENT_REMAPPED,
};

enum wtwm_placement_button_action {
	WTWM_PLACEMENT_BUTTON_IGNORE,
	WTWM_PLACEMENT_BUTTON_CONFIRM,
	WTWM_PLACEMENT_BUTTON_RESIZE,
	WTWM_PLACEMENT_BUTTON_FILL,
};

struct wtwm_random_placement {
	int next_x;
	int next_y;
};

struct wtwm_placement_area {
	int x;
	int y;
	int width;
	int height;
};

/*
 * Candidate areas are ordered canonically by the caller.  Selection keeps the
 * first candidate on every containment, distance, or intersection tie.
 */
bool wtwm_placement_output_for_point(const struct wtwm_placement_area *areas,
	size_t count, int point_x, int point_y, size_t *selected);
bool wtwm_placement_output_for_outer(const struct wtwm_placement_area *areas,
	size_t count, int outer_x, int outer_y, int outer_width, int outer_height,
	size_t *selected);

bool wtwm_parse_use_p_position(const char *text,
	enum wtwm_use_p_position *mode);

/*
 * Parse the width and height from X geometry syntax.  Position and sign fields
 * are accepted and ignored, matching twm's XParseGeometry use.
 */
bool wtwm_parse_max_window_size(const char *text, int *width, int *height);

/* twm's screen-derived defaults are 32767 minus the screen dimension. */
void wtwm_default_max_window_size(int screen_width, int screen_height,
	int *width, int *height);

void wtwm_clip_initial_size(int max_width, int max_height,
	int *width, int *height);

bool wtwm_placement_asks_user(bool transient, bool us_position,
	bool p_position, enum wtwm_use_p_position use_p_position,
	int requested_x, int requested_y);

void wtwm_random_placement_init(struct wtwm_random_placement *state);
void wtwm_random_placement_seed(struct wtwm_random_placement *state,
	unsigned index);
void wtwm_random_placement_next(struct wtwm_random_placement *state,
	int screen_width, int screen_height, int client_width, int client_height,
	int *x, int *y);

/* Native Wayland translation for maps that reference twm would prompt. */
void wtwm_pointer_placement(unsigned index, int pointer_x, int pointer_y,
	int *x, int *y);

enum wtwm_placement_button_action wtwm_placement_button(unsigned button);

/* The reference prompt treats the pointer as the outer frame's upper-left. */
void wtwm_placement_prompt_position(const struct wtwm_placement_area *area,
	bool dont_move_off, int outer_width, int outer_height,
	int pointer_x, int pointer_y, int *x, int *y);

/* Button3 fills the output from the confirmed origin before size constraints. */
void wtwm_placement_fill_size(const struct wtwm_placement_area *area,
	int x, int y, int horizontal_inset, int vertical_inset,
	int *client_width, int *client_height);

/* Clamp an outer frame to the selected output/layout area. */
void wtwm_clamp_outer_position(const struct wtwm_placement_area *area,
	int outer_width, int outer_height, int *x, int *y);

const char *wtwm_placement_kind_name(enum wtwm_placement_kind kind);

#endif
