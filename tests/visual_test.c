/* SPDX-License-Identifier: MIT */
#include <wtwm/visual.h>

#include <assert.h>
#include <stddef.h>

static void assert_box(struct wtwm_visual_box box, int x, int y,
		int width, int height) {
	assert(box.x == x);
	assert(box.y == y);
	assert(box.width == width);
	assert(box.height == height);
}

static void test_default_title_layout(void) {
	struct wtwm_visual_config config = wtwm_visual_config_defaults();
	assert(config.border_width == 2);
	assert(config.frame_padding == 2);
	assert(config.title_padding == 8);
	assert(config.button_indent == 1);
	assert(config.title_button_border_width == 1);
	assert(config.menu_border_width == 2);
	assert(config.menu_shadows);

	struct wtwm_title_layout layout;
	wtwm_title_layout_compute(&config, 200, 13, 11, 80, 1, 1, true,
		&layout);
	assert_box(layout.title, 0, 0, 200, 17);
	assert(layout.title_extent == 19);
	assert_box(layout.text, 22, 2, 80, 13);
	assert(layout.text_baseline_y == 13);
	assert(layout.button_width == 11);
	assert(layout.button_inner_size == 9);
	assert(layout.button_stride == 15);
	assert(layout.button_border_width == 1);
	assert(layout.button_geometry_valid);
	assert(layout.squeezed_title_width == 156);
	assert(layout.focus_highlight_visible);
	assert_box(layout.focus_highlight, 110, 2, 68, 13);

	struct wtwm_visual_box box;
	assert(wtwm_title_button_box(&layout, false, 0, &box));
	assert_box(box, 3, 3, 11, 11);
	assert(wtwm_title_button_box(&layout, true, 0, &box));
	assert_box(box, 186, 3, 11, 11);
	assert(!wtwm_title_button_box(&layout, true, 1, &box));
}

static void test_title_squeezing_and_justification(void) {
	struct wtwm_title_layout layout;
	wtwm_title_layout_compute(NULL, 200, 13, 11, 80, 1, 1, true,
		&layout);
	assert(layout.squeezed_title_width == 156);
	assert(wtwm_title_squeeze_x(200, 144, 2,
		WTWM_TITLE_JUSTIFY_LEFT, 0, 0) == -2);
	assert(wtwm_title_squeeze_x(200, 144, 2,
		WTWM_TITLE_JUSTIFY_CENTER, 0, 0) == 26);
	assert(wtwm_title_squeeze_x(200, 144, 2,
		WTWM_TITLE_JUSTIFY_RIGHT, 0, 0) == 55);
	assert(wtwm_title_squeeze_x(200, 60, 3,
		WTWM_TITLE_JUSTIFY_CENTER, 1, 4) == 17);
	assert(wtwm_title_squeeze_x(200, 60, 3,
		WTWM_TITLE_JUSTIFY_RIGHT, -1, 4) == 88);
	/* Reference clips titles wider than the frame back to the left edge. */
	assert(wtwm_title_squeeze_x(40, 100, 2,
		WTWM_TITLE_JUSTIFY_RIGHT, 0, 0) == -2);
}

static void test_configured_title_spacing(void) {
	struct wtwm_visual_config config = wtwm_visual_config_defaults();
	config.border_width = 5;
	config.frame_padding = 4;
	config.title_padding = 3;
	config.button_indent = 2;
	config.title_button_border_width = 2;

	struct wtwm_title_layout layout;
	wtwm_title_layout_compute(&config, 150, 14, 10, 20, 2, 2, true,
		&layout);
	/* 14 + 2*4 is even, so reference twm rounds the title height to 23. */
	assert_box(layout.title, 0, 0, 150, 23);
	assert(layout.title_extent == 28);
	assert_box(layout.text, 33, 4, 20, 14);
	assert(layout.text_baseline_y == 14);
	assert(layout.button_width == 11);
	assert(layout.button_inner_size == 7);
	assert(layout.button_stride == 13);
	assert(layout.button_y == 6);
	assert_box(layout.focus_highlight, 56, 4, 61, 15);

	struct wtwm_visual_box box;
	assert(wtwm_title_button_box(&layout, false, 1, &box));
	assert_box(box, 19, 6, 11, 11);
	assert(wtwm_title_button_box(&layout, true, 0, &box));
	assert_box(box, 120, 6, 11, 11);
	assert(wtwm_title_button_box(&layout, true, 1, &box));
	assert_box(box, 133, 6, 11, 11);
}

