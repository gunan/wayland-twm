/* SPDX-License-Identifier: MIT */
#include <wtwm/actions.h>

#include <assert.h>
#include <limits.h>
#include <string.h>

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
	assert(wtwm_action_screen_target("NEXT", 0, 2, 3) == 1);
	assert(wtwm_action_screen_target("nExT", 2, 0, 3) == 0);
	assert(wtwm_action_screen_target("PrEv", 0, 1, 3) == 2);
	assert(wtwm_action_screen_target("BaCk", 0, 2, 3) == 2);
	assert(wtwm_action_screen_target("previous", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("ne" "\xc3\xa9" "xt", 0, 2, 3) == -1);
	assert(wtwm_action_screen_target("back", 0, -1, 3) == 0);
	assert(wtwm_action_screen_target("next", -1, 0, 3) == -1);
	assert(wtwm_action_screen_target("prev", 3, 0, 3) == -1);
	assert(wtwm_action_screen_target("next", INT_MAX, 0, INT_MAX) == -1);
	assert(wtwm_action_screen_target("prev", INT_MIN, 0, INT_MAX) == -1);
}

static void assert_state_unchanged(struct wtwm_screen_warp_state before,
		const struct wtwm_screen_warp_state *after) {
	assert(memcmp(&before, after, sizeof(before)) == 0);
}

static void screen_warp_plan_cases(void) {
	const struct wtwm_interaction_box outputs[] = {
		{10, 20, 100, 80},
		{1000, -100, 50, 40},
		{-500, 400, 200, 100},
	};
	struct wtwm_screen_warp_state state;
	struct wtwm_screen_warp_plan plan;
	wtwm_action_screen_warp_init(&state);
	assert(state.previous == -1);
	wtwm_action_screen_warp_init(NULL);

	assert(wtwm_action_plan_screen_warp("1", 0, 3, outputs, 42, 30,
		&state, &plan));
	assert(plan.source == 0 && plan.target == 1);
	assert(plan.x == 1032 && plan.y == -90);
	assert(state.previous == 0);

	/* Successful back operations exchange current and previous outputs. */
	assert(wtwm_action_plan_screen_warp("BaCk", 1, 3, outputs,
		plan.x, plan.y, &state, &plan));
	assert(plan.source == 1 && plan.target == 0);
	assert(plan.x == 42 && plan.y == 30 && state.previous == 1);
	assert(wtwm_action_plan_screen_warp("bACK", 0, 3, outputs,
		plan.x, plan.y, &state, &plan));
	assert(plan.source == 0 && plan.target == 1);
	assert(plan.x == 1032 && plan.y == -90 && state.previous == 0);

	assert(wtwm_action_plan_screen_warp("NeXt", 2, 3, outputs,
		-450, 450, &state, &plan));
	assert(plan.source == 2 && plan.target == 0);
	assert(plan.x == 60 && plan.y == 70 && state.previous == 2);
	assert(wtwm_action_plan_screen_warp("pReV", 0, 3, outputs,
		60, 70, &state, &plan));
	assert(plan.source == 0 && plan.target == 2);
	assert(plan.x == -450 && plan.y == 450 && state.previous == 0);
}

static void screen_warp_noop_cases(void) {
	struct wtwm_interaction_box outputs[] = {
		{0, 0, 100, 100},
		{100, 0, 100, 100},
		{200, 0, 100, 100},
	};
	struct wtwm_screen_warp_state state = {.previous = 1};
	struct wtwm_screen_warp_plan plan;
	struct wtwm_screen_warp_state before = state;

#define ASSERT_NO_WARP(argument, current, count, boxes) do { \
	assert(!wtwm_action_plan_screen_warp((argument), (current), (count), \
		(boxes), 25, 25, &state, &plan)); \
	assert(plan.source == -1 && plan.target == -1); \
	assert(plan.x == 25 && plan.y == 25); \
	assert_state_unchanged(before, &state); \
} while (0)

	ASSERT_NO_WARP("0", 0, 2, outputs);
	ASSERT_NO_WARP("back", 1, 2, outputs);
	ASSERT_NO_WARP("next", 0, 1, outputs);
	ASSERT_NO_WARP("next", -1, 2, outputs);
	ASSERT_NO_WARP("next", 2, 2, outputs);
	ASSERT_NO_WARP("2", 0, 2, outputs);
	ASSERT_NO_WARP("previous", 0, 2, outputs);
	ASSERT_NO_WARP(NULL, 0, 2, outputs);
	ASSERT_NO_WARP("next", 0, 0, outputs);
	ASSERT_NO_WARP("next", 0, 2, NULL);

	outputs[0].width = 0;
	ASSERT_NO_WARP("next", 0, 2, outputs);
	outputs[0].width = 100;
	outputs[1].height = -1;
	ASSERT_NO_WARP("next", 0, 2, outputs);
	outputs[1].height = 100;
	outputs[2].width = 0;
	ASSERT_NO_WARP("next", 0, 3, outputs);
	outputs[2].width = 100;
	assert(!wtwm_action_plan_screen_warp("next", 0, 2, outputs,
		25, 25, NULL, &plan));
	assert(!wtwm_action_plan_screen_warp("next", 0, 2, outputs,
		25, 25, &state, NULL));
	assert_state_unchanged(before, &state);

#undef ASSERT_NO_WARP
}

static void screen_warp_boundary_cases(void) {
	struct wtwm_screen_warp_state state = {.previous = -1};
	struct wtwm_screen_warp_plan plan;
	const struct wtwm_interaction_box lower[] = {
		{INT_MAX, INT_MAX, 1, 1},
		{INT_MIN, INT_MIN, INT_MAX, INT_MAX},
	};
	assert(wtwm_action_plan_screen_warp("next", 0, 2, lower,
		INT_MIN, INT_MIN, &state, &plan));
	assert(plan.x == INT_MIN && plan.y == INT_MIN);

	const struct wtwm_interaction_box upper[] = {
		{INT_MIN, INT_MIN, 1, 1},
		{INT_MAX, INT_MAX, INT_MAX, INT_MAX},
	};
	assert(wtwm_action_plan_screen_warp("next", 0, 2, upper,
		INT_MAX, INT_MAX, &state, &plan));
	assert(plan.x == INT_MAX && plan.y == INT_MAX);

	const struct wtwm_interaction_box clamp[] = {
		{0, 0, 10, 10},
		{INT_MAX, INT_MIN, 1, 1},
	};
	assert(wtwm_action_plan_screen_warp("next", 0, 2, clamp,
		INT_MIN, INT_MAX, &state, &plan));
	assert(plan.x == INT_MAX && plan.y == INT_MIN);
}

int main(void) {
	zoom_cases();
	navigation_cases();
	screen_warp_plan_cases();
	screen_warp_noop_cases();
	screen_warp_boundary_cases();
	return 0;
}
