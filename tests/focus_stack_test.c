/* SPDX-License-Identifier: MIT */
#include "wtwm/config.h"
#include "wtwm/focus_stack.h"

#include <assert.h>
#include <stddef.h>

static void context_map_matches_twm(void) {
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_ROOT) ==
		WTWM_CONTEXT_ROOT);
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_FRAME) ==
		WTWM_CONTEXT_FRAME);
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_TITLE) ==
		WTWM_CONTEXT_TITLE);
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_CLIENT) ==
		WTWM_CONTEXT_WINDOW);
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_ICON) ==
		WTWM_CONTEXT_ICON);
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_ICON_MANAGER) ==
		WTWM_CONTEXT_ICONMGR);
	assert(wtwm_binding_context_for_surface(WTWM_FOCUS_SURFACE_MENU) == 0);
}

static void focus_enter_matches_title_and_protocol_rules(void) {
	struct wtwm_focus_enter_input input = {
		.focus_root = true,
		.surface = WTWM_FOCUS_SURFACE_FRAME,
		.title_focus = true,
		.has_title = true,
		.input_hint = true,
	};
	struct wtwm_focus_enter_result result = wtwm_focus_enter(&input);
	assert(result.activate && result.set_input_focus && !result.send_take_focus);
	input.take_focus = true;
	result = wtwm_focus_enter(&input);
	assert(result.activate && result.set_input_focus && result.send_take_focus);
	input.take_focus = false;
	input.title_focus = false;
	result = wtwm_focus_enter(&input);
	assert(result.activate && !result.set_input_focus && !result.send_take_focus);
	input.take_focus = true;
	result = wtwm_focus_enter(&input);
	assert(result.activate && !result.set_input_focus && result.send_take_focus);
	input.input_hint = false;
	result = wtwm_focus_enter(&input);
	/* A missing WM_HINTS has the same pointer-enter result as input=false. */
	assert(result.activate && !result.set_input_focus && result.send_take_focus);
	input.focus_root = false;
	result = wtwm_focus_enter(&input);
	assert(!result.activate && !result.set_input_focus && !result.send_take_focus);
	input.focus_root = true;
	input.surface = WTWM_FOCUS_SURFACE_CLIENT;
	result = wtwm_focus_enter(&input);
	assert(!result.activate && !result.set_input_focus && !result.send_take_focus);
	input.surface = WTWM_FOCUS_SURFACE_TITLE;
	result = wtwm_focus_enter(&input);
	assert(!result.activate && !result.set_input_focus && !result.send_take_focus);
	input.surface = WTWM_FOCUS_SURFACE_ICON_MANAGER;
	input.title_focus = true;
	input.input_hint = true;
	input.take_focus = false;
	input.has_title = false;
	result = wtwm_focus_enter(&input);
	assert(result.activate && !result.set_input_focus);
	input.global_no_titlebar = true;
	result = wtwm_focus_enter(&input);
	assert(result.activate && result.set_input_focus);
}

static void focus_toggle_matches_pointer_root_mode(void) {
	assert(wtwm_focus_toggle(true, false, false) == WTWM_FOCUS_CLICK_LOCKED);
	assert(wtwm_focus_toggle(false, true, false) == WTWM_FOCUS_POINTER_ROOT);
	assert(wtwm_focus_toggle(false, false, false) == WTWM_FOCUS_CLICK_LOCKED);
	assert(wtwm_focus_toggle(true, false, true) == WTWM_FOCUS_UNCHANGED);
}

static void focus_leave_preserves_no_title_focus_input(void) {
	struct wtwm_focus_leave_input input = {
		.focus_root = true,
		.surface = WTWM_FOCUS_SURFACE_FRAME,
		.title_focus = true,
	};
	struct wtwm_focus_leave_result result = wtwm_focus_leave(&input);
	assert(result.deactivate && result.set_pointer_root);
	input.title_focus = false;
	result = wtwm_focus_leave(&input);
	assert(result.deactivate && !result.set_pointer_root);
	input.take_focus = true;
	result = wtwm_focus_leave(&input);
	assert(result.deactivate && result.set_pointer_root);
	input.focus_root = false;
	result = wtwm_focus_leave(&input);
	assert(!result.deactivate && !result.set_pointer_root);
	input.focus_root = true;
	input.detail_inferior = true;
	result = wtwm_focus_leave(&input);
	assert(!result.deactivate && !result.set_pointer_root);
	input.detail_inferior = false;
	input.queued_match = true;
	result = wtwm_focus_leave(&input);
	assert(!result.deactivate && !result.set_pointer_root);
}

static void stacking_uses_actual_overlap(void) {
	struct wtwm_stack_box boxes[] = {
		{.x = 100, .y = 100, .width = 100, .height = 100, .visible = true},
		{.x = 150, .y = 150, .width = 100, .height = 100, .visible = true},
		{.x = 400, .y = 400, .width = 40, .height = 40, .visible = true},
		{.x = 175, .y = 175, .width = 25, .height = 25, .visible = true},
	};
	assert(!wtwm_stack_is_occluded(boxes, 4, 0));
	assert(wtwm_stack_is_occluded(boxes, 4, 1));
	assert(!wtwm_stack_is_occluded(boxes, 4, 2));
	assert(wtwm_stack_is_occluded(boxes, 4, 3));
	assert(wtwm_raise_lower_action(boxes, 4, 1, false) == WTWM_STACK_RAISE);
	assert(wtwm_raise_lower_action(boxes, 4, 0, false) == WTWM_STACK_LOWER);
	assert(wtwm_raise_lower_action(boxes, 4, 1, true) == WTWM_STACK_NONE);
	assert(wtwm_circle_up_candidate(boxes, 4) == 3);
	assert(wtwm_circle_down_candidate(boxes, 4) == 0);
	boxes[0].visible = false;
	assert(wtwm_circle_down_candidate(boxes, 4) == 1);
	struct wtwm_stack_box separate[] = {
		{.x = 0, .y = 0, .width = 20, .height = 20, .visible = true},
		{.x = 40, .y = 40, .width = 20, .height = 20, .visible = true},
	};
	assert(wtwm_circle_up_candidate(separate, 2) == -1);
	assert(wtwm_circle_down_candidate(separate, 2) == -1);
}

static void edge_contact_and_extreme_coordinates_do_not_overlap(void) {
	struct wtwm_stack_box first = {
		.x = 0, .y = 0, .width = 10, .height = 10, .visible = true,
	};
	struct wtwm_stack_box second = {
		.x = 10, .y = 0, .width = 10, .height = 10, .visible = true,
	};
	assert(!wtwm_stack_boxes_overlap(&first, &second));
	first.x = 2147483640;
	second.x = 2147483645;
	assert(wtwm_stack_boxes_overlap(&first, &second));
}

int main(void) {
	context_map_matches_twm();
	focus_enter_matches_title_and_protocol_rules();
	focus_toggle_matches_pointer_root_mode();
	focus_leave_preserves_no_title_focus_input();
	stacking_uses_actual_overlap();
	edge_contact_and_extreme_coordinates_do_not_overlap();
	return 0;
}
