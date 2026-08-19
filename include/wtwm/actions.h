/* SPDX-License-Identifier: MIT */
#ifndef WTWM_ACTIONS_H
#define WTWM_ACTIONS_H

#include <wtwm/config.h>
#include <wtwm/interaction.h>

#include <stdbool.h>

struct wtwm_zoom_state {
	enum wtwm_action_type mode;
	struct wtwm_interaction_box saved;
};

struct wtwm_screen_warp_state {
	int previous;
};

struct wtwm_screen_warp_plan {
	int source;
	int target;
	int x;
	int y;
};

bool wtwm_action_is_zoom(enum wtwm_action_type type);

/* Apply twm's toggle/switch rules to client size plus frame position. */
struct wtwm_interaction_box wtwm_action_zoom(
	enum wtwm_action_type type,
	const struct wtwm_interaction_box *output,
	int decoration_width, int decoration_height,
	const struct wtwm_interaction_box *current,
	struct wtwm_zoom_state *state);

/* Wrap a current list position by one step; -1 means no current item. */
int wtwm_action_cycle_index(int count, int current, bool forward);

/* Resolve ASCII-case-insensitive next/prev/back or strict numeric arguments. */
int wtwm_action_screen_target(const char *argument, int current,
	int previous, int count);

/* Initialize f.warptoscreen history with no previous output. */
void wtwm_action_screen_warp_init(struct wtwm_screen_warp_state *state);

/*
 * Plan one f.warptoscreen operation and update history only on success.
 * Output boxes use half-open bounds and must have positive dimensions.
 */
bool wtwm_action_plan_screen_warp(const char *argument, int current, int count,
	const struct wtwm_interaction_box *outputs, int pointer_x, int pointer_y,
	struct wtwm_screen_warp_state *state,
	struct wtwm_screen_warp_plan *plan);

#endif
