/* SPDX-License-Identifier: MIT */
#include <wtwm/geometry.h>

#include <assert.h>
#include <limits.h>
#include <stdio.h>

static void assert_size(const struct wtwm_size_hints *hints,
		int requested_width, int requested_height,
		int expected_width, int expected_height) {
	int width = requested_width;
	int height = requested_height;
	wtwm_constrain_size(hints, 32000, 32000, &width, &height);
	assert(width == expected_width);
	assert(height == expected_height);
}

static void assert_limited_size(const struct wtwm_size_hints *hints,
		int limit_width, int limit_height,
		int requested_width, int requested_height,
		int expected_width, int expected_height) {
	int width = requested_width;
	int height = requested_height;
	wtwm_constrain_size(hints, limit_width, limit_height, &width, &height);
	assert(width == expected_width);
	assert(height == expected_height);
}

static void test_title_and_frame_geometry(void) {
	assert(wtwm_title_bar_height(13, 2) == 17);
	assert(wtwm_title_bar_height(12, 2) == 17);
	assert(wtwm_title_bar_height(13, 0) == 13);

	struct wtwm_frame_geometry geometry;
	wtwm_frame_geometry(100, 65, 3, 17, true, &geometry);
	assert(geometry.client_width == 100);
	assert(geometry.client_height == 65);
	assert(geometry.border_width == 3);
	assert(geometry.title_bar_height == 17);
	assert(geometry.title_extent == 20);
	assert(geometry.frame_width == 100);
	assert(geometry.frame_height == 85);
	assert(geometry.outer_width == 106);
	assert(geometry.outer_height == 91);
	assert(geometry.content_x == 3);
	assert(geometry.content_y == 23);

	/* NoTitle removes only the title; twm retains the frame border. */
	wtwm_frame_geometry(100, 65, 3, 17, false, &geometry);
	assert(geometry.title_bar_height == 0);
	assert(geometry.title_extent == 0);
	assert(geometry.frame_height == 65);
	assert(geometry.outer_width == 106);
	assert(geometry.outer_height == 71);
	assert(geometry.content_x == 3);
	assert(geometry.content_y == 3);
}

static void test_title_rule_order(void) {
	assert(wtwm_window_has_title(false, false, false, false, false));
	assert(!wtwm_window_has_title(true, false, false, false, false));
	assert(wtwm_window_has_title(true, true, false, false, false));
	assert(!wtwm_window_has_title(false, true, true, false, false));
	assert(!wtwm_window_has_title(true, true, true, false, false));

	/* Reference transient suppression is last, even after MakeTitle. */
	assert(!wtwm_window_has_title(false, false, false, true, false));
	assert(!wtwm_window_has_title(true, true, false, true, false));
	assert(wtwm_window_has_title(false, false, false, true, true));
	assert(wtwm_window_has_title(true, true, false, true, true));
	assert(!wtwm_window_has_title(false, true, true, true, true));
}

static void test_reference_window_coordinates(void) {
	struct wtwm_frame_geometry geometry;
	wtwm_frame_geometry(100, 65, 3, 17, true, &geometry);
	struct wtwm_window_position position;
	wtwm_initial_window_position(30, 28, 0, &geometry, false, -1, -1,
		&position);
	assert(position.frame_x == 30);
	assert(position.frame_y == 28);
	assert(position.client_x == 33);
	assert(position.client_y == 51);

	/* ClientBorderWidth makes the original border the frame border. */
	wtwm_frame_geometry(100, 65, 5, 17, true, &geometry);
	wtwm_initial_window_position(30, 28, 5, &geometry, true, -1, -1,
		&position);
	assert(position.frame_x == 30);
	assert(position.frame_y == 28);
	assert(position.client_x == 35);
	assert(position.client_y == 55);

	/* A NorthWest CWY request addresses the client before title translation. */
	wtwm_frame_geometry(277, 199, 2, 21, true, &geometry);
	wtwm_configure_request_position(44, 55, 120, 100, true, true,
		&geometry, -1, &position);
	assert(position.frame_x == 118);
	assert(position.frame_y == 98);
	assert(position.client_x == 120);
	assert(position.client_y == 123);

	wtwm_configure_request_position(44, 55, 120, 100, true, true,
		&geometry, 1, &position);
	assert(position.frame_y == 75);
	assert(position.client_y == 100);
}

static void test_initial_gravity_matrix(void) {
	struct wtwm_frame_geometry geometry;
	wtwm_frame_geometry(137, 91, 2, 17, true, &geometry);
	const int expected_x[] = {160, 162, 164};
	const int expected_y[] = {120, 103, 105};
	for (int gravity_y = -1; gravity_y <= 1; ++gravity_y) {
		for (int gravity_x = -1; gravity_x <= 1; ++gravity_x) {
			struct wtwm_window_position position;
			wtwm_initial_window_position(160, 120, 4, &geometry, false,
				gravity_x, gravity_y, &position);
			assert(position.frame_x == expected_x[gravity_x + 1]);
			assert(position.frame_y == expected_y[gravity_y + 1]);
			assert(position.client_x == position.frame_x + 2);
			assert(position.client_y == position.frame_y + 21);
		}
	}
}

