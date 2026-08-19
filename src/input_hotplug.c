/* SPDX-License-Identifier: MIT */

#include "wtwm/input_hotplug.h"

#include <math.h>
#include <string.h>

static bool modifiers_zero(const struct wtwm_input_modifiers *modifiers) {
	return modifiers->depressed == 0 && modifiers->latched == 0 &&
		modifiers->locked == 0 && modifiers->group == 0;
}

static bool valid_name(const char name[WTWM_INPUT_NAME_MAX]) {
	if (name[0] == '\0') return false;
	for (size_t index = 1; index < WTWM_INPUT_NAME_MAX; ++index) {
		if (name[index] == '\0') return true;
	}
	return false;
}

static bool source_name_length(const char *name, size_t *length) {
	if (name == NULL || name[0] == '\0') return false;
	for (size_t index = 1; index < WTWM_INPUT_NAME_MAX; ++index) {
		if (name[index] == '\0') {
			*length = index;
			return true;
		}
	}
	return false;
}

static bool held_valid(const struct wtwm_input_held *held, size_t count,
		size_t capacity) {
	if (count > capacity) return false;
	for (size_t index = 1; index < count; ++index) {
		if (held[index - 1].code >= held[index].code) return false;
	}
	return true;
}

static int find_device(const struct wtwm_input_hotplug_state *state,
		uint64_t ordinal) {
	for (size_t index = 0; index < state->device_count; ++index) {
		if (state->devices[index].ordinal == ordinal) return (int)index;
	}
	return -1;
}

static int selected_device(const struct wtwm_input_hotplug_state *state,
		enum wtwm_input_device_type type) {
	int selected = -1;
	for (size_t index = 0; index < state->device_count; ++index) {
		const struct wtwm_input_hotplug_device *candidate =
			&state->devices[index];
		if (candidate->type != type) continue;
		if (selected < 0 || candidate->last_activity >
				state->devices[selected].last_activity ||
				(candidate->last_activity ==
				state->devices[selected].last_activity &&
				candidate->ordinal < state->devices[selected].ordinal))
			selected = (int)index;
	}
	return selected;
}

static bool device_valid(const struct wtwm_input_hotplug_device *device) {
	if (!valid_name(device->name) || device->ordinal == 0 ||
			(device->type != WTWM_INPUT_DEVICE_KEYBOARD &&
			device->type != WTWM_INPUT_DEVICE_POINTER)) return false;
	if (!held_valid(device->keys, device->key_count,
			WTWM_INPUT_MAX_HELD_KEYS) ||
			!held_valid(device->buttons, device->button_count,
			WTWM_INPUT_MAX_HELD_BUTTONS)) return false;
	if (device->type == WTWM_INPUT_DEVICE_KEYBOARD)
		return device->button_count == 0;
	return device->key_count == 0 && modifiers_zero(&device->modifiers);
}

static size_t physical_button_holders(
		const struct wtwm_input_hotplug_state *state, uint32_t code) {
	size_t count = 0;
	for (size_t device_index = 0; device_index < state->device_count;
			++device_index) {
		const struct wtwm_input_hotplug_device *device =
			&state->devices[device_index];
		if (device->type != WTWM_INPUT_DEVICE_POINTER) continue;
		for (size_t index = 0; index < device->button_count; ++index) {
			if (device->buttons[index].code == code) ++count;
		}
	}
	return count;
}

void wtwm_input_hotplug_state_init(struct wtwm_input_hotplug_state *state) {
	if (state == NULL) return;
	*state = (struct wtwm_input_hotplug_state){
		.generation = 1,
		.next_ordinal = 1,
		.next_activity = 1,
	};
}

