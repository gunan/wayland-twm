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
