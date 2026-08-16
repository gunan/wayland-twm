/* SPDX-License-Identifier: MIT */
#include "wtwm/lifecycle_model.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static struct wtwm_lifecycle_window *find_mutable(
		struct wtwm_lifecycle_model *model, uint64_t id) {
	if (id == 0) return NULL;
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		if (model->windows[i].active && model->windows[i].id == id)
			return &model->windows[i];
	}
	return NULL;
}

const struct wtwm_lifecycle_window *wtwm_lifecycle_find(
		const struct wtwm_lifecycle_model *model, uint64_t id) {
	if (id == 0) return NULL;
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		if (model->windows[i].active && model->windows[i].id == id)
			return &model->windows[i];
	}
	return NULL;
}

void wtwm_lifecycle_model_init(struct wtwm_lifecycle_model *model) {
	memset(model, 0, sizeof(*model));
	model->next_id = 1;
}

static size_t stack_index(const struct wtwm_lifecycle_model *model,
		uint64_t id) {
	for (size_t i = 0; i < model->stack_count; ++i) {
		if (model->stack[i] == id) return i;
	}
	return SIZE_MAX;
}

static void remove_stack_index(struct wtwm_lifecycle_model *model,
		size_t index) {
	if (index >= model->stack_count) return;
	if (index + 1 < model->stack_count) {
		memmove(&model->stack[index], &model->stack[index + 1],
			(model->stack_count - index - 1) * sizeof(model->stack[0]));
	}
	--model->stack_count;
	model->stack[model->stack_count] = 0;
}

static void insert_stack_bottom(struct wtwm_lifecycle_model *model,
		uint64_t id) {
	if (model->stack_count != 0) {
		memmove(&model->stack[1], &model->stack[0],
			model->stack_count * sizeof(model->stack[0]));
	}
	model->stack[0] = id;
	++model->stack_count;
}

static void insert_stack_top(struct wtwm_lifecycle_model *model,
		uint64_t id) {
	model->stack[model->stack_count++] = id;
}

static bool visible(const struct wtwm_lifecycle_window *window) {
	return window != NULL && window->mapped && !window->iconified;
}

static void repair_focus(struct wtwm_lifecycle_model *model) {
	if (visible(find_mutable(model, model->focus_id))) return;
	model->focus_id = 0;
}

static enum wtwm_lifecycle_result create_window(
		struct wtwm_lifecycle_model *model,
		const struct wtwm_lifecycle_operation *operation,
		uint64_t *created_id) {
	if (operation->parent_id != 0 &&
			find_mutable(model, operation->parent_id) == NULL)
		return WTWM_LIFECYCLE_IGNORED;
	if (model->next_id == 0 || model->next_id == UINT64_MAX)
		return WTWM_LIFECYCLE_ERROR;
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		if (model->windows[i].active) continue;
		model->windows[i] = (struct wtwm_lifecycle_window){
			.id = model->next_id++,
			.parent_id = operation->parent_id,
			.title_revision = operation->value,
			.active = true,
		};
		if (created_id != NULL) *created_id = model->windows[i].id;
		return WTWM_LIFECYCLE_APPLIED;
	}
	return WTWM_LIFECYCLE_IGNORED;
}

static enum wtwm_lifecycle_result map_window(
		struct wtwm_lifecycle_model *model,
		struct wtwm_lifecycle_window *window, bool remap) {
	if (window == NULL || window->mapped || window->ever_mapped != remap)
		return WTWM_LIFECYCLE_IGNORED;
	window->mapped = true;
	window->ever_mapped = true;
	window->iconified = false;
	insert_stack_top(model, window->id);
	return WTWM_LIFECYCLE_APPLIED;
}

static enum wtwm_lifecycle_result unmap_window(
		struct wtwm_lifecycle_model *model,
		struct wtwm_lifecycle_window *window) {
	if (window == NULL || !window->mapped) return WTWM_LIFECYCLE_IGNORED;
	size_t index = stack_index(model, window->id);
	if (index == SIZE_MAX) return WTWM_LIFECYCLE_ERROR;
	remove_stack_index(model, index);
	window->mapped = false;
	window->iconified = false;
	repair_focus(model);
	return WTWM_LIFECYCLE_APPLIED;
}