bool wtwm_input_hotplug_state_valid(
		const struct wtwm_input_hotplug_state *state) {
	if (state == NULL || state->device_count > WTWM_INPUT_MAX_DEVICES ||
			state->generation == 0 || state->next_ordinal == 0 ||
			state->next_activity == 0 || !isfinite(state->cursor_x) ||
			!isfinite(state->cursor_y) ||
			state->pointer_operation < WTWM_INPUT_POINTER_IDLE ||
			state->pointer_operation > WTWM_INPUT_POINTER_INITIAL_PLACEMENT)
		return false;

	size_t keyboards = 0, pointers = 0;
	for (size_t index = 0; index < state->device_count; ++index) {
		const struct wtwm_input_hotplug_device *device =
			&state->devices[index];
		if (!device_valid(device) || device->ordinal >= state->next_ordinal ||
				device->last_activity >= state->next_activity) return false;
		if (index > 0 && state->devices[index - 1].ordinal >= device->ordinal)
			return false;
		for (size_t prior = 0; prior < index; ++prior) {
			if (strcmp(state->devices[prior].name, device->name) == 0)
				return false;
			if (device->last_activity != 0 &&
					state->devices[prior].last_activity == device->last_activity)
				return false;
		}
		if (device->type == WTWM_INPUT_DEVICE_KEYBOARD) ++keyboards;
		else ++pointers;
	}
	if (keyboards != state->keyboard_count || pointers != state->pointer_count)
		return false;
	uint32_t capabilities = (keyboards > 0 ? WTWM_INPUT_CAPABILITY_KEYBOARD : 0) |
		(pointers > 0 ? WTWM_INPUT_CAPABILITY_POINTER : 0);
	if (state->capabilities != capabilities) return false;

	int keyboard = selected_device(state, WTWM_INPUT_DEVICE_KEYBOARD);
	if (state->active_keyboard_valid != (keyboard >= 0) ||
			(keyboard >= 0 && state->active_keyboard !=
			state->devices[keyboard].ordinal)) return false;
	int pointer = selected_device(state, WTWM_INPUT_DEVICE_POINTER);
	if (state->active_pointer_valid != (pointer >= 0) ||
			(pointer >= 0 && state->active_pointer !=
			state->devices[pointer].ordinal)) return false;
	if (pointers == 0 && (state->pointer_focus_valid ||
			state->pointer_operation != WTWM_INPUT_POINTER_IDLE)) return false;
	if ((state->pointer_operation == WTWM_INPUT_POINTER_IDLE &&
			state->pointer_operation_button_valid) ||
			(state->pointer_operation_button_valid &&
			physical_button_holders(state,
				state->pointer_operation_button) == 0)) return false;
	return true;
}

void wtwm_input_hotplug_plan_init(struct wtwm_input_hotplug_plan *plan) {
	if (plan != NULL) *plan = (struct wtwm_input_hotplug_plan){0};
}

static bool plan_ready(const struct wtwm_input_hotplug_plan *plan) {
	return plan != NULL && !plan->built && plan->base_generation == 0 &&
		plan->operation == WTWM_INPUT_PLAN_NONE && plan->next.generation == 0 &&
		plan->key_transition_count == 0 && plan->button_transition_count == 0;
}

static bool same_selection(bool left_valid, uint64_t left,
		bool right_valid, uint64_t right) {
	return left_valid == right_valid && (!left_valid || left == right);
}

static bool start_plan(const struct wtwm_input_hotplug_state *state,
		const struct wtwm_input_hotplug_plan *destination,
		enum wtwm_input_plan_operation operation,
		struct wtwm_input_hotplug_plan *result) {
	if (!wtwm_input_hotplug_state_valid(state) || !plan_ready(destination) ||
			state->generation == UINT64_MAX) return false;
	*result = (struct wtwm_input_hotplug_plan){0};
	result->next = *state;
	result->next.generation = state->generation + 1;
	result->base_generation = state->generation;
	result->operation = operation;
	result->capabilities_before = state->capabilities;
	return true;
}

static void set_selected(struct wtwm_input_hotplug_state *state,
		enum wtwm_input_device_type type) {
	int selected = selected_device(state, type);
	if (type == WTWM_INPUT_DEVICE_KEYBOARD) {
		state->active_keyboard_valid = selected >= 0;
		state->active_keyboard = selected >= 0 ?
			state->devices[selected].ordinal : 0;
	} else {
		state->active_pointer_valid = selected >= 0;
		state->active_pointer = selected >= 0 ?
			state->devices[selected].ordinal : 0;
	}
}

static void set_capabilities(struct wtwm_input_hotplug_state *state) {
	state->capabilities =
		(state->keyboard_count > 0 ? WTWM_INPUT_CAPABILITY_KEYBOARD : 0) |
		(state->pointer_count > 0 ? WTWM_INPUT_CAPABILITY_POINTER : 0);
}

