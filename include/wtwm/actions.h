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

/* Resolve next/prev/back/numeric f.warptoscreen arguments. */
int wtwm_action_screen_target(const char *argument, int current,
	int previous, int count);

#endif