static void test_narrow_title_and_invalid_button_metrics(void) {
	struct wtwm_title_layout layout;
	wtwm_title_layout_compute(NULL, 40, 13, 11, 100, 1, 1, true,
		&layout);
	assert_box(layout.text, 22, 2, 100, 13);
	assert(!layout.focus_highlight_visible);
	/* twm's resize path uses a one-pixel offscreen fallback. */
	assert_box(layout.focus_highlight, 130, 2, 1, 13);

	struct wtwm_visual_config config = wtwm_visual_config_defaults();
	config.frame_padding = 20;
	config.button_indent = 20;
	wtwm_title_layout_compute(&config, 40, 5, 4, 4, 1, 0, true, &layout);
	assert(!layout.button_geometry_valid);
	struct wtwm_visual_box box;
	assert(!wtwm_title_button_box(&layout, false, 0, &box));
}

static void test_default_menu_layout(void) {
	struct wtwm_menu_layout layout;
	wtwm_menu_layout_compute(NULL, 13, 11, 80, 3, false, &layout);
	assert(layout.row_height == 17);
	assert(layout.border_width == 2);
	assert_box(layout.content, 2, 2, 90, 51);
	assert_box(layout.outer, 0, 0, 94, 55);
	assert(layout.shadow_visible);
	assert_box(layout.shadow, 5, 5, 90, 51);
	/* At the default 2px border, one pixel of shadow extends past each edge. */
	assert_box(layout.visible_bounds, 0, 0, 95, 56);

	struct wtwm_visual_box row;
	assert(wtwm_menu_row_box(&layout, 1, &row));
	assert_box(row, 2, 19, 90, 17);
	assert(!wtwm_menu_row_box(&layout, 3, &row));
	int x;
	int y;
	assert(wtwm_menu_text_origin(&layout, 1, 30, false, &x, &y));
	assert(x == 7);
	assert(y == 30);
	assert(wtwm_menu_text_origin(&layout, 1, 30, true, &x, &y));
	assert(x == 32);
	assert(y == 30);
	assert(wtwm_menu_pull_origin(&layout, 1, 11, &x, &y));
	assert(x == 76);
	assert(y == 19);
	assert(!wtwm_menu_pull_origin(&layout, 3, 11, &x, &y));
	assert(!wtwm_menu_pull_origin(&layout, 1, 0, &x, &y));
	assert(wtwm_menu_popup_origin(&layout, false, 130, 90, &x, &y));
	assert(x == 85);
	assert(y == 82);
	assert(wtwm_menu_popup_origin(&layout, true, 85, 51, &x, &y));
	assert(x == 85);
	assert(y == 51);
}

static void test_configured_and_narrow_menus(void) {
	struct wtwm_visual_config config = wtwm_visual_config_defaults();
	config.menu_border_width = 4;
	struct wtwm_menu_layout layout;
	wtwm_menu_layout_compute(&config, 10, 8, 50, 2, true, &layout);
	assert(layout.row_height == 14);
	assert_box(layout.content, 4, 4, 86, 28);
	assert_box(layout.outer, 0, 0, 94, 36);
	assert_box(layout.shadow, 5, 5, 86, 28);
	/* A 4px menu border fully contains the 5px-offset shadow's far edge. */
	assert_box(layout.visible_bounds, 0, 0, 94, 36);

	config.menu_border_width = 2;
	config.menu_shadows = false;
	wtwm_menu_layout_compute(&config, 1, 0, 0, 1, false, &layout);
	/* Empty labels are promoted to one pixel before the 10px menu padding. */
	assert_box(layout.content, 2, 2, 11, 5);
	assert_box(layout.outer, 0, 0, 15, 9);
	assert(!layout.shadow_visible);
	assert_box(layout.visible_bounds, 0, 0, 15, 9);
	int x;
	int y;
	assert(wtwm_menu_text_origin(&layout, 0, 0, true, &x, &y));
	assert(x == 7);
	assert(y == 2);
}

static void test_fractional_scale_projection(void) {
	assert(wtwm_visual_scale_edge(17, 0) == 17);
	assert(wtwm_visual_scale_edge(17, 120) == 17);
	assert(wtwm_visual_scale_edge(17, 240) == 34);
	assert(wtwm_visual_scale_edge(1, 150) == 1);
	assert(wtwm_visual_scale_edge(2, 150) == 3);
	assert(wtwm_visual_scale_edge(-2, 150) == -3);
	struct wtwm_visual_box first = wtwm_visual_scale_box(
		(struct wtwm_visual_box){1, 2, 1, 3}, 150);
	struct wtwm_visual_box second = wtwm_visual_scale_box(
		(struct wtwm_visual_box){2, 2, 4, 3}, 150);
	assert_box(first, 1, 3, 2, 3);
	assert_box(second, 3, 3, 5, 3);
	assert(first.x + first.width == second.x);
}

int main(void) {
	test_default_title_layout();
	test_configured_title_spacing();
	test_title_squeezing_and_justification();
	test_narrow_title_and_invalid_button_metrics();
	test_default_menu_layout();
	test_configured_and_narrow_menus();
	test_fractional_scale_projection();
	return 0;
}
