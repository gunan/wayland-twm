/* SPDX-License-Identifier: MIT */

#include "wtwm/input_hotplug.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define ASSERT(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "assertion failed at %s:%d: %s\n", \
			__FILE__, __LINE__, #condition); \
		return false; \
	} \
} while (0)

static bool apply(struct wtwm_input_hotplug_state *state,
		const struct wtwm_input_hotplug_plan *plan) {
	ASSERT(plan->built);
	ASSERT(wtwm_input_hotplug_plan_apply(state, plan));
	ASSERT(wtwm_input_hotplug_state_valid(state));
	return true;
}

static bool add(struct wtwm_input_hotplug_state *state, const char *name,
		enum wtwm_input_device_type type, uint64_t *ordinal) {
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_add(state, name, type, &plan));
	if (ordinal != NULL) *ordinal = plan.device_ordinal;
	return apply(state, &plan);
}

static const struct wtwm_input_hotplug_device *device(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal) {
	for (size_t index = 0; index < state->device_count; ++index) {
		if (state->devices[index].ordinal == ordinal) return &state->devices[index];
	}
	return NULL;
}

static bool test_initial_state_and_add_order(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	ASSERT(wtwm_input_hotplug_state_valid(&state));
	ASSERT(sizeof(state) <= WTWM_INPUT_HOTPLUG_STATE_MAX_BYTES);
	ASSERT(sizeof(struct wtwm_input_hotplug_plan) <=
		WTWM_INPUT_HOTPLUG_PLAN_MAX_BYTES);
	state.keyboard_focus_valid = true;
	state.keyboard_focus = UINT64_C(0x1234);
	state.cursor_x = -45.5;
	state.cursor_y = 98.25;

	uint64_t keyboard_a = 0, keyboard_b = 0, pointer_a = 0, pointer_b = 0;
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_add(&state, "keyboard-z",
		WTWM_INPUT_DEVICE_KEYBOARD, &plan));
	keyboard_a = plan.device_ordinal;
	ASSERT(plan.capabilities_before == 0);
	ASSERT(plan.capabilities_after == WTWM_INPUT_CAPABILITY_KEYBOARD);
	ASSERT(plan.capabilities_changed && plan.active_keyboard_changed);
	ASSERT(plan.reassert_keyboard_focus);
	ASSERT(apply(&state, &plan));

	ASSERT(add(&state, "keyboard-a", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_b));
	ASSERT(state.active_keyboard == keyboard_a);
	ASSERT(add(&state, "pointer-z", WTWM_INPUT_DEVICE_POINTER, &pointer_a));
	ASSERT(add(&state, "pointer-a", WTWM_INPUT_DEVICE_POINTER, &pointer_b));
	ASSERT(state.active_pointer == pointer_a);
	ASSERT(state.device_count == 4 && state.keyboard_count == 2 &&
		state.pointer_count == 2);
	ASSERT(state.capabilities == (WTWM_INPUT_CAPABILITY_KEYBOARD |
		WTWM_INPUT_CAPABILITY_POINTER));
	ASSERT(keyboard_a < keyboard_b && keyboard_b < pointer_a &&
		pointer_a < pointer_b);
	ASSERT(strcmp(state.devices[0].name, "keyboard-z") == 0);
	ASSERT(strcmp(state.devices[1].name, "keyboard-a") == 0);
	ASSERT(state.keyboard_focus_valid && state.keyboard_focus == UINT64_C(0x1234));
	ASSERT(state.cursor_x == -45.5 && state.cursor_y == 98.25);
	return true;
}

