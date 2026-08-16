/* SPDX-License-Identifier: MIT */
#include <wtwm/placement.h>

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

static void parses_policy_and_maximum(void) {
	enum wtwm_use_p_position mode = WTWM_USE_P_POSITION_OFF;
	assert(wtwm_parse_use_p_position("ON", &mode));
	assert(mode == WTWM_USE_P_POSITION_ON);
	assert(wtwm_parse_use_p_position("nonzero", &mode));
	assert(mode == WTWM_USE_P_POSITION_NON_ZERO);
	assert(!wtwm_parse_use_p_position("sometimes", &mode));
	int width = 0, height = 0;
	assert(wtwm_parse_max_window_size("800x600", &width, &height));
	assert(width == 800 && height == 600);
	assert(wtwm_parse_max_window_size("=1024X768-2+7", &width, &height));
	assert(width == 1024 && height == 768);
	assert(!wtwm_parse_max_window_size("800", &width, &height));
	assert(!wtwm_parse_max_window_size("0x600", &width, &height));
	assert(!wtwm_parse_max_window_size("800x-1", &width, &height));
	wtwm_default_max_window_size(640, 480, &width, &height);
	assert(width == 32127 && height == 32287);
}

static void matches_position_hint_policy(void) {
	assert(!wtwm_placement_asks_user(false, true, false,
		WTWM_USE_P_POSITION_OFF, 0, 0));
	assert(wtwm_placement_asks_user(false, false, true,
		WTWM_USE_P_POSITION_OFF, 40, 50));
	assert(!wtwm_placement_asks_user(false, false, true,
		WTWM_USE_P_POSITION_ON, 0, 0));
	assert(wtwm_placement_asks_user(false, false, true,
		WTWM_USE_P_POSITION_NON_ZERO, 0, 0));
	assert(!wtwm_placement_asks_user(false, false, true,
		WTWM_USE_P_POSITION_NON_ZERO, 0, 7));
	assert(!wtwm_placement_asks_user(true, false, false,
		WTWM_USE_P_POSITION_OFF, 0, 0));
}

static void matches_random_sequence_and_edge_reset(void) {
	struct wtwm_random_placement state;
	wtwm_random_placement_init(&state);
	int x = 0, y = 0;
	wtwm_random_placement_next(&state, 640, 480, 100, 80, &x, &y);
	assert(x == 50 && y == 50);
	wtwm_random_placement_next(&state, 640, 480, 100, 80, &x, &y);
	assert(x == 80 && y == 80);
	wtwm_random_placement_next(&state, 640, 480, 100, 80, &x, &y);
	assert(x == 110 && y == 110);
	assert(state.next_x == 140 && state.next_y == 140);

	wtwm_random_placement_init(&state);
	wtwm_random_placement_next(&state, 120, 100, 100, 80, &x, &y);
	assert(x == 20 && y == 20);
	assert(state.next_x == 50 && state.next_y == 50);
	wtwm_random_placement_next(&state, 120, 100, 100, 80, &x, &y);
	assert(x == 20 && y == 20);
	assert(state.next_x == 50 && state.next_y == 50);

	wtwm_random_placement_init(&state);
	wtwm_random_placement_next(&state, 120, 100, 200, 180, &x, &y);
	assert(x == 0 && y == 0);
	assert(state.next_x == 30 && state.next_y == 30);
	wtwm_random_placement_seed(&state, UINT_MAX);
	assert(state.next_x == INT_MAX && state.next_y == INT_MAX);
}

static void clips_sizes_and_outer_positions(void) {
	int width = 900, height = 700;
	wtwm_clip_initial_size(800, 600, &width, &height);
	assert(width == 800 && height == 600);
	struct wtwm_placement_area area = {.x = -20, .y = 10,
		.width = 120, .height = 100};
	int x = 90, y = -50;
	wtwm_clamp_outer_position(&area, 80, 60, &x, &y);
	assert(x == 20 && y == 10);
	x = 50; y = 80;
	wtwm_clamp_outer_position(&area, 200, 180, &x, &y);
	assert(x == -100 && y == -70);
	assert(strcmp(wtwm_placement_kind_name(WTWM_PLACEMENT_RANDOM), "random") == 0);
	wtwm_pointer_placement(0, 8, 9, &x, &y);
	assert(x == 8 && y == 9);
	wtwm_pointer_placement(13, 8, 9, &x, &y);
	assert(x == 8 && y == 9);
}

static void models_interactive_prompt(void) {
	struct wtwm_placement_area area = {.x = 10, .y = 20,
		.width = 200, .height = 160};
	int x = 0, y = 0;
	wtwm_placement_prompt_position(&area, false, 80, 60, 205, 175, &x, &y);
	assert(x == 205 && y == 175);
	wtwm_placement_prompt_position(&area, true, 80, 60, 205, 175, &x, &y);
	assert(x == 130 && y == 120);
	/* Reference near-edge then far-edge ordering keeps this oversized result. */
	wtwm_placement_prompt_position(&area, true, 260, 220, -50, -40, &x, &y);
	assert(x == -50 && y == -40);

	assert(wtwm_placement_button(1) == WTWM_PLACEMENT_BUTTON_CONFIRM);
	assert(wtwm_placement_button(2) == WTWM_PLACEMENT_BUTTON_RESIZE);
	assert(wtwm_placement_button(3) == WTWM_PLACEMENT_BUTTON_FILL);
	assert(wtwm_placement_button(8) == WTWM_PLACEMENT_BUTTON_IGNORE);

	int width = 80, height = 60;
	wtwm_placement_fill_size(&area, 50, 60, 6, 28, &width, &height);
	assert(width == 154 && height == 92);
	wtwm_placement_fill_size(&area, 500, 500, 6, 28, &width, &height);
	assert(width == 1 && height == 1);
}

int main(void) {
	parses_policy_and_maximum();
	matches_position_hint_policy();
	matches_random_sequence_and_edge_reset();
	clips_sizes_and_outer_positions();
	models_interactive_prompt();
	puts("placement tests passed");
	return 0;
}