static enum wtwm_lifecycle_result destroy_window(
		struct wtwm_lifecycle_model *model,
		struct wtwm_lifecycle_window *window) {
	if (window == NULL) return WTWM_LIFECYCLE_IGNORED;
	if (window->mapped) {
		size_t index = stack_index(model, window->id);
		if (index == SIZE_MAX) return WTWM_LIFECYCLE_ERROR;
		remove_stack_index(model, index);
	}
	uint64_t destroyed_id = window->id;
	memset(window, 0, sizeof(*window));
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		if (model->windows[i].active &&
				model->windows[i].parent_id == destroyed_id)
			model->windows[i].parent_id = 0;
	}
	repair_focus(model);
	return WTWM_LIFECYCLE_APPLIED;
}

static enum wtwm_lifecycle_result restack_window(
		struct wtwm_lifecycle_model *model,
		struct wtwm_lifecycle_window *window,
		enum wtwm_lifecycle_operation_type type, uint32_t decision) {
	if (window == NULL || !window->mapped) return WTWM_LIFECYCLE_IGNORED;
	size_t index = stack_index(model, window->id);
	if (index == SIZE_MAX) return WTWM_LIFECYCLE_ERROR;
	bool to_top = type == WTWM_LIFECYCLE_RAISE ||
		(type == WTWM_LIFECYCLE_RAISELOWER &&
			decision == WTWM_LIFECYCLE_STACK_RAISE);
	bool to_bottom = type == WTWM_LIFECYCLE_LOWER ||
		(type == WTWM_LIFECYCLE_RAISELOWER &&
			decision == WTWM_LIFECYCLE_STACK_LOWER);
	if (!to_top && !to_bottom) return WTWM_LIFECYCLE_IGNORED;
	if (model->stack_count < 2) return WTWM_LIFECYCLE_APPLIED;
	remove_stack_index(model, index);
	if (to_top) insert_stack_top(model, window->id);
	else if (to_bottom) insert_stack_bottom(model, window->id);
	return WTWM_LIFECYCLE_APPLIED;
}

enum wtwm_lifecycle_result wtwm_lifecycle_apply(
		struct wtwm_lifecycle_model *model,
		const struct wtwm_lifecycle_operation *operation,
		uint64_t *created_id) {
	if (created_id != NULL) *created_id = 0;
	if (model == NULL || operation == NULL ||
			operation->type >= WTWM_LIFECYCLE_OPERATION_COUNT)
		return WTWM_LIFECYCLE_ERROR;
	if (operation->type == WTWM_LIFECYCLE_CREATE)
		return create_window(model, operation, created_id);

	struct wtwm_lifecycle_window *window =
		find_mutable(model, operation->target_id);
	switch (operation->type) {
	case WTWM_LIFECYCLE_MAP:
		return map_window(model, window, false);
	case WTWM_LIFECYCLE_UNMAP:
		return unmap_window(model, window);
	case WTWM_LIFECYCLE_REMAP:
		return map_window(model, window, true);
	case WTWM_LIFECYCLE_TITLE:
		if (window == NULL) return WTWM_LIFECYCLE_IGNORED;
		window->title_revision = operation->value;
		return WTWM_LIFECYCLE_APPLIED;
	case WTWM_LIFECYCLE_ICONIFY:
		if (!visible(window)) return WTWM_LIFECYCLE_IGNORED;
		window->iconified = true;
		repair_focus(model);
		return WTWM_LIFECYCLE_APPLIED;
	case WTWM_LIFECYCLE_DEICONIFY:
		if (window == NULL || !window->mapped || !window->iconified)
			return WTWM_LIFECYCLE_IGNORED;
		window->iconified = false;
		return WTWM_LIFECYCLE_APPLIED;
	case WTWM_LIFECYCLE_DESTROY:
		return destroy_window(model, window);
	case WTWM_LIFECYCLE_RAISE:
	case WTWM_LIFECYCLE_LOWER:
	case WTWM_LIFECYCLE_RAISELOWER:
		return restack_window(model, window, operation->type, operation->value);
	case WTWM_LIFECYCLE_CIRCLE_UP:
		return restack_window(model, window, WTWM_LIFECYCLE_RAISE, 0);
	case WTWM_LIFECYCLE_CIRCLE_DOWN:
		return restack_window(model, window, WTWM_LIFECYCLE_LOWER, 0);
	case WTWM_LIFECYCLE_FOCUS:
		if (!visible(window)) return WTWM_LIFECYCLE_IGNORED;
		model->focus_id = window->id;
		return WTWM_LIFECYCLE_APPLIED;
	default:
		return WTWM_LIFECYCLE_ERROR;
	}
}