static bool test_activity_and_fallback(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t keyboard_a = 0, keyboard_b = 0, keyboard_c = 0;
	ASSERT(add(&state, "ka", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_a));
	ASSERT(add(&state, "kb", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_b));
	ASSERT(add(&state, "kc", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_c));

	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	struct wtwm_input_modifiers modifiers = {
		.depressed = 1,
		.latched = 2,
		.locked = 4,
		.group = 3,
	};
	ASSERT(wtwm_input_hotplug_plan_modifiers(&state, keyboard_b, modifiers, &plan));
	ASSERT(plan.active_keyboard_changed);
	ASSERT(plan.key_transition_count == 0 && !plan.recompute_seat_modifiers);
	ASSERT(apply(&state, &plan));
	ASSERT(state.active_keyboard == keyboard_b);
	ASSERT(device(&state, keyboard_b)->last_activity == 1);
	ASSERT(device(&state, keyboard_b)->modifiers.group == 3);

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_a, 44, false,
		&plan));
	ASSERT(plan.active_keyboard_changed && plan.key_transition_count == 0);
	ASSERT(apply(&state, &plan));
	ASSERT(state.active_keyboard == keyboard_a);
	ASSERT(device(&state, keyboard_a)->last_activity == 2);

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, keyboard_a, &plan));
	ASSERT(plan.active_keyboard_changed && plan.reassert_keyboard_focus);
	ASSERT(plan.key_transition_count == 0);
	ASSERT(plan.next.active_keyboard == keyboard_b);
	ASSERT(apply(&state, &plan));
	ASSERT(state.active_keyboard == keyboard_b);

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, keyboard_b, &plan));
	ASSERT(plan.next.active_keyboard == keyboard_c);
	ASSERT(apply(&state, &plan));
	ASSERT(state.active_keyboard == keyboard_c);

	struct wtwm_input_hotplug_state ties;
	wtwm_input_hotplug_state_init(&ties);
	uint64_t first = 0, second = 0, third = 0;
	ASSERT(add(&ties, "first", WTWM_INPUT_DEVICE_KEYBOARD, &first));
	ASSERT(add(&ties, "second", WTWM_INPUT_DEVICE_KEYBOARD, &second));
	ASSERT(add(&ties, "third", WTWM_INPUT_DEVICE_KEYBOARD, &third));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&ties, first, &plan));
	ASSERT(plan.next.active_keyboard == second);
	ASSERT(apply(&ties, &plan));
	ASSERT(ties.active_keyboard == second && second < third);
	return true;
}

static bool test_key_ownership_and_drains(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t keyboard_a = 0, keyboard_b = 0;
	ASSERT(add(&state, "ka", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_a));
	ASSERT(add(&state, "kb", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_b));
	struct wtwm_input_hotplug_plan plan;

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_a, 30, true,
		&plan));
	ASSERT(plan.key_transition_count == 1);
	ASSERT(plan.key_transitions[0].code == 30 &&
		plan.key_transitions[0].pressed);
	ASSERT(plan.recompute_seat_modifiers);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_b, 30, true,
		&plan));
	ASSERT(plan.key_transition_count == 0);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_a, 31, false,
		&plan));
	ASSERT(plan.key_transition_count == 0);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, keyboard_a, &plan));
	ASSERT(plan.key_transition_count == 0);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_release(&state, keyboard_b, 30, &plan));
	ASSERT(plan.key_transition_count == 1);
	ASSERT(plan.key_transitions[0].code == 30 &&
		!plan.key_transitions[0].pressed);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	struct wtwm_input_hotplug_plan plan_before = plan;
	struct wtwm_input_hotplug_state state_before = state;
	ASSERT(!wtwm_input_hotplug_plan_key_release(&state, keyboard_b, 30, &plan));
	ASSERT(memcmp(&plan, &plan_before, sizeof(plan)) == 0);
	ASSERT(memcmp(&state, &state_before, sizeof(state)) == 0);

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_b, 55, false,
		&plan));
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_release(&state, keyboard_b, 55, &plan));
	ASSERT(plan.key_transition_count == 0);
	ASSERT(apply(&state, &plan));
	return true;
}

static bool test_visible_and_binding_holders_are_independent(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t visible = 0, binding = 0;
	ASSERT(add(&state, "visible", WTWM_INPUT_DEVICE_KEYBOARD, &visible));
	ASSERT(add(&state, "binding", WTWM_INPUT_DEVICE_KEYBOARD, &binding));
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, visible, 77, true, &plan));
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, binding, 77, false, &plan));
	ASSERT(plan.key_transition_count == 0);
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, visible, &plan));
	ASSERT(plan.key_transition_count == 1 &&
		plan.key_transitions[0].code == 77 &&
		!plan.key_transitions[0].pressed);
	ASSERT(apply(&state, &plan));
	ASSERT(device(&state, binding)->key_count == 1);
	return true;
}

