/* SPDX-License-Identifier: MIT */
#ifndef WTWM_INPUT_HOTPLUG_H
#define WTWM_INPUT_HOTPLUG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_INPUT_NAME_MAX 512
#define WTWM_INPUT_MAX_DEVICES 64
#define WTWM_INPUT_MAX_HELD_KEYS 64
#define WTWM_INPUT_MAX_HELD_BUTTONS 32
#define WTWM_INPUT_MAX_KEY_TRANSITIONS \
	(WTWM_INPUT_MAX_DEVICES * WTWM_INPUT_MAX_HELD_KEYS)
#define WTWM_INPUT_MAX_BUTTON_TRANSITIONS \
	(WTWM_INPUT_MAX_DEVICES * WTWM_INPUT_MAX_HELD_BUTTONS)
#define WTWM_INPUT_HOTPLUG_STATE_MAX_BYTES 131072
#define WTWM_INPUT_HOTPLUG_PLAN_MAX_BYTES 262144

enum wtwm_input_device_type {
	WTWM_INPUT_DEVICE_KEYBOARD,
	WTWM_INPUT_DEVICE_POINTER,
};

enum wtwm_input_capability {
	WTWM_INPUT_CAPABILITY_KEYBOARD = 1u << 0,
	WTWM_INPUT_CAPABILITY_POINTER = 1u << 1,
};

enum wtwm_input_pointer_operation {
	WTWM_INPUT_POINTER_IDLE,
	WTWM_INPUT_POINTER_MENU,
	WTWM_INPUT_POINTER_DEFERRED_ACTION,
	WTWM_INPUT_POINTER_MOVE,
	WTWM_INPUT_POINTER_RESIZE,
	WTWM_INPUT_POINTER_INITIAL_PLACEMENT,
};

struct wtwm_input_modifiers {
	uint32_t depressed;
	uint32_t latched;
	uint32_t locked;
	uint32_t group;
};

struct wtwm_input_held {
	uint32_t code;
	bool client_visible;
};

/* One immutable physical-device identity and its owned physical state. */
struct wtwm_input_hotplug_device {
	char name[WTWM_INPUT_NAME_MAX];
	enum wtwm_input_device_type type;
	uint64_t ordinal;
	uint64_t last_activity;
	struct wtwm_input_modifiers modifiers;
	struct wtwm_input_held keys[WTWM_INPUT_MAX_HELD_KEYS];
	size_t key_count;
	struct wtwm_input_held buttons[WTWM_INPUT_MAX_HELD_BUTTONS];
	size_t button_count;
};

/*
 * Self-contained one-seat state.  The focus cookies are opaque compositor
 * identities.  They and the shared cursor survive device churn except that
 * removing the final pointer clears pointer protocol focus.
 */
struct wtwm_input_hotplug_state {
	struct wtwm_input_hotplug_device devices[WTWM_INPUT_MAX_DEVICES];
	size_t device_count;
	size_t keyboard_count;
	size_t pointer_count;
	uint32_t capabilities;
	uint64_t generation;
	uint64_t next_ordinal;
	uint64_t next_activity;
	bool active_keyboard_valid;
	uint64_t active_keyboard;
	bool active_pointer_valid;
	uint64_t active_pointer;
	bool keyboard_focus_valid;
	uint64_t keyboard_focus;
	bool pointer_focus_valid;
	uint64_t pointer_focus;
	double cursor_x;
	double cursor_y;
	enum wtwm_input_pointer_operation pointer_operation;
	bool pointer_operation_button_valid;
	uint32_t pointer_operation_button;
};

struct wtwm_input_transition {
	uint32_t code;
	bool pressed;
};

enum wtwm_input_plan_operation {
	WTWM_INPUT_PLAN_NONE,
	WTWM_INPUT_PLAN_ADD,
	WTWM_INPUT_PLAN_REMOVE,
	WTWM_INPUT_PLAN_CLEAR,
	WTWM_INPUT_PLAN_KEY,
	WTWM_INPUT_PLAN_MODIFIERS,
	WTWM_INPUT_PLAN_POINTER_MOTION,
	WTWM_INPUT_PLAN_BUTTON,
};

/*
 * One complete, atomic next state plus the effects the wlroots adapter applies.
 * Physical modifier snapshots are diagnostic only: logical seat modifiers are
 * derived by the compositor-owned aggregate xkb state from key_transitions.
 */
struct wtwm_input_hotplug_plan {
	struct wtwm_input_hotplug_state next;
	uint64_t base_generation;
	enum wtwm_input_plan_operation operation;
	uint64_t device_ordinal;
	uint32_t capabilities_before;
	uint32_t capabilities_after;
	bool capabilities_changed;
	bool active_keyboard_changed;
	bool active_pointer_changed;
	bool reassert_keyboard_focus;
	bool recompute_seat_modifiers;
	struct wtwm_input_transition
		key_transitions[WTWM_INPUT_MAX_KEY_TRANSITIONS];
	size_t key_transition_count;
	struct wtwm_input_transition
		button_transitions[WTWM_INPUT_MAX_BUTTON_TRANSITIONS];
	size_t button_transition_count;
	bool clear_pointer_focus;
	bool refresh_pointer_focus;
	bool close_menu;
	bool cancel_deferred_action;
	bool abort_move_resize;
	bool requeue_initial_placement;
	bool built;
};

_Static_assert(sizeof(struct wtwm_input_hotplug_state) <=
	WTWM_INPUT_HOTPLUG_STATE_MAX_BYTES, "input state exceeds resource bound");
_Static_assert(sizeof(struct wtwm_input_hotplug_plan) <=
	WTWM_INPUT_HOTPLUG_PLAN_MAX_BYTES, "input plan exceeds resource bound");

void wtwm_input_hotplug_state_init(struct wtwm_input_hotplug_state *state);
bool wtwm_input_hotplug_state_valid(
	const struct wtwm_input_hotplug_state *state);
void wtwm_input_hotplug_plan_init(struct wtwm_input_hotplug_plan *plan);

/* A stale plan is rejected; successful apply copies its complete next state. */
bool wtwm_input_hotplug_plan_apply(struct wtwm_input_hotplug_state *state,
	const struct wtwm_input_hotplug_plan *plan);

bool wtwm_input_hotplug_plan_add(
	const struct wtwm_input_hotplug_state *state, const char *name,
	enum wtwm_input_device_type type, struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_remove(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_clear(
	const struct wtwm_input_hotplug_state *state,
	struct wtwm_input_hotplug_plan *plan);

/* client_visible is stored on press; release consumes that stored disposition. */
bool wtwm_input_hotplug_plan_key_press(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	uint32_t keycode, bool client_visible,
	struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_key_release(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	uint32_t keycode, struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_modifiers(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	struct wtwm_input_modifiers modifiers,
	struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_pointer_motion(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	double x, double y, struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_button_press(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	uint32_t button, bool client_visible,
	struct wtwm_input_hotplug_plan *plan);
bool wtwm_input_hotplug_plan_button_release(
	const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
	uint32_t button, struct wtwm_input_hotplug_plan *plan);

#endif
