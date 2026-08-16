/* SPDX-License-Identifier: MIT */
#include <wtwm/interaction.h>

#include <limits.h>
#include <stddef.h>
#include <stdint.h>

static uint64_t absolute_int(int value) {
	return value < 0 ? (uint64_t)(-(int64_t)value) : (uint64_t)value;
}

bool wtwm_interaction_threshold_reached(int move_delta, int dx, int dy) {
	uint64_t threshold = move_delta > 0 ? (uint64_t)move_delta : 0;
	return absolute_int(dx) >= threshold || absolute_int(dy) >= threshold;
}

bool wtwm_constrained_move_entry(int configured_ms, uint32_t elapsed_ms) {
	return configured_ms != 0 && elapsed_ms < (uint32_t)configured_ms;
}

enum wtwm_constrained_axis wtwm_constrained_move_axis(int outer_width,
		int outer_height, int pointer_x, int pointer_y) {
	if (outer_width < 0) outer_width = 0;
	if (outer_height < 0) outer_height = 0;
	int width_third = outer_width / 3;
	int height_third = outer_height / 3;
	enum wtwm_constrained_axis axis = WTWM_AXIS_NONE;
	if (pointer_x < width_third || pointer_x > 2 * width_third)
		axis = WTWM_AXIS_HORIZONTAL;
	/* This is a separate if in twm, so vertical wins simultaneous exits. */
	if (pointer_y < height_third || pointer_y > 2 * height_third)
		axis = WTWM_AXIS_VERTICAL;
	return axis;
}

void wtwm_clamp_move(int screen_width, int screen_height, int outer_width,
		int outer_height, bool force, int *x, int *y) {
	if (force || x == NULL || y == NULL) return;
	int64_t right = (int64_t)*x + outer_width;
	int64_t bottom = (int64_t)*y + outer_height;
	if (*x < 0) *x = 0;
	if (right > screen_width) *x = screen_width - outer_width;
	if (*y < 0) *y = 0;
	if (bottom > screen_height) *y = screen_height - outer_height;
}

uint32_t wtwm_auto_relative_resize_edges(int width, int height,
		int title_height, int pointer_x, int pointer_y, bool from_titlebar) {
	if (from_titlebar) return WTWM_RESIZE_EDGE_NONE;
	int horizontal = pointer_x / (width < 3 ? 1 : width / 3);
	int vertical = (pointer_y - title_height) /
		(height < 3 ? 1 : height / 3);
	uint32_t edges = WTWM_RESIZE_EDGE_NONE;
	if (horizontal <= 0) edges |= WTWM_RESIZE_EDGE_LEFT;
	else if (horizontal >= 2) edges |= WTWM_RESIZE_EDGE_RIGHT;
	if (vertical <= 0) edges |= WTWM_RESIZE_EDGE_TOP;
	else if (vertical >= 2) edges |= WTWM_RESIZE_EDGE_BOTTOM;
	return edges;
}

void wtwm_anchor_constrained_resize(const struct wtwm_interaction_box *original,
		uint32_t edges, int constrained_width, int constrained_height,
		struct wtwm_interaction_box *result) {
	if (original == NULL || result == NULL) return;
	if (constrained_width < 1) constrained_width = 1;
	if (constrained_height < 1) constrained_height = 1;
	*result = *original;
	result->width = constrained_width;
	result->height = constrained_height;
	if ((edges & WTWM_RESIZE_EDGE_LEFT) != 0)
		result->x = original->x + original->width - constrained_width;
	if ((edges & WTWM_RESIZE_EDGE_TOP) != 0)
		result->y = original->y + original->height - constrained_height;
}

bool wtwm_delta_stop_continues(bool window_moved) {
	return !window_moved;
}

struct wtwm_interaction_render_path wtwm_interaction_render_path(
		enum wtwm_interaction_kind kind, bool opaque_move) {
	if (kind == WTWM_INTERACTION_MOVE && opaque_move) {
		return (struct wtwm_interaction_render_path){
			.preview = WTWM_PREVIEW_WINDOW,
			.commit = WTWM_COMMIT_DURING_MOTION,
		};
	}
	return (struct wtwm_interaction_render_path){
		.preview = WTWM_PREVIEW_OUTLINE,
		.commit = WTWM_COMMIT_ON_RELEASE,
	};
}

struct wtwm_interaction_box wtwm_interaction_window_box(
		struct wtwm_interaction_render_path path,
		enum wtwm_interaction_phase phase,
		const struct wtwm_interaction_box *original,
		const struct wtwm_interaction_box *preview) {
	if (original == NULL)
		return (struct wtwm_interaction_box){0};
	if (phase == WTWM_PHASE_ABORT || preview == NULL) return *original;
	if (phase == WTWM_PHASE_COMMIT || path.commit == WTWM_COMMIT_DURING_MOTION)
		return *preview;
	return *original;
}
