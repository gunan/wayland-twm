/* SPDX-License-Identifier: MIT */
#include <wtwm/actions.h>

#include <assert.h>

static void zoom_cases(void) {
	struct wtwm_interaction_box output = {10, 20, 1001, 801};
	struct wtwm_interaction_box original = {100, 120, 300, 200};
	struct wtwm_zoom_state state = {0};
	struct wtwm_interaction_box value = wtwm_action_zoom(WTWM_ACTION_ZOOM,
		&output, 4, 24, &original, &state);
	assert(value.x == 100 && value.y == 20 && value.width == 300 &&
		value.height == 777);
	value = wtwm_action_zoom(WTWM_ACTION_ZOOM, &output, 4, 24, &value, &state);
	assert(value.x == 100 && value.y == 120 && value.width == 300 &&
		value.height == 200 && state.mode == WTWM_ACTION_NOP);
	value = wtwm_action_zoom(WTWM_ACTION_LEFTZOOM, &output, 4, 24,
		&original, &state);
	assert(value.x == 10 && value.y == 20 && value.width == 496 &&
		value.height == 777);
	value = wtwm_action_zoom(WTWM_ACTION_RIGHTZOOM, &output, 4, 24,
		&value, &state);
	assert(value.x == 510 && value.width == 496 && value.height == 777);
	value = wtwm_action_zoom(WTWM_ACTION_RIGHTZOOM, &output, 4, 24,
		&value, &state);
	assert(value.x == original.x && value.y == original.y &&
		value.width == original.width && value.height == original.height);
	value = wtwm_action_zoom(WTWM_ACTION_TOPZOOM, &output, 4, 24,
		&original, &state);
	assert(value.x == 10 && value.y == 20 && value.width == 997 &&
		value.height == 376);
	value = wtwm_action_zoom(WTWM_ACTION_BOTTOMZOOM, &output, 4, 24,
		&value, &state);
	assert(value.y == 420 && value.height == 376);
	value = wtwm_action_zoom(WTWM_ACTION_FULLZOOM, &output, 4, 24,
		&value, &state);
	assert(value.x == 10 && value.y == 20 && value.width == 997 &&
		value.height == 777);
	value = wtwm_action_zoom(WTWM_ACTION_HORIZOOM, &output, 4, 24,
		&value, &state);
	assert(value.x == 10 && value.y == 20 && value.width == 997 &&
		value.height == 777);
}

static void navigation_cases(void) {
	assert(wtwm_action_cycle_index(0, 0, true) == -1);
	assert(wtwm_action_cycle_index(3, -1, true) == 0);
	assert(wtwm_action_cycle_index(3, -1, false) == 2);
	assert(wtwm_action_cycle_index(3, 2, true) == 0);
	assert(wtwm_action_cycle_index(3, 0, false) == 2);
	assert(wtwm_action_screen_target("next", 2, 1, 3) == 0);
	assert(wtwm_action_screen_target("prev", 0, 1, 3) == 2);
	assert(wtwm_action_screen_target("back", 0, 2, 3) == 2);
	assert(wtwm_action_screen_target("1", 0, 2, 3) == 1);
	assert(wtwm_action_screen_target("00", 2, 1, 3) == 0);
	assert(wtwm_action_screen_target("02", 0, 1, 3) == 2);
	assert(wtwm_action_screen_target("4", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target(NULL, 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("0", 0, 2, 0) == -1);
	assert(wtwm_action_screen_target("", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("-1", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("+1", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target(" 1", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("1 ", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("\t1", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("1x", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("x", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("999999999999999999999999999999999",
		0, 2, 3) == -1);
}

int main(void) {
	zoom_cases();
	navigation_cases();
	return 0;
}
