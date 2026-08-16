/* SPDX-License-Identifier: MIT */
#ifndef WTWM_FOCUS_STACK_H
#define WTWM_FOCUS_STACK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum wtwm_focus_surface {
	WTWM_FOCUS_SURFACE_ROOT,
	WTWM_FOCUS_SURFACE_FRAME,
	WTWM_FOCUS_SURFACE_TITLE,
	WTWM_FOCUS_SURFACE_CLIENT,
	WTWM_FOCUS_SURFACE_ICON,
	WTWM_FOCUS_SURFACE_ICON_MANAGER,
	WTWM_FOCUS_SURFACE_MENU,
};

struct wtwm_focus_enter_input {
	bool focus_root;
	enum wtwm_focus_surface surface;
	bool title_focus;
	bool has_title;
	bool global_no_titlebar;
	bool input_hint;
	bool take_focus;
};

struct wtwm_focus_enter_result {
	bool activate;
	bool set_input_focus;
	bool send_take_focus;
};

struct wtwm_focus_leave_input {
	bool focus_root;
	enum wtwm_focus_surface surface;
	bool detail_inferior;
	bool queued_match;
	bool title_focus;
	bool take_focus;
};

struct wtwm_focus_leave_result {
	bool deactivate;
	bool set_pointer_root;
};

enum wtwm_focus_toggle_result {
	WTWM_FOCUS_UNCHANGED,
	WTWM_FOCUS_CLICK_LOCKED,
	WTWM_FOCUS_POINTER_ROOT,
};

enum wtwm_stack_action {
	WTWM_STACK_NONE,
	WTWM_STACK_RAISE,
	WTWM_STACK_LOWER,
};

struct wtwm_stack_box {
	int x;
	int y;
	int width;
	int height;
	bool visible;
};

uint32_t wtwm_binding_context_for_surface(enum wtwm_focus_surface surface);

struct wtwm_focus_enter_result wtwm_focus_enter(
	const struct wtwm_focus_enter_input *input);

struct wtwm_focus_leave_result wtwm_focus_leave(
	const struct wtwm_focus_leave_input *input);

enum wtwm_focus_toggle_result wtwm_focus_toggle(bool focus_root,
	bool selected_is_current, bool iconified);

bool wtwm_stack_boxes_overlap(const struct wtwm_stack_box *first,
	const struct wtwm_stack_box *second);

bool wtwm_stack_is_occluded(const struct wtwm_stack_box *top_to_bottom,
	size_t count, size_t index);

enum wtwm_stack_action wtwm_raise_lower_action(
	const struct wtwm_stack_box *top_to_bottom, size_t count, size_t index,
	bool window_moved);

ptrdiff_t wtwm_circle_up_candidate(const struct wtwm_stack_box *top_to_bottom,
	size_t count);

ptrdiff_t wtwm_circle_down_candidate(const struct wtwm_stack_box *top_to_bottom,
	size_t count);

#endif