static bool test_pointer_aggregation_and_last_removal(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	state.keyboard_focus_valid = true;
	state.keyboard_focus = 900;
	uint64_t pointer_a = 0, pointer_b = 0;
	ASSERT(add(&state, "pa", WTWM_INPUT_DEVICE_POINTER, &pointer_a));
	ASSERT(add(&state, "pb", WTWM_INPUT_DEVICE_POINTER, &pointer_b));
	state.pointer_focus_valid = true;
	state.pointer_focus = 700;
	state.cursor_x = -123.75;
	state.cursor_y = 456.5;
	ASSERT(wtwm_input_hotplug_state_valid(&state));

	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_press(&state, pointer_a, 272, true,
		&plan));
	ASSERT(plan.button_transition_count == 1 &&
		plan.button_transitions[0].pressed);
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_press(&state, pointer_b, 272, true,
		&plan));
	ASSERT(plan.button_transition_count == 0);
	ASSERT(apply(&state, &plan));
	state.pointer_operation = WTWM_INPUT_POINTER_MOVE;
	state.pointer_operation_button_valid = true;
	state.pointer_operation_button = 272;
	ASSERT(wtwm_input_hotplug_state_valid(&state));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, pointer_a, &plan));
	ASSERT(plan.button_transition_count == 0);
	ASSERT(!plan.clear_pointer_focus && !plan.abort_move_resize);
	ASSERT(plan.next.pointer_focus_valid && plan.next.pointer_focus == 700);
	ASSERT(plan.next.pointer_operation == WTWM_INPUT_POINTER_MOVE);
	ASSERT(plan.next.pointer_operation_button_valid &&
		plan.next.pointer_operation_button == 272);
	ASSERT(plan.next.cursor_x == -123.75 && plan.next.cursor_y == 456.5);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, pointer_b, &plan));
	ASSERT(plan.button_transition_count == 1);
	ASSERT(plan.button_transitions[0].code == 272 &&
		!plan.button_transitions[0].pressed);
	ASSERT(plan.clear_pointer_focus && plan.abort_move_resize);
	ASSERT(!plan.close_menu && !plan.cancel_deferred_action &&
		!plan.requeue_initial_placement);
	ASSERT(!plan.next.pointer_focus_valid);
	ASSERT(plan.next.pointer_operation == WTWM_INPUT_POINTER_IDLE);
	ASSERT(plan.next.cursor_x == -123.75 && plan.next.cursor_y == 456.5);
	ASSERT(plan.next.keyboard_focus_valid && plan.next.keyboard_focus == 900);
	ASSERT(apply(&state, &plan));

	uint64_t returned = 0;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_add(&state, "returned",
		WTWM_INPUT_DEVICE_POINTER, &plan));
	returned = plan.device_ordinal;
	ASSERT(plan.refresh_pointer_focus && plan.active_pointer_changed);
	ASSERT(plan.next.cursor_x == -123.75 && plan.next.cursor_y == 456.5);
	ASSERT(!plan.next.pointer_focus_valid);
	ASSERT(apply(&state, &plan));
	ASSERT(state.active_pointer == returned);
	return true;
}

