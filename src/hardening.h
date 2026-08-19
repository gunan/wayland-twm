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

#endif