static bool finish_plan(const struct wtwm_input_hotplug_state *before,
		struct wtwm_input_hotplug_plan *result,
		struct wtwm_input_hotplug_plan *destination) {
	if (!wtwm_input_hotplug_state_valid(&result->next)) return false;
	result->capabilities_after = result->next.capabilities;
	result->capabilities_changed = result->capabilities_before !=
		result->capabilities_after;
	result->active_keyboard_changed = !same_selection(
		before->active_keyboard_valid, before->active_keyboard,
		result->next.active_keyboard_valid, result->next.active_keyboard);
	result->active_pointer_changed = !same_selection(
		before->active_pointer_valid, before->active_pointer,
		result->next.active_pointer_valid, result->next.active_pointer);
	result->recompute_seat_modifiers = result->key_transition_count > 0;
	result->built = true;
	*destination = *result;
	return true;
}

bool wtwm_input_hotplug_plan_apply(struct wtwm_input_hotplug_state *state,
		const struct wtwm_input_hotplug_plan *plan) {
	if (!wtwm_input_hotplug_state_valid(state) || plan == NULL || !plan->built ||
			plan->operation == WTWM_INPUT_PLAN_NONE ||
			plan->base_generation != state->generation ||
			plan->base_generation == UINT64_MAX ||
			plan->next.generation != plan->base_generation + 1 ||
			!wtwm_input_hotplug_state_valid(&plan->next)) return false;
	*state = plan->next;
	return true;
}

static bool append_transition(struct wtwm_input_transition *transitions,
		size_t *count, size_t capacity, uint32_t code, bool pressed) {
	size_t at = 0;
	while (at < *count && transitions[at].code < code) ++at;
	if (at < *count && transitions[at].code == code) return true;
	if (*count == capacity) return false;
	memmove(&transitions[at + 1], &transitions[at],
		(*count - at) * sizeof(transitions[0]));
	transitions[at] = (struct wtwm_input_transition){
		.code = code,
		.pressed = pressed,
	};
	++*count;
	return true;
}

static size_t visible_holders(const struct wtwm_input_hotplug_state *state,
		enum wtwm_input_device_type type, uint32_t code) {
	size_t count = 0;
	for (size_t device_index = 0; device_index < state->device_count;
			++device_index) {
		const struct wtwm_input_hotplug_device *device =
			&state->devices[device_index];
		if (device->type != type) continue;
		const struct wtwm_input_held *held = type == WTWM_INPUT_DEVICE_KEYBOARD ?
			device->keys : device->buttons;
		size_t held_count = type == WTWM_INPUT_DEVICE_KEYBOARD ?
			device->key_count : device->button_count;
		for (size_t index = 0; index < held_count; ++index) {
			if (held[index].code == code && held[index].client_visible) ++count;
		}
	}
	return count;
}

static int held_index(const struct wtwm_input_held *held, size_t count,
		uint32_t code) {
	for (size_t index = 0; index < count; ++index) {
		if (held[index].code == code) return (int)index;
		if (held[index].code > code) break;
	}
	return -1;
}

static bool held_insert(struct wtwm_input_held *held, size_t *count,
		size_t capacity, uint32_t code, bool client_visible) {
	size_t at = 0;
	while (at < *count && held[at].code < code) ++at;
	if (at < *count && held[at].code == code) return false;
	if (*count == capacity) return false;
	memmove(&held[at + 1], &held[at], (*count - at) * sizeof(held[0]));
	held[at] = (struct wtwm_input_held){
		.code = code,
		.client_visible = client_visible,
	};
	++*count;
	return true;
}

static void held_remove(struct wtwm_input_held *held, size_t *count,
		size_t index) {
	memmove(&held[index], &held[index + 1],
		(*count - index - 1) * sizeof(held[0]));
	--*count;
	held[*count] = (struct wtwm_input_held){0};
}

static void renormalize_activity(struct wtwm_input_hotplug_state *state) {
	if (state->next_activity != UINT64_MAX) return;
	size_t order[WTWM_INPUT_MAX_DEVICES];
	size_t count = 0;
	for (size_t index = 0; index < state->device_count; ++index) {
		if (state->devices[index].last_activity == 0) continue;
		size_t at = count;
		while (at > 0 && state->devices[order[at - 1]].last_activity >
				state->devices[index].last_activity) {
			order[at] = order[at - 1];
			--at;
		}
		order[at] = index;
		++count;
	}
	for (size_t index = 0; index < count; ++index)
		state->devices[order[index]].last_activity = index + 1;
	state->next_activity = count + 1;
}