static bool test_surviving_pointer_required_button_repair(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t pointer_a = 0, pointer_b = 0;
	ASSERT(add(&state, "pa", WTWM_INPUT_DEVICE_POINTER, &pointer_a));
	ASSERT(add(&state, "pb", WTWM_INPUT_DEVICE_POINTER, &pointer_b));
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_press(&state, pointer_a, 272, false,
		&plan));
	ASSERT(plan.button_transition_count == 0);
	ASSERT(apply(&state, &plan));
	state.pointer_focus_valid = true;
	state.pointer_focus = 81;
	state.pointer_operation = WTWM_INPUT_POINTER_RESIZE;
	state.pointer_operation_button_valid = true;
	state.pointer_operation_button = 272;
	ASSERT(wtwm_input_hotplug_state_valid(&state));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, pointer_a, &plan));
	ASSERT(plan.next.pointer_count == 1);
	ASSERT(plan.abort_move_resize);
	ASSERT(!plan.clear_pointer_focus && plan.next.pointer_focus_valid &&
		plan.next.pointer_focus == 81);
	ASSERT(plan.button_transition_count == 0);
	ASSERT(plan.next.pointer_operation == WTWM_INPUT_POINTER_IDLE);
	ASSERT(!plan.next.pointer_operation_button_valid);
	ASSERT(apply(&state, &plan));

	struct wtwm_input_hotplug_state placement;
	wtwm_input_hotplug_state_init(&placement);
	ASSERT(add(&placement, "p1", WTWM_INPUT_DEVICE_POINTER, &pointer_a));
	ASSERT(add(&placement, "p2", WTWM_INPUT_DEVICE_POINTER, &pointer_b));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_press(&placement, pointer_a, 273,
		true, &plan));
	ASSERT(apply(&placement, &plan));
	placement.pointer_operation = WTWM_INPUT_POINTER_INITIAL_PLACEMENT;
	placement.pointer_operation_button_valid = true;
	placement.pointer_operation_button = 273;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&placement, pointer_a, &plan));
	ASSERT(plan.requeue_initial_placement && !plan.clear_pointer_focus);
	ASSERT(plan.button_transition_count == 1 &&
		plan.button_transitions[0].code == 273 &&
		!plan.button_transitions[0].pressed);
	ASSERT(apply(&placement, &plan));
	return true;
}

static bool test_pointer_operation_flags(void) {
	const enum wtwm_input_pointer_operation operations[] = {
		WTWM_INPUT_POINTER_MENU,
		WTWM_INPUT_POINTER_DEFERRED_ACTION,
		WTWM_INPUT_POINTER_RESIZE,
		WTWM_INPUT_POINTER_INITIAL_PLACEMENT,
	};
	for (size_t index = 0; index < sizeof(operations) / sizeof(operations[0]);
			++index) {
		struct wtwm_input_hotplug_state state;
		wtwm_input_hotplug_state_init(&state);
		uint64_t pointer = 0;
		ASSERT(add(&state, "pointer", WTWM_INPUT_DEVICE_POINTER, &pointer));
		state.pointer_operation = operations[index];
		struct wtwm_input_hotplug_plan plan;
		wtwm_input_hotplug_plan_init(&plan);
		ASSERT(wtwm_input_hotplug_plan_remove(&state, pointer, &plan));
		ASSERT(plan.clear_pointer_focus);
		ASSERT(plan.close_menu == (operations[index] == WTWM_INPUT_POINTER_MENU));
		ASSERT(plan.cancel_deferred_action ==
			(operations[index] == WTWM_INPUT_POINTER_DEFERRED_ACTION));
		ASSERT(plan.abort_move_resize ==
			(operations[index] == WTWM_INPUT_POINTER_RESIZE));
		ASSERT(plan.requeue_initial_placement ==
			(operations[index] == WTWM_INPUT_POINTER_INITIAL_PLACEMENT));
		ASSERT(apply(&state, &plan));
	}
	return true;
}

