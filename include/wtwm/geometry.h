/* SPDX-License-Identifier: MIT */
#ifndef WTWM_GEOMETRY_H
#define WTWM_GEOMETRY_H

#include <stdbool.h>
#include <stdint.h>

enum wtwm_size_hint_flag {
	WTWM_SIZE_HINT_MIN = 1u << 0,
	WTWM_SIZE_HINT_MAX = 1u << 1,
	WTWM_SIZE_HINT_BASE = 1u << 2,
	WTWM_SIZE_HINT_INCREMENT = 1u << 3,
	WTWM_SIZE_HINT_ASPECT = 1u << 4,
};

struct wtwm_size_hints {
	uint32_t flags;
	int min_width;
	int min_height;
	int max_width;
	int max_height;
	int base_width;
	int base_height;
	int width_increment;
	int height_increment;
	int min_aspect_x;
	int min_aspect_y;
	int max_aspect_x;
	int max_aspect_y;
};

struct wtwm_frame_geometry {
	int client_width;
	int client_height;
	int border_width;
	int title_bar_height;
	int title_extent;
	int frame_width;
	int frame_height;
	int outer_width;
	int outer_height;
	int content_x;
	int content_y;
};

struct wtwm_window_position {
	int frame_x;
	int frame_y;
	int client_x;
	int client_y;
};

/*
 * twm makes the title bar font-height + 2 * FramePadding pixels high, then
 * rounds an even result up so that title buttons are centered on an odd row.
 */
int wtwm_title_bar_height(int font_height, int frame_padding);

/*
 * Compute twm's frame and client extents. frame_width/frame_height exclude the
 * frame's outer border, while outer_width/outer_height include it. title_extent
 * is twm's title_height: the title bar plus the lower title-window border.
 */
void wtwm_frame_geometry(int client_width, int client_height, int border_width,
	int title_bar_height, bool has_title, struct wtwm_frame_geometry *geometry);

/* Convert an initial ICCCM position into twm's frame and client coordinates. */
void wtwm_initial_window_position(int requested_x, int requested_y,
	int original_client_border, const struct wtwm_frame_geometry *geometry,
	bool use_client_border_width, int gravity_x, int gravity_y,
	struct wtwm_window_position *position);

/* Apply the CWX/CWY translation used by twm's HandleConfigureRequest. */
void wtwm_configure_request_position(int current_frame_x, int current_frame_y,
	int requested_x, int requested_y, bool has_x, bool has_y,
	const struct wtwm_frame_geometry *geometry, int gravity_y,
	struct wtwm_window_position *position);

/*
 * Apply twm 1.0.13.1's ConstrainSize ordering to client dimensions: clamp,
 * fit base + N * increment, then adjust aspect. limit_width/limit_height are
 * the compositor's absolute maxima and must be positive.
 */
void wtwm_constrain_size(const struct wtwm_size_hints *hints,
	int limit_width, int limit_height, int *width, int *height);

#endif
