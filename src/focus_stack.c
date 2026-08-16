/* SPDX-License-Identifier: MIT */
#include "wtwm/focus_stack.h"

#include "wtwm/config.h"

#include <limits.h>

uint32_t wtwm_binding_context_for_surface(enum wtwm_focus_surface surface) {
	switch (surface) {
	case WTWM_FOCUS_SURFACE_ROOT: return WTWM_CONTEXT_ROOT;
	case WTWM_FOCUS_SURFACE_FRAME: return WTWM_CONTEXT_FRAME;
	case WTWM_FOCUS_SURFACE_TITLE: return WTWM_CONTEXT_TITLE;
	case WTWM_FOCUS_SURFACE_CLIENT: return WTWM_CONTEXT_WINDOW;
	case WTWM_FOCUS_SURFACE_ICON: return WTWM_CONTEXT_ICON;
	case WTWM_FOCUS_SURFACE_ICON_MANAGER: return WTWM_CONTEXT_ICONMGR;
	case WTWM_FOCUS_SURFACE_MENU: return 0;
	}
	return 0;
}

struct wtwm_focus_enter_result wtwm_focus_enter(
		const struct wtwm_focus_enter_input *input) {
	struct wtwm_focus_enter_result result = {0};
	if (input == NULL || !input->focus_root) return result;
	if (input->surface != WTWM_FOCUS_SURFACE_FRAME &&
			input->surface != WTWM_FOCUS_SURFACE_ICON_MANAGER) return result;
	result.activate = true;
	result.set_input_focus = input->input_hint && input->title_focus &&
		(input->has_title || input->global_no_titlebar);
	result.send_take_focus = input->take_focus;
	return result;
}

struct wtwm_focus_leave_result wtwm_focus_leave(
		const struct wtwm_focus_leave_input *input) {
	struct wtwm_focus_leave_result result = {0};
	if (input == NULL || !input->focus_root || input->detail_inferior ||
			input->queued_match ||
			(input->surface != WTWM_FOCUS_SURFACE_FRAME &&
			input->surface != WTWM_FOCUS_SURFACE_ICON_MANAGER)) return result;
	result.deactivate = true;
	result.set_pointer_root = input->title_focus || input->take_focus;
	return result;
}

enum wtwm_focus_toggle_result wtwm_focus_toggle(bool focus_root,
		bool selected_is_current, bool iconified) {
	if (iconified) return WTWM_FOCUS_UNCHANGED;
	if (!focus_root && selected_is_current) return WTWM_FOCUS_POINTER_ROOT;
	return WTWM_FOCUS_CLICK_LOCKED;
}

static long long box_right(const struct wtwm_stack_box *box) {
	return (long long)box->x + box->width;
}

static long long box_bottom(const struct wtwm_stack_box *box) {
	return (long long)box->y + box->height;
}

bool wtwm_stack_boxes_overlap(const struct wtwm_stack_box *first,
		const struct wtwm_stack_box *second) {
	if (first == NULL || second == NULL || !first->visible || !second->visible ||
			first->width <= 0 || first->height <= 0 ||
			second->width <= 0 || second->height <= 0) return false;
	return (long long)first->x < box_right(second) &&
		(long long)second->x < box_right(first) &&
		(long long)first->y < box_bottom(second) &&
		(long long)second->y < box_bottom(first);
}

bool wtwm_stack_is_occluded(const struct wtwm_stack_box *top_to_bottom,
		size_t count, size_t index) {
	if (top_to_bottom == NULL || index >= count ||
			!top_to_bottom[index].visible) return false;
	for (size_t above = 0; above < index; ++above)
		if (wtwm_stack_boxes_overlap(&top_to_bottom[index],
				&top_to_bottom[above])) return true;
	return false;
}

enum wtwm_stack_action wtwm_raise_lower_action(
		const struct wtwm_stack_box *top_to_bottom, size_t count, size_t index,
		bool window_moved) {
	if (window_moved || top_to_bottom == NULL || index >= count ||
			!top_to_bottom[index].visible) return WTWM_STACK_NONE;
	return wtwm_stack_is_occluded(top_to_bottom, count, index) ?
		WTWM_STACK_RAISE : WTWM_STACK_LOWER;
}

ptrdiff_t wtwm_circle_up_candidate(const struct wtwm_stack_box *top_to_bottom,
		size_t count) {
	if (top_to_bottom == NULL || count > (size_t)PTRDIFF_MAX) return -1;
	for (size_t offset = 0; offset < count; ++offset) {
		size_t index = count - 1 - offset;
		if (wtwm_stack_is_occluded(top_to_bottom, count, index))
			return (ptrdiff_t)index;
	}
	return -1;
}

ptrdiff_t wtwm_circle_down_candidate(const struct wtwm_stack_box *top_to_bottom,
		size_t count) {
	if (top_to_bottom == NULL || count > (size_t)PTRDIFF_MAX) return -1;
	for (size_t index = 0; index < count; ++index) {
		if (!top_to_bottom[index].visible) continue;
		for (size_t below = index + 1; below < count; ++below) {
			if (wtwm_stack_boxes_overlap(&top_to_bottom[index],
					&top_to_bottom[below])) return (ptrdiff_t)index;
		}
	}
	return -1;
}
