/* SPDX-License-Identifier: MIT */
#ifndef WTWM_INTERACTION_H
#define WTWM_INTERACTION_H

#include <stdbool.h>
#include <stdint.h>

enum wtwm_interaction_kind {
	WTWM_INTERACTION_MOVE,
	WTWM_INTERACTION_RESIZE,
};

enum wtwm_constrained_axis {
	WTWM_AXIS_NONE,
	WTWM_AXIS_HORIZONTAL,
	WTWM_AXIS_VERTICAL,
};

enum wtwm_resize_edge {
	WTWM_RESIZE_EDGE_NONE = 0,
	WTWM_RESIZE_EDGE_LEFT = 1u << 0,
	WTWM_RESIZE_EDGE_RIGHT = 1u << 1,
	WTWM_RESIZE_EDGE_TOP = 1u << 2,
	WTWM_RESIZE_EDGE_BOTTOM = 1u << 3,
};

enum wtwm_interaction_preview {
	WTWM_PREVIEW_OUTLINE,
	WTWM_PREVIEW_WINDOW,
};

enum wtwm_interaction_commit {
	WTWM_COMMIT_ON_RELEASE,
	WTWM_COMMIT_DURING_MOTION,
};

enum wtwm_interaction_phase {
	WTWM_PHASE_MOTION,
	WTWM_PHASE_COMMIT,
	WTWM_PHASE_ABORT,
};

struct wtwm_interaction_box {
	int x;
	int y;
	int width;
	int height;
};

struct wtwm_interaction_render_path {
	enum wtwm_interaction_preview preview;
	enum wtwm_interaction_commit commit;
};

/* twm starts once either absolute pointer delta reaches MoveDelta. */
bool wtwm_interaction_threshold_reached(int move_delta, int dx, int dy);

/* ConstrainedMoveTime is enabled and compared strictly, not inclusively. */
bool wtwm_constrained_move_entry(int configured_ms, uint32_t elapsed_ms);

/* Choose the first constrained direction; the vertical test intentionally wins. */
enum wtwm_constrained_axis wtwm_constrained_move_axis(int outer_width,
	int outer_height, int pointer_x, int pointer_y);

/* Apply DontMoveOff in twm's original near-edge then far-edge order. */
void wtwm_clamp_move(int screen_width, int screen_height, int outer_width,
	int outer_height, bool force, int *x, int *y);

/* Return the initial resize edges selected by AutoRelativeResize. */
uint32_t wtwm_auto_relative_resize_edges(int width, int height,
	int title_height, int pointer_x, int pointer_y, bool from_titlebar);

/* Preserve the opposite edge after size constraints alter a left/top resize. */
void wtwm_anchor_constrained_resize(const struct wtwm_interaction_box *original,
	uint32_t edges, int constrained_width, int constrained_height,
	struct wtwm_interaction_box *result);

/* f.deltastop continues only while the preceding interaction did not move. */
bool wtwm_delta_stop_continues(bool window_moved);

struct wtwm_interaction_render_path wtwm_interaction_render_path(
	enum wtwm_interaction_kind kind, bool opaque_move);

/* The actual window geometry for motion, commit, and abort phases. */
struct wtwm_interaction_box wtwm_interaction_window_box(
	struct wtwm_interaction_render_path path, enum wtwm_interaction_phase phase,
	const struct wtwm_interaction_box *original,
	const struct wtwm_interaction_box *preview);

#endif