static void activate(struct wtwm_input_hotplug_state *state, size_t index) {
	renormalize_activity(state);
	state->devices[index].last_activity = state->next_activity++;
	if (state->devices[index].type == WTWM_INPUT_DEVICE_KEYBOARD) {
		state->active_keyboard_valid = true;
		state->active_keyboard = state->devices[index].ordinal;
	} else {
		state->active_pointer_valid = true;
		state->active_pointer = state->devices[index].ordinal;
	}
}

bool wtwm_input_hotplug_plan_add(
		const struct wtwm_input_hotplug_state *state, const char *name,
		enum wtwm_input_device_type type, struct wtwm_input_hotplug_plan *plan) {
	struct wtwm_input_hotplug_plan result;
	size_t length = 0;
	if (!source_name_length(name, &length) ||
			(type != WTWM_INPUT_DEVICE_KEYBOARD &&
			type != WTWM_INPUT_DEVICE_POINTER) ||
			!start_plan(state, plan, WTWM_INPUT_PLAN_ADD, &result) ||
			state->device_count == WTWM_INPUT_MAX_DEVICES ||
			state->next_ordinal == UINT64_MAX) return false;
	for (size_t index = 0; index < state->device_count; ++index) {
		if (strcmp(state->devices[index].name, name) == 0) return false;
	}

	struct wtwm_input_hotplug_device *device =
		&result.next.devices[result.next.device_count++];
	memcpy(device->name, name, length + 1);
	device->type = type;
	device->ordinal = result.next.next_ordinal++;
	result.device_ordinal = device->ordinal;
	if (type == WTWM_INPUT_DEVICE_KEYBOARD) {
		++result.next.keyboard_count;
		if (!result.next.active_keyboard_valid) {
			result.next.active_keyboard_valid = true;
			result.next.active_keyboard = device->ordinal;
			result.reassert_keyboard_focus = true;
		}
	} else {
		++result.next.pointer_count;
		if (!result.next.active_pointer_valid) {
			result.next.active_pointer_valid = true;
			result.next.active_pointer = device->ordinal;
			result.refresh_pointer_focus = true;
		}
	}
	set_capabilities(&result.next);
	return finish_plan(state, &result, plan);
}

static void mark_pointer_repairs(
		const struct wtwm_input_hotplug_state *before,
		struct wtwm_input_hotplug_plan *result) {
	bool last = before->pointer_count > 0 && result->next.pointer_count == 0;
	bool lost_required = before->pointer_operation != WTWM_INPUT_POINTER_IDLE &&
		before->pointer_operation_button_valid &&
		physical_button_holders(&result->next,
			before->pointer_operation_button) == 0;
	if (!last && !lost_required) return;
	if (last) {
		result->clear_pointer_focus = true;
		result->next.pointer_focus_valid = false;
		result->next.pointer_focus = 0;
	}
	switch (before->pointer_operation) {
	case WTWM_INPUT_POINTER_MENU:
		result->close_menu = true;
		break;
	case WTWM_INPUT_POINTER_DEFERRED_ACTION:
		result->cancel_deferred_action = true;
		break;
	case WTWM_INPUT_POINTER_MOVE:
	case WTWM_INPUT_POINTER_RESIZE:
		result->abort_move_resize = true;
		break;
	case WTWM_INPUT_POINTER_INITIAL_PLACEMENT:
		result->requeue_initial_placement = true;
		break;
	case WTWM_INPUT_POINTER_IDLE:
		break;
	}
	result->next.pointer_operation = WTWM_INPUT_POINTER_IDLE;
	result->next.pointer_operation_button_valid = false;
	result->next.pointer_operation_button = 0;
}

static bool drain_device(const struct wtwm_input_hotplug_state *state,
		const struct wtwm_input_hotplug_device *device,
		struct wtwm_input_hotplug_plan *result) {
	for (size_t index = 0; index < device->key_count; ++index) {
		if (!device->keys[index].client_visible ||
				visible_holders(state, WTWM_INPUT_DEVICE_KEYBOARD,
				device->keys[index].code) != 1) continue;
		if (!append_transition(result->key_transitions,
				&result->key_transition_count, WTWM_INPUT_MAX_KEY_TRANSITIONS,
				device->keys[index].code, false)) return false;
	}
	for (size_t index = 0; index < device->button_count; ++index) {
		if (!device->buttons[index].client_visible ||
				visible_holders(state, WTWM_INPUT_DEVICE_POINTER,
				device->buttons[index].code) != 1) continue;
		if (!append_transition(result->button_transitions,
				&result->button_transition_count,
				WTWM_INPUT_MAX_BUTTON_TRANSITIONS,
				device->buttons[index].code, false)) return false;
	}
	return true;
}