static bool test_motion_active_pointer_and_validation(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t pointer_a = 0, pointer_b = 0;
	ASSERT(add(&state, "pa", WTWM_INPUT_DEVICE_POINTER, &pointer_a));
	ASSERT(add(&state, "pb", WTWM_INPUT_DEVICE_POINTER, &pointer_b));
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_pointer_motion(&state, pointer_b,
		-1000.25, 2000.75, &plan));
	ASSERT(plan.active_pointer_changed);
	ASSERT(plan.next.cursor_x == -1000.25 && plan.next.cursor_y == 2000.75);
	ASSERT(apply(&state, &plan));
	ASSERT(state.active_pointer == pointer_b);

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_press(&state, pointer_a, 400, false,
		&plan));
	ASSERT(plan.active_pointer_changed && plan.button_transition_count == 0);
	ASSERT(apply(&state, &plan));
	state.pointer_operation = WTWM_INPUT_POINTER_MOVE;
	ASSERT(wtwm_input_hotplug_state_valid(&state));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_release(&state, pointer_a, 400,
		&plan));
	ASSERT(plan.button_transition_count == 0);
	ASSERT(apply(&state, &plan));
	ASSERT(device(&state, pointer_a)->button_count == 0);
	ASSERT(state.pointer_operation == WTWM_INPUT_POINTER_MOVE);
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_remove(&state, pointer_a, &plan));
	ASSERT(plan.active_pointer_changed);
	ASSERT(plan.next.active_pointer == pointer_b);
	ASSERT(!plan.clear_pointer_focus);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	struct wtwm_input_hotplug_plan before = plan;
	ASSERT(!wtwm_input_hotplug_plan_pointer_motion(&state, pointer_b,
		NAN, 1.0, &plan));
	ASSERT(memcmp(&plan, &before, sizeof(plan)) == 0);
	ASSERT(!wtwm_input_hotplug_plan_pointer_motion(&state, pointer_b,
		1.0, INFINITY, &plan));
	ASSERT(memcmp(&plan, &before, sizeof(plan)) == 0);
	return true;
}

static bool test_clear_unique_transitions_and_continuity(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	state.keyboard_focus_valid = true;
	state.keyboard_focus = 42;
	uint64_t keyboard_a = 0, keyboard_b = 0, pointer = 0;
	ASSERT(add(&state, "ka", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_a));
	ASSERT(add(&state, "kb", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_b));
	ASSERT(add(&state, "pointer", WTWM_INPUT_DEVICE_POINTER, &pointer));
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_a, 90, true,
		&plan));
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_b, 90, true,
		&plan));
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_a, 10, true,
		&plan));
	ASSERT(apply(&state, &plan));
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_button_press(&state, pointer, 273, true,
		&plan));
	ASSERT(apply(&state, &plan));
	state.pointer_focus_valid = true;
	state.pointer_focus = 7;
	state.cursor_x = 11.5;
	state.cursor_y = -12.5;
	state.pointer_operation = WTWM_INPUT_POINTER_DEFERRED_ACTION;
	uint64_t next_ordinal = state.next_ordinal;
	uint64_t next_activity = state.next_activity;

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_clear(&state, &plan));
	ASSERT(plan.key_transition_count == 2);
	ASSERT(plan.key_transitions[0].code == 10 &&
		plan.key_transitions[1].code == 90);
	ASSERT(!plan.key_transitions[0].pressed &&
		!plan.key_transitions[1].pressed);
	ASSERT(plan.button_transition_count == 1 &&
		plan.button_transitions[0].code == 273);
	ASSERT(plan.clear_pointer_focus && plan.cancel_deferred_action);
	ASSERT(plan.next.next_ordinal == next_ordinal);
	ASSERT(plan.next.next_activity == next_activity);
	ASSERT(plan.next.keyboard_focus_valid && plan.next.keyboard_focus == 42);
	ASSERT(plan.next.cursor_x == 11.5 && plan.next.cursor_y == -12.5);
	ASSERT(apply(&state, &plan));
	ASSERT(state.device_count == 0 && state.capabilities == 0);

	uint64_t replacement = 0;
	ASSERT(add(&state, "replacement", WTWM_INPUT_DEVICE_KEYBOARD,
		&replacement));
	ASSERT(replacement == next_ordinal);
	ASSERT(state.next_activity == next_activity);
	return true;
}