static bool invalid(char *error, size_t error_size, const char *message) {
	if (error != NULL && error_size != 0)
		(void)snprintf(error, error_size, "%s", message);
	return false;
}

static bool invalid_id(char *error, size_t error_size, const char *message,
		uint64_t id) {
	if (error != NULL && error_size != 0)
		(void)snprintf(error, error_size, message, id);
	return false;
}

bool wtwm_lifecycle_validate(const struct wtwm_lifecycle_model *model,
		char *error, size_t error_size) {
	if (model == NULL) return invalid(error, error_size, "null model");
	if (model->next_id == 0)
		return invalid(error, error_size, "creation identity overflow");
	if (model->stack_count > WTWM_LIFECYCLE_MAX_WINDOWS)
		return invalid(error, error_size, "stack count overflow");

	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		const struct wtwm_lifecycle_window *window = &model->windows[i];
		if (!window->active) continue;
		if (window->id == 0 || window->id >= model->next_id)
			return invalid_id(error, error_size, "invalid active id %" PRIu64,
				window->id);
		if (window->parent_id == window->id ||
				(window->parent_id != 0 &&
				wtwm_lifecycle_find(model, window->parent_id) == NULL))
			return invalid_id(error, error_size, "stale parent for %" PRIu64,
				window->id);
		if (window->iconified && !window->mapped)
			return invalid_id(error, error_size, "unmapped icon %" PRIu64,
				window->id);
		for (size_t j = i + 1; j < WTWM_LIFECYCLE_MAX_WINDOWS; ++j) {
			if (model->windows[j].active &&
					model->windows[j].id == window->id)
				return invalid_id(error, error_size,
					"duplicate active id %" PRIu64, window->id);
		}
		size_t occurrences = 0;
		for (size_t j = 0; j < model->stack_count; ++j) {
			if (model->stack[j] == window->id) ++occurrences;
		}
		if ((window->mapped && occurrences != 1) ||
				(!window->mapped && occurrences != 0))
			return invalid_id(error, error_size, "list mismatch for %" PRIu64,
				window->id);
	}
	for (size_t i = 0; i < model->stack_count; ++i) {
		const struct wtwm_lifecycle_window *window =
			wtwm_lifecycle_find(model, model->stack[i]);
		if (window == NULL || !window->mapped)
			return invalid_id(error, error_size, "stale stack id %" PRIu64,
				model->stack[i]);
		for (size_t j = i + 1; j < model->stack_count; ++j) {
			if (model->stack[i] == model->stack[j])
				return invalid_id(error, error_size,
					"duplicate stack id %" PRIu64, model->stack[i]);
		}
	}
	if (model->focus_id != 0 &&
			!visible(wtwm_lifecycle_find(model, model->focus_id)))
		return invalid_id(error, error_size, "stale focus id %" PRIu64,
			model->focus_id);
	if (error != NULL && error_size != 0) error[0] = '\0';
	return true;
}

static uint64_t mix_u64(uint64_t digest, uint64_t value) {
	for (unsigned i = 0; i < 8; ++i) {
		digest ^= value & UINT64_C(0xff);
		digest *= UINT64_C(1099511628211);
		value >>= 8;
	}
	return digest;
}

uint64_t wtwm_lifecycle_digest(const struct wtwm_lifecycle_model *model) {
	uint64_t digest = UINT64_C(1469598103934665603);
	digest = mix_u64(digest, model->next_id);
	digest = mix_u64(digest, model->focus_id);
	digest = mix_u64(digest, model->stack_count);
	for (size_t i = 0; i < model->stack_count; ++i)
		digest = mix_u64(digest, model->stack[i]);
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		const struct wtwm_lifecycle_window *window = &model->windows[i];
		if (!window->active) continue;
		digest = mix_u64(digest, window->id);
		digest = mix_u64(digest, window->parent_id);
		digest = mix_u64(digest, window->title_revision);
		digest = mix_u64(digest, window->ever_mapped);
		digest = mix_u64(digest, window->mapped);
		digest = mix_u64(digest, window->iconified);
	}
	return digest;
}