bool wtwm_input_hotplug_plan_remove(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		struct wtwm_input_hotplug_plan *plan) {
	struct wtwm_input_hotplug_plan result;
	if (!start_plan(state, plan, WTWM_INPUT_PLAN_REMOVE, &result)) return false;
	int found = find_device(state, ordinal);
	if (found < 0) return false;
	const struct wtwm_input_hotplug_device *removed = &state->devices[found];
	if (!drain_device(state, removed, &result)) return false;
	result.device_ordinal = ordinal;
	bool removed_active_keyboard = state->active_keyboard_valid &&
		state->active_keyboard == ordinal;
	if (removed->type == WTWM_INPUT_DEVICE_KEYBOARD)
		--result.next.keyboard_count;
	else --result.next.pointer_count;
	memmove(&result.next.devices[found], &result.next.devices[found + 1],
		(result.next.device_count - (size_t)found - 1) *
		sizeof(result.next.devices[0]));
	--result.next.device_count;
	result.next.devices[result.next.device_count] =
		(struct wtwm_input_hotplug_device){0};
	set_selected(&result.next, removed->type);
	set_capabilities(&result.next);
	if (removed_active_keyboard && result.next.active_keyboard_valid)
		result.reassert_keyboard_focus = true;
	mark_pointer_repairs(state, &result);
	return finish_plan(state, &result, plan);
}

bool wtwm_input_hotplug_plan_clear(
		const struct wtwm_input_hotplug_state *state,
		struct wtwm_input_hotplug_plan *plan) {
	struct wtwm_input_hotplug_plan result;
	if (!start_plan(state, plan, WTWM_INPUT_PLAN_CLEAR, &result)) return false;
	for (size_t device_index = 0; device_index < state->device_count;
			++device_index) {
		const struct wtwm_input_hotplug_device *device =
			&state->devices[device_index];
		for (size_t index = 0; index < device->key_count; ++index) {
			if (device->keys[index].client_visible &&
					!append_transition(result.key_transitions,
					&result.key_transition_count, WTWM_INPUT_MAX_KEY_TRANSITIONS,
					device->keys[index].code, false)) return false;
		}
		for (size_t index = 0; index < device->button_count; ++index) {
			if (device->buttons[index].client_visible &&
					!append_transition(result.button_transitions,
					&result.button_transition_count,
					WTWM_INPUT_MAX_BUTTON_TRANSITIONS,
					device->buttons[index].code, false)) return false;
		}
	}
	memset(result.next.devices, 0, sizeof(result.next.devices));
	result.next.device_count = 0;
	result.next.keyboard_count = 0;
	result.next.pointer_count = 0;
	result.next.capabilities = 0;
	result.next.active_keyboard_valid = false;
	result.next.active_keyboard = 0;
	result.next.active_pointer_valid = false;
	result.next.active_pointer = 0;
	mark_pointer_repairs(state, &result);
	return finish_plan(state, &result, plan);
}

static bool prepare_event(const struct wtwm_input_hotplug_state *state,
		uint64_t ordinal, enum wtwm_input_device_type type,
		enum wtwm_input_plan_operation operation,
		struct wtwm_input_hotplug_plan *destination,
		struct wtwm_input_hotplug_plan *result, size_t *device_index) {
	if (!start_plan(state, destination, operation, result)) return false;
	int found = find_device(state, ordinal);
	if (found < 0 || state->devices[found].type != type) return false;
	result->device_ordinal = ordinal;
	*device_index = (size_t)found;
	return true;
}