static bool test_activity_overflow_renormalizes(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t keyboard_a = 0, keyboard_b = 0, pointer = 0;
	ASSERT(add(&state, "ka", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_a));
	ASSERT(add(&state, "kb", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard_b));
	ASSERT(add(&state, "pointer", WTWM_INPUT_DEVICE_POINTER, &pointer));
	state.devices[0].last_activity = UINT64_MAX - 2;
	state.devices[1].last_activity = UINT64_MAX - 1;
	state.devices[2].last_activity = 0;
	state.next_activity = UINT64_MAX;
	state.active_keyboard_valid = true;
	state.active_keyboard = keyboard_b;
	state.active_pointer_valid = true;
	state.active_pointer = pointer;
	ASSERT(wtwm_input_hotplug_state_valid(&state));

	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_pointer_motion(&state, pointer, 1.0, 2.0,
		&plan));
	ASSERT(device(&plan.next, keyboard_a)->last_activity == 1);
	ASSERT(device(&plan.next, keyboard_b)->last_activity == 2);
	ASSERT(device(&plan.next, pointer)->last_activity == 3);
	ASSERT(plan.next.next_activity == 4);
	ASSERT(plan.next.active_keyboard == keyboard_b);
	ASSERT(apply(&state, &plan));

	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&state, keyboard_a, 1, false,
		&plan));
	ASSERT(device(&plan.next, keyboard_a)->last_activity == 4);
	ASSERT(plan.next.next_activity == 5);
	ASSERT(plan.next.active_keyboard == keyboard_a);
	ASSERT(apply(&state, &plan));
	return true;
}

static bool test_capacity_and_ordinal_overflow(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	char name[32];
	uint64_t first = 0;
	for (size_t index = 0; index < WTWM_INPUT_MAX_DEVICES; ++index) {
		(void)snprintf(name, sizeof(name), "keyboard-%zu", index);
		uint64_t ordinal = 0;
		ASSERT(add(&state, name, WTWM_INPUT_DEVICE_KEYBOARD, &ordinal));
		if (index == 0) first = ordinal;
	}
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	struct wtwm_input_hotplug_plan plan_before = plan;
	ASSERT(!wtwm_input_hotplug_plan_add(&state, "overflow",
		WTWM_INPUT_DEVICE_KEYBOARD, &plan));
	ASSERT(memcmp(&plan, &plan_before, sizeof(plan)) == 0);

	for (size_t code = 0; code < WTWM_INPUT_MAX_HELD_KEYS; ++code) {
		wtwm_input_hotplug_plan_init(&plan);
		ASSERT(wtwm_input_hotplug_plan_key_press(&state, first,
			(uint32_t)code, false, &plan));
		ASSERT(apply(&state, &plan));
	}
	wtwm_input_hotplug_plan_init(&plan);
	plan_before = plan;
	ASSERT(!wtwm_input_hotplug_plan_key_press(&state, first, 999, false,
		&plan));
	ASSERT(memcmp(&plan, &plan_before, sizeof(plan)) == 0);

	struct wtwm_input_hotplug_state exhausted;
	wtwm_input_hotplug_state_init(&exhausted);
	exhausted.next_ordinal = UINT64_MAX;
	ASSERT(wtwm_input_hotplug_state_valid(&exhausted));
	wtwm_input_hotplug_plan_init(&plan);
	plan_before = plan;
	ASSERT(!wtwm_input_hotplug_plan_add(&exhausted, "never",
		WTWM_INPUT_DEVICE_POINTER, &plan));
	ASSERT(memcmp(&plan, &plan_before, sizeof(plan)) == 0);
	return true;
}