static void test_min_max_base_and_increments(void) {
	struct wtwm_size_hints hints = {
		.flags = WTWM_SIZE_HINT_MIN | WTWM_SIZE_HINT_MAX,
		.min_width = 100, .min_height = 80,
		.max_width = 300, .max_height = 200,
	};
	assert_size(&hints, 40, 20, 100, 80);
	assert_size(&hints, 400, 300, 300, 200);

	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_BASE | WTWM_SIZE_HINT_INCREMENT,
		.base_width = 40, .base_height = 30,
		.width_increment = 13, .height_increment = 7,
	};
	assert_size(&hints, 210, 130, 209, 128);
	assert_size(&hints, 1, 1, 40, 30);

	/* This surprising ordering is reference behavior: fit follows clamping. */
	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_MIN | WTWM_SIZE_HINT_MAX |
			WTWM_SIZE_HINT_INCREMENT,
		.min_width = 100, .min_height = 80,
		.max_width = 105, .max_height = 85,
		.width_increment = 16, .height_increment = 16,
	};
	assert_size(&hints, 105, 85, 100, 80);

	hints.width_increment = 0;
	hints.height_increment = 0;
	assert_size(&hints, 103, 83, 103, 83);

	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_MIN | WTWM_SIZE_HINT_INCREMENT,
		.min_width = 40, .min_height = 30,
		.width_increment = 13, .height_increment = 7,
	};
	assert_limited_size(&hints, 1000, 1000, 80, 60, 79, 58);

	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_MIN | WTWM_SIZE_HINT_BASE |
			WTWM_SIZE_HINT_INCREMENT,
		.min_width = 50, .min_height = 40,
		.base_width = 10, .base_height = 5,
		.width_increment = 13, .height_increment = 7,
	};
	assert_limited_size(&hints, 1000, 1000, 50, 40, 49, 40);

	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_MIN | WTWM_SIZE_HINT_MAX,
		.min_width = 100, .min_height = 100,
		.max_width = 80, .max_height = 80,
	};
	assert_limited_size(&hints, 1000, 1000, 50, 50, 80, 80);

	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_MAX | WTWM_SIZE_HINT_BASE |
			WTWM_SIZE_HINT_INCREMENT,
		.max_width = 100, .max_height = 90,
		.width_increment = 16, .height_increment = 16,
	};
	assert_limited_size(&hints, 1000, 1000, 103, 95, 96, 80);
}

static void test_aspect_order_and_rounding(void) {
	struct wtwm_size_hints hints = {
		.flags = WTWM_SIZE_HINT_BASE | WTWM_SIZE_HINT_INCREMENT |
			WTWM_SIZE_HINT_ASPECT,
		.base_width = 40, .base_height = 30,
		.width_increment = 13, .height_increment = 7,
		.min_aspect_x = 4, .min_aspect_y = 3,
		.max_aspect_x = 16, .max_aspect_y = 9,
	};
	assert_size(&hints, 210, 130, 209, 128);

	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_INCREMENT | WTWM_SIZE_HINT_ASPECT,
		.width_increment = 10, .height_increment = 1,
		.min_aspect_x = 4, .min_aspect_y = 3,
		.max_aspect_x = 16, .max_aspect_y = 9,
	};
	/* twm rounds the correction down, so an increment may leave a small error. */
	assert_limited_size(&hints, 1000, 1000, 100, 100, 130, 100);

	/* If growing width would cross max, twm shrinks height instead. */
	hints.flags |= WTWM_SIZE_HINT_MAX;
	hints.max_width = 120;
	hints.max_height = 1000;
	assert_limited_size(&hints, 1000, 1000, 100, 100, 100, 75);

	/* Maximum-aspect correction first grows height, then falls back to width. */
	hints = (struct wtwm_size_hints){
		.flags = WTWM_SIZE_HINT_INCREMENT | WTWM_SIZE_HINT_ASPECT,
		.width_increment = 1, .height_increment = 1,
		.min_aspect_x = 1, .min_aspect_y = 1000,
		.max_aspect_x = 16, .max_aspect_y = 9,
	};
	assert_limited_size(&hints, 1000, 1000, 200, 100, 200, 112);

	hints.flags |= WTWM_SIZE_HINT_MAX;
	hints.max_width = 1000;
	hints.max_height = 105;
	hints.width_increment = 10;
	assert_limited_size(&hints, 1000, 1000, 200, 100, 180, 100);
}

static void test_absolute_limits_and_empty_hints(void) {
	int width = INT_MAX;
	int height = INT_MAX;
	wtwm_constrain_size(NULL, 32767, 32766, &width, &height);
	assert(width == 32767);
	assert(height == 32766);

	width = 0;
	height = -10;
	wtwm_constrain_size(NULL, 32767, 32766, &width, &height);
	assert(width == 1);
	assert(height == 1);
}

int main(void) {
	test_title_and_frame_geometry();
	test_title_rule_order();
	test_reference_window_coordinates();
	test_initial_gravity_matrix();
	test_min_max_base_and_increments();
	test_aspect_order_and_rounding();
	test_absolute_limits_and_empty_hints();
	puts("geometry tests passed");
	return 0;
}
