/* SPDX-License-Identifier: MIT */
#ifndef WTWM_PLACEMENT_H
#define WTWM_PLACEMENT_H

#include <stdbool.h>

enum wtwm_use_p_position {
	WTWM_USE_P_POSITION_OFF,
	WTWM_USE_P_POSITION_ON,
	WTWM_USE_P_POSITION_NON_ZERO,
};

enum wtwm_placement_kind {
	WTWM_PLACEMENT_REQUESTED,
	WTWM_PLACEMENT_RANDOM,
	WTWM_PLACEMENT_POINTER,
	WTWM_PLACEMENT_REMAPPED,
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

/* Deterministic Wayland translation for maps that reference twm would prompt. */
void wtwm_pointer_placement(unsigned index, int pointer_x, int pointer_y,
	int *x, int *y);

/* Clamp an outer frame to the selected output/layout area. */
void wtwm_clamp_outer_position(const struct wtwm_placement_area *area,
	int outer_width, int outer_height, int *x, int *y);

const char *wtwm_placement_kind_name(enum wtwm_placement_kind kind);

#endif
