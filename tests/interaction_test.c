/* SPDX-License-Identifier: MIT */
#include <wtwm/interaction.h>

#include <assert.h>
#include <limits.h>

static void threshold_cases(void) {
	assert(!wtwm_interaction_threshold_reached(3, 2, -2));
	assert(wtwm_interaction_threshold_reached(3, 3, 0));
	assert(wtwm_interaction_threshold_reached(0, 0, 0));
	assert(wtwm_interaction_threshold_reached(3, INT_MIN, 0));
}

static void constrained_cases(void) {
	assert(!wtwm_constrained_move_entry(0, 0));
	assert(wtwm_constrained_move_entry(400, 399));
	assert(!wtwm_constrained_move_entry(400, 400));
	/* twm casts a nonzero signed setting to X Time's unsigned domain. */
	assert(wtwm_constrained_move_entry(-1, 400));
	assert(wtwm_constrained_move_axis(90, 90, 45, 45) == WTWM_AXIS_NONE);
	assert(wtwm_constrained_move_axis(90, 90, 61, 45) ==
		WTWM_AXIS_HORIZONTAL);
	assert(wtwm_constrained_move_axis(90, 90, 61, 61) == WTWM_AXIS_VERTICAL);
}

static void bounds_and_function_cases(void) {
	int x = -7, y = -9;
	wtwm_clamp_move(640, 480, 100, 80, false, &x, &y);
	assert(x == 0 && y == 0);
	x = 600; y = 450;
	wtwm_clamp_move(640, 480, 100, 80, false, &x, &y);
	assert(x == 540 && y == 400);
	x = -5; y = -5;
	wtwm_clamp_move(640, 480, 700, 500, false, &x, &y);
	assert(x == -60 && y == -20);
	x = -7; y = 450;
	wtwm_clamp_move(640, 480, 100, 80, true, &x, &y);
	assert(x == -7 && y == 450);
	assert(wtwm_delta_stop_continues(false));
	assert(!wtwm_delta_stop_continues(true));
}

static void resize_origin_cases(void) {
	assert(wtwm_auto_relative_resize_edges(90, 90, 18, 10, 25, false) ==
		(WTWM_RESIZE_EDGE_LEFT | WTWM_RESIZE_EDGE_TOP));
	assert(wtwm_auto_relative_resize_edges(90, 90, 18, 75, 90, false) ==
		(WTWM_RESIZE_EDGE_RIGHT | WTWM_RESIZE_EDGE_BOTTOM));
	assert(wtwm_auto_relative_resize_edges(90, 90, 18, 45, 63, false) ==
		WTWM_RESIZE_EDGE_NONE);
	assert(wtwm_auto_relative_resize_edges(90, 90, 18, 10, 25, true) ==
		WTWM_RESIZE_EDGE_NONE);

	struct wtwm_interaction_box original = {10, 20, 101, 79};
	struct wtwm_interaction_box result;
	wtwm_anchor_constrained_resize(&original,
		WTWM_RESIZE_EDGE_LEFT | WTWM_RESIZE_EDGE_TOP, 80, 60, &result);
	assert(result.x == 31 && result.y == 39);
	assert(result.width == 80 && result.height == 60);
}

static void rendering_cases(void) {
	struct wtwm_interaction_render_path outline =
		wtwm_interaction_render_path(WTWM_INTERACTION_MOVE, false);
	struct wtwm_interaction_render_path opaque =
		wtwm_interaction_render_path(WTWM_INTERACTION_MOVE, true);
	struct wtwm_interaction_render_path resize =
		wtwm_interaction_render_path(WTWM_INTERACTION_RESIZE, true);
	assert(outline.preview == WTWM_PREVIEW_OUTLINE &&
		outline.commit == WTWM_COMMIT_ON_RELEASE);
	assert(opaque.preview == WTWM_PREVIEW_WINDOW &&
		opaque.commit == WTWM_COMMIT_DURING_MOTION);
	assert(resize.preview == WTWM_PREVIEW_OUTLINE &&
		resize.commit == WTWM_COMMIT_ON_RELEASE);

	struct wtwm_interaction_box original = {10, 20, 100, 80};
	struct wtwm_interaction_box preview = {30, 40, 120, 90};
	struct wtwm_interaction_box value = wtwm_interaction_window_box(outline,
		WTWM_PHASE_MOTION, &original, &preview);
	assert(value.x == 10 && value.y == 20 && value.width == 100);
	value = wtwm_interaction_window_box(outline,
		WTWM_PHASE_COMMIT, &original, &preview);
	assert(value.x == 30 && value.y == 40 && value.width == 120);
	value = wtwm_interaction_window_box(opaque,
		WTWM_PHASE_MOTION, &original, &preview);
	assert(value.x == 30 && value.y == 40 && value.width == 120);
	value = wtwm_interaction_window_box(opaque,
		WTWM_PHASE_ABORT, &original, &preview);
	assert(value.x == 10 && value.y == 20 && value.width == 100);
	value = wtwm_interaction_window_box(resize,
		WTWM_PHASE_ABORT, &original, &preview);
	assert(value.x == 10 && value.y == 20 && value.width == 100);
}

int main(void) {
	threshold_cases();
	constrained_cases();
	bounds_and_function_cases();
	resize_origin_cases();
	rendering_cases();
	return 0;
}