static bool test_invalid_inputs_are_atomic(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	uint64_t keyboard = 0;
	ASSERT(add(&state, "keyboard", WTWM_INPUT_DEVICE_KEYBOARD, &keyboard));
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	struct wtwm_input_hotplug_plan plan_before = plan;
	struct wtwm_input_hotplug_state state_before = state;
	ASSERT(!wtwm_input_hotplug_plan_add(&state, "keyboard",
		WTWM_INPUT_DEVICE_POINTER, &plan));
	ASSERT(!wtwm_input_hotplug_plan_add(&state, "",
		WTWM_INPUT_DEVICE_POINTER, &plan));
	ASSERT(!wtwm_input_hotplug_plan_add(&state, NULL,
		WTWM_INPUT_DEVICE_POINTER, &plan));
	ASSERT(!wtwm_input_hotplug_plan_remove(&state, UINT64_C(9999), &plan));
	ASSERT(!wtwm_input_hotplug_plan_button_press(&state, keyboard, 1, true,
		&plan));
	ASSERT(memcmp(&plan, &plan_before, sizeof(plan)) == 0);
	ASSERT(memcmp(&state, &state_before, sizeof(state)) == 0);

	char unterminated[WTWM_INPUT_NAME_MAX];
	memset(unterminated, 'x', sizeof(unterminated));
	ASSERT(!wtwm_input_hotplug_plan_add(&state, unterminated,
		WTWM_INPUT_DEVICE_POINTER, &plan));
	ASSERT(memcmp(&plan, &plan_before, sizeof(plan)) == 0);

	struct wtwm_input_hotplug_state invalid = state;
	invalid.capabilities = 0;
	ASSERT(!wtwm_input_hotplug_state_valid(&invalid));
	invalid = state;
	invalid.next_activity = 0;
	ASSERT(!wtwm_input_hotplug_state_valid(&invalid));
	invalid = state;
	invalid.cursor_x = NAN;
	ASSERT(!wtwm_input_hotplug_state_valid(&invalid));
	invalid = state;
	invalid.active_keyboard = UINT64_C(999);
	ASSERT(!wtwm_input_hotplug_state_valid(&invalid));
	invalid = state;
	invalid.devices[0].name[0] = '\0';
	ASSERT(!wtwm_input_hotplug_state_valid(&invalid));
	invalid = state;
	invalid.devices[0].button_count = 1;
	ASSERT(!wtwm_input_hotplug_state_valid(&invalid));
	return true;
}

static bool test_stale_plan_and_restart_copy(void) {
	struct wtwm_input_hotplug_state state;
	wtwm_input_hotplug_state_init(&state);
	state.keyboard_focus_valid = true;
	state.keyboard_focus = 123;
	state.cursor_x = 4.25;
	state.cursor_y = -8.5;
	struct wtwm_input_hotplug_plan plan;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_add(&state, "keyboard",
		WTWM_INPUT_DEVICE_KEYBOARD, &plan));
	struct wtwm_input_hotplug_plan saved_plan = plan;
	ASSERT(apply(&state, &plan));
	struct wtwm_input_hotplug_state applied = state;
	ASSERT(!wtwm_input_hotplug_plan_apply(&state, &saved_plan));
	ASSERT(memcmp(&state, &applied, sizeof(state)) == 0);
	ASSERT(!wtwm_input_hotplug_plan_add(&state, "pointer",
		WTWM_INPUT_DEVICE_POINTER, &plan));
	ASSERT(memcmp(&plan, &saved_plan, sizeof(plan)) == 0);

	struct wtwm_input_hotplug_state retained = state;
	uint64_t keyboard = state.active_keyboard;
	wtwm_input_hotplug_plan_init(&plan);
	ASSERT(wtwm_input_hotplug_plan_key_press(&retained, keyboard, 12, true,
		&plan));
	ASSERT(plan.next.keyboard_focus == 123);
	ASSERT(plan.next.cursor_x == 4.25 && plan.next.cursor_y == -8.5);
	ASSERT(apply(&retained, &plan));
	ASSERT(device(&retained, keyboard)->key_count == 1);
	ASSERT(device(&state, keyboard)->key_count == 0);
	ASSERT(state.next_ordinal == retained.next_ordinal);
	return true;
}

int main(void) {
	if (!test_initial_state_and_add_order() ||
			!test_activity_and_fallback() ||
			!test_key_ownership_and_drains() ||
			!test_visible_and_binding_holders_are_independent() ||
			!test_pointer_aggregation_and_last_removal() ||
			!test_surviving_pointer_required_button_repair() ||
			!test_pointer_operation_flags() ||
			!test_motion_active_pointer_and_validation() ||
			!test_clear_unique_transitions_and_continuity() ||
			!test_activity_overflow_renormalizes() ||
			!test_capacity_and_ordinal_overflow() ||
			!test_invalid_inputs_are_atomic() ||
			!test_stale_plan_and_restart_copy()) return 1;
	return 0;
}
