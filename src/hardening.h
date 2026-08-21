/* SPDX-License-Identifier: MIT */
#ifndef WTWM_HARDENING_H
#define WTWM_HARDENING_H

#include <stdbool.h>

/* X11 client geometry is limited to 16-bit dimensions.  Applying the same
 * ceiling to native clients keeps every later decoration and scene-geometry
 * calculation in a small, well-defined integer range. */
#define WTWM_CLIENT_SIZE_MAX 65535

enum wtwm_client_size_adjustment {
	WTWM_CLIENT_SIZE_UNCHANGED = 0,
	WTWM_CLIENT_WIDTH_FALLBACK = 1 << 0,
	WTWM_CLIENT_HEIGHT_FALLBACK = 1 << 1,
	WTWM_CLIENT_WIDTH_CLAMPED = 1 << 2,
	WTWM_CLIENT_HEIGHT_CLAMPED = 1 << 3,
};

enum wtwm_client_positioner_error {
	WTWM_POSITIONER_VALID = 0,
	WTWM_POSITIONER_INVALID_SIZE,
	WTWM_POSITIONER_INVALID_ANCHOR_RECT,
	WTWM_POSITIONER_INVALID_PARENT_SIZE,
	WTWM_POSITIONER_INVALID_OFFSET,
	WTWM_POSITIONER_INVALID_GEOMETRY,
};

struct wtwm_client_positioner {
	int width, height;
	int anchor_x, anchor_y, anchor_width, anchor_height;
	int parent_width, parent_height;
	int offset_x, offset_y;
	int geometry_x, geometry_y, geometry_width, geometry_height;
};

/**
 * Sanitize client-controlled geometry before it reaches compositor frame math.
 * Non-positive dimensions retain the last accepted value, while dimensions
 * above WTWM_CLIENT_SIZE_MAX are clipped to that ceiling.
 *
 * The fallbacks are sanitized too, so the result is always in the inclusive
 * range [1, WTWM_CLIENT_SIZE_MAX].  The return value is a bitmask describing
 * every adjustment made to the requested dimensions.
 */
unsigned wtwm_client_size_sanitize(int requested_width, int requested_height,
	int fallback_width, int fallback_height, int *width, int *height);

bool wtwm_client_size_adjusted(unsigned adjustment);

/**
 * Return whether client-controlled geometry can safely reach scene arithmetic.
 * Coordinates may be negative for shadows, but every field is kept within the
 * same 16-bit magnitude used for client sizes so coordinate-plus-size math
 * cannot overflow a signed int.
 */
bool wtwm_client_geometry_in_bounds(int x, int y, int width, int height);

/** Return whether a client-controlled coordinate is safe for signed-int math. */
bool wtwm_client_point_in_bounds(int x, int y);

/**
 * Validate every client-controlled xdg-positioner field that can reach wtwm's
 * popup placement, scene, or unconstrain calculations.  A zero parent size is
 * the public wlroots representation for an omitted set_parent_size request;
 * otherwise both parent dimensions must be positive and bounded.
 */
enum wtwm_client_positioner_error wtwm_client_positioner_validate(
	const struct wtwm_client_positioner *positioner);

const char *wtwm_client_positioner_error_name(
	enum wtwm_client_positioner_error error);

#endif