static bool plan_held_event(const struct wtwm_input_hotplug_state *state,
		uint64_t ordinal, enum wtwm_input_device_type type, uint32_t code,
		bool pressed, bool client_visible,
		struct wtwm_input_hotplug_plan *destination) {
	struct wtwm_input_hotplug_plan result;
	size_t device_index = 0;
	enum wtwm_input_plan_operation operation =
		type == WTWM_INPUT_DEVICE_KEYBOARD ? WTWM_INPUT_PLAN_KEY :
		WTWM_INPUT_PLAN_BUTTON;
	if (!prepare_event(state, ordinal, type, operation, destination, &result,
			&device_index)) return false;
	const struct wtwm_input_hotplug_device *old_device =
		&state->devices[device_index];
	const struct wtwm_input_held *old_held =
		type == WTWM_INPUT_DEVICE_KEYBOARD ? old_device->keys :
		old_device->buttons;
	size_t old_count = type == WTWM_INPUT_DEVICE_KEYBOARD ?
		old_device->key_count : old_device->button_count;
	int found = held_index(old_held, old_count, code);
	if ((pressed && found >= 0) || (!pressed && found < 0)) return false;

	activate(&result.next, device_index);
	struct wtwm_input_hotplug_device *device =
		&result.next.devices[device_index];
	struct wtwm_input_held *held = type == WTWM_INPUT_DEVICE_KEYBOARD ?
		device->keys : device->buttons;
	size_t *count = type == WTWM_INPUT_DEVICE_KEYBOARD ?
		&device->key_count : &device->button_count;
	size_t capacity = type == WTWM_INPUT_DEVICE_KEYBOARD ?
		WTWM_INPUT_MAX_HELD_KEYS : WTWM_INPUT_MAX_HELD_BUTTONS;
	bool transition = false;
	bool stored_visible = client_visible;
	if (pressed) {
		if (!held_insert(held, count, capacity, code, client_visible)) return false;
		transition = client_visible && visible_holders(state, type, code) == 0;
	} else {
		stored_visible = old_held[found].client_visible;
		transition = stored_visible && visible_holders(state, type, code) == 1;
		held_remove(held, count, (size_t)found);
	}
	if (transition) {
		if (type == WTWM_INPUT_DEVICE_KEYBOARD) {
			if (!append_transition(result.key_transitions,
					&result.key_transition_count, WTWM_INPUT_MAX_KEY_TRANSITIONS,
					code, pressed)) return false;
		} else if (!append_transition(result.button_transitions,
				&result.button_transition_count, WTWM_INPUT_MAX_BUTTON_TRANSITIONS,
				code, pressed)) return false;
	}
	return finish_plan(state, &result, destination);
}

bool wtwm_input_hotplug_plan_key_press(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		uint32_t keycode, bool client_visible,
		struct wtwm_input_hotplug_plan *plan) {
	return plan_held_event(state, ordinal, WTWM_INPUT_DEVICE_KEYBOARD,
		keycode, true, client_visible, plan);
}

bool wtwm_input_hotplug_plan_key_release(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		uint32_t keycode, struct wtwm_input_hotplug_plan *plan) {
	return plan_held_event(state, ordinal, WTWM_INPUT_DEVICE_KEYBOARD,
		keycode, false, false, plan);
}

bool wtwm_input_hotplug_plan_modifiers(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		struct wtwm_input_modifiers modifiers,
		struct wtwm_input_hotplug_plan *plan) {
	struct wtwm_input_hotplug_plan result;
	size_t device_index = 0;
	if (!prepare_event(state, ordinal, WTWM_INPUT_DEVICE_KEYBOARD,
			WTWM_INPUT_PLAN_MODIFIERS, plan, &result, &device_index)) return false;
	activate(&result.next, device_index);
	result.next.devices[device_index].modifiers = modifiers;
	return finish_plan(state, &result, plan);
}

bool wtwm_input_hotplug_plan_pointer_motion(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		double x, double y, struct wtwm_input_hotplug_plan *plan) {
	struct wtwm_input_hotplug_plan result;
	size_t device_index = 0;
	if (!isfinite(x) || !isfinite(y) ||
			!prepare_event(state, ordinal, WTWM_INPUT_DEVICE_POINTER,
			WTWM_INPUT_PLAN_POINTER_MOTION, plan, &result, &device_index))
		return false;
	activate(&result.next, device_index);
	result.next.cursor_x = x;
	result.next.cursor_y = y;
	return finish_plan(state, &result, plan);
}

bool wtwm_input_hotplug_plan_button_press(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		uint32_t button, bool client_visible,
		struct wtwm_input_hotplug_plan *plan) {
	return plan_held_event(state, ordinal, WTWM_INPUT_DEVICE_POINTER,
		button, true, client_visible, plan);
}

bool wtwm_input_hotplug_plan_button_release(
		const struct wtwm_input_hotplug_state *state, uint64_t ordinal,
		uint32_t button, struct wtwm_input_hotplug_plan *plan) {
	return plan_held_event(state, ordinal, WTWM_INPUT_DEVICE_POINTER,
		button, false, false, plan);
}
