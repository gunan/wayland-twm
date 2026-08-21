/* SPDX-License-Identifier: MIT */

#include "hardening.h"

#include <assert.h>
#include <stddef.h>

static int sanitize_fallback(int value) {
	if (value < 1) return 1;
	if (value > WTWM_CLIENT_SIZE_MAX) return WTWM_CLIENT_SIZE_MAX;
	return value;
}

unsigned wtwm_client_size_sanitize(int requested_width, int requested_height,
		int fallback_width, int fallback_height, int *width, int *height) {
	assert(width != NULL);
	assert(height != NULL);

	unsigned adjustment = WTWM_CLIENT_SIZE_UNCHANGED;
	if (requested_width < 1) {
		*width = sanitize_fallback(fallback_width);
		adjustment |= WTWM_CLIENT_WIDTH_FALLBACK;
	} else if (requested_width > WTWM_CLIENT_SIZE_MAX) {
		*width = WTWM_CLIENT_SIZE_MAX;
		adjustment |= WTWM_CLIENT_WIDTH_CLAMPED;
	} else {
		*width = requested_width;
	}

	if (requested_height < 1) {
		*height = sanitize_fallback(fallback_height);
		adjustment |= WTWM_CLIENT_HEIGHT_FALLBACK;
	} else if (requested_height > WTWM_CLIENT_SIZE_MAX) {
		*height = WTWM_CLIENT_SIZE_MAX;
		adjustment |= WTWM_CLIENT_HEIGHT_CLAMPED;
	} else {
		*height = requested_height;
	}
	return adjustment;
}

bool wtwm_client_size_adjusted(unsigned adjustment) {
	return adjustment != WTWM_CLIENT_SIZE_UNCHANGED;
}

bool wtwm_client_geometry_in_bounds(int x, int y, int width, int height) {
	return wtwm_client_point_in_bounds(x, y) &&
		width >= 1 && width <= WTWM_CLIENT_SIZE_MAX &&
		height >= 1 && height <= WTWM_CLIENT_SIZE_MAX;
}

bool wtwm_client_point_in_bounds(int x, int y) {
	return x >= -WTWM_CLIENT_SIZE_MAX && x <= WTWM_CLIENT_SIZE_MAX &&
		y >= -WTWM_CLIENT_SIZE_MAX && y <= WTWM_CLIENT_SIZE_MAX;
}

enum wtwm_client_positioner_error wtwm_client_positioner_validate(
		const struct wtwm_client_positioner *positioner) {
	assert(positioner != NULL);
	if (positioner->width < 1 || positioner->width > WTWM_CLIENT_SIZE_MAX ||
			positioner->height < 1 ||
			positioner->height > WTWM_CLIENT_SIZE_MAX)
		return WTWM_POSITIONER_INVALID_SIZE;
	if (!wtwm_client_geometry_in_bounds(positioner->anchor_x,
			positioner->anchor_y, positioner->anchor_width,
			positioner->anchor_height))
		return WTWM_POSITIONER_INVALID_ANCHOR_RECT;
	bool parent_omitted = positioner->parent_width == 0 &&
		positioner->parent_height == 0;
	if (!parent_omitted &&
			(positioner->parent_width < 1 ||
			positioner->parent_width > WTWM_CLIENT_SIZE_MAX ||
			positioner->parent_height < 1 ||
			positioner->parent_height > WTWM_CLIENT_SIZE_MAX))
		return WTWM_POSITIONER_INVALID_PARENT_SIZE;
	if (!wtwm_client_point_in_bounds(positioner->offset_x,
			positioner->offset_y))
		return WTWM_POSITIONER_INVALID_OFFSET;
	if (!wtwm_client_geometry_in_bounds(positioner->geometry_x,
			positioner->geometry_y, positioner->geometry_width,
			positioner->geometry_height))
		return WTWM_POSITIONER_INVALID_GEOMETRY;
	return WTWM_POSITIONER_VALID;
}

const char *wtwm_client_positioner_error_name(
		enum wtwm_client_positioner_error error) {
	switch (error) {
	case WTWM_POSITIONER_VALID: return "none";
	case WTWM_POSITIONER_INVALID_SIZE: return "size";
	case WTWM_POSITIONER_INVALID_ANCHOR_RECT: return "anchor_rect";
	case WTWM_POSITIONER_INVALID_PARENT_SIZE: return "parent_size";
	case WTWM_POSITIONER_INVALID_OFFSET: return "offset";
	case WTWM_POSITIONER_INVALID_GEOMETRY: return "geometry";
	}
	return "unknown";
}
