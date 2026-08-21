/* SPDX-License-Identifier: MIT */
#include "hardening.h"

#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static void expect_size(int requested_width, int requested_height,
		int fallback_width, int fallback_height, int expected_width,
		int expected_height, unsigned expected_adjustment) {
	int width = 0;
	int height = 0;
	unsigned adjustment = wtwm_client_size_sanitize(requested_width,
		requested_height, fallback_width, fallback_height, &width, &height);
	assert(width == expected_width);
	assert(height == expected_height);
	assert(adjustment == expected_adjustment);
	assert(wtwm_client_size_adjusted(adjustment) ==
		(expected_adjustment != WTWM_CLIENT_SIZE_UNCHANGED));
}

static struct wtwm_client_positioner valid_positioner(void) {
	return (struct wtwm_client_positioner){
		.width = 320,
		.height = 200,
		.anchor_x = -20,
		.anchor_y = 30,
		.anchor_width = 640,
		.anchor_height = 480,
		.parent_width = 800,
		.parent_height = 600,
		.offset_x = 5,
		.offset_y = -7,
		.geometry_x = 10,
		.geometry_y = 20,
		.geometry_width = 320,
		.geometry_height = 200,
	};
}

int main(void) {
	expect_size(640, 480, 1, 1, 640, 480,
		WTWM_CLIENT_SIZE_UNCHANGED);
	expect_size(1, WTWM_CLIENT_SIZE_MAX, 10, 20,
		1, WTWM_CLIENT_SIZE_MAX, WTWM_CLIENT_SIZE_UNCHANGED);
	expect_size(0, -1, 640, 480, 640, 480,
		WTWM_CLIENT_WIDTH_FALLBACK | WTWM_CLIENT_HEIGHT_FALLBACK);
	expect_size(INT_MIN, 10, 0, 20, 1, 10,
		WTWM_CLIENT_WIDTH_FALLBACK);
	expect_size(10, 0, 20, INT_MAX, 10, WTWM_CLIENT_SIZE_MAX,
		WTWM_CLIENT_HEIGHT_FALLBACK);
	expect_size(WTWM_CLIENT_SIZE_MAX + 1, INT_MAX, 1, 1,
		WTWM_CLIENT_SIZE_MAX, WTWM_CLIENT_SIZE_MAX,
		WTWM_CLIENT_WIDTH_CLAMPED | WTWM_CLIENT_HEIGHT_CLAMPED);
	assert(wtwm_client_geometry_in_bounds(0, 0, 640, 480));
	assert(wtwm_client_geometry_in_bounds(-WTWM_CLIENT_SIZE_MAX,
		WTWM_CLIENT_SIZE_MAX, 1, WTWM_CLIENT_SIZE_MAX));
	assert(!wtwm_client_geometry_in_bounds(INT_MIN, 0, 640, 480));
	assert(!wtwm_client_geometry_in_bounds(0, INT_MAX, 640, 480));
	assert(!wtwm_client_geometry_in_bounds(0, 0, INT_MAX, INT_MAX));
	assert(!wtwm_client_geometry_in_bounds(0, 0, 0, 480));
	assert(wtwm_client_point_in_bounds(-WTWM_CLIENT_SIZE_MAX,
		WTWM_CLIENT_SIZE_MAX));
	assert(!wtwm_client_point_in_bounds(INT_MIN, 0));

	struct wtwm_client_positioner positioner = valid_positioner();
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_VALID);
	positioner.parent_width = positioner.parent_height = 0;
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_VALID);

	positioner = valid_positioner();
	positioner.width = INT_MAX;
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_INVALID_SIZE);
	positioner = valid_positioner();
	positioner.anchor_x = INT_MIN;
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_INVALID_ANCHOR_RECT);
	positioner = valid_positioner();
	positioner.parent_height = INT_MAX;
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_INVALID_PARENT_SIZE);
	positioner = valid_positioner();
	positioner.offset_y = INT_MAX;
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_INVALID_OFFSET);
	positioner = valid_positioner();
	positioner.geometry_width = INT_MAX;
	assert(wtwm_client_positioner_validate(&positioner) ==
		WTWM_POSITIONER_INVALID_GEOMETRY);
	assert(strcmp(wtwm_client_positioner_error_name(
		WTWM_POSITIONER_INVALID_ANCHOR_RECT), "anchor_rect") == 0);

	/* Exercise the boundary policy over a deterministic hostile-size stream.
	 * This catches wraparound and guarantees that no input can escape the range
	 * used by compositor decoration math. */
	uint32_t state = UINT32_C(0x6d2b79f5);
	for (size_t index = 0; index < 250000; ++index) {
		state = state * UINT32_C(1664525) + UINT32_C(1013904223);
		int requested_width = (int)(state % UINT32_C(300001)) - 100000;
		state = state * UINT32_C(1664525) + UINT32_C(1013904223);
		int requested_height = (int)(state % UINT32_C(300001)) - 100000;
		int width = 0, height = 0;
		(void)wtwm_client_size_sanitize(requested_width, requested_height,
			640, 480, &width, &height);
		assert(width >= 1 && width <= WTWM_CLIENT_SIZE_MAX);
		assert(height >= 1 && height <= WTWM_CLIENT_SIZE_MAX);
		if (requested_width >= 1 && requested_width <= WTWM_CLIENT_SIZE_MAX)
			assert(width == requested_width);
		if (requested_height >= 1 && requested_height <= WTWM_CLIENT_SIZE_MAX)
			assert(height == requested_height);
	}
	return 0;
}
