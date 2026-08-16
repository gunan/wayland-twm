/* SPDX-License-Identifier: MIT */
#ifndef WTWM_LIFECYCLE_MODEL_H
#define WTWM_LIFECYCLE_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_LIFECYCLE_MAX_WINDOWS 64

enum wtwm_lifecycle_operation_type {
	WTWM_LIFECYCLE_CREATE,
	WTWM_LIFECYCLE_MAP,
	WTWM_LIFECYCLE_UNMAP,
	WTWM_LIFECYCLE_REMAP,
	WTWM_LIFECYCLE_TITLE,
	WTWM_LIFECYCLE_ICONIFY,
	WTWM_LIFECYCLE_DEICONIFY,
	WTWM_LIFECYCLE_DESTROY,
	WTWM_LIFECYCLE_RAISE,
	WTWM_LIFECYCLE_LOWER,
	WTWM_LIFECYCLE_RAISELOWER,
	WTWM_LIFECYCLE_CIRCLE_UP,
	WTWM_LIFECYCLE_CIRCLE_DOWN,
	WTWM_LIFECYCLE_FOCUS,
	WTWM_LIFECYCLE_OPERATION_COUNT,
};

enum wtwm_lifecycle_result {
	WTWM_LIFECYCLE_IGNORED,
	WTWM_LIFECYCLE_APPLIED,
	WTWM_LIFECYCLE_ERROR,
};

enum wtwm_lifecycle_stack_decision {
	WTWM_LIFECYCLE_STACK_RAISE = 1,
	WTWM_LIFECYCLE_STACK_LOWER = 2,
};

struct wtwm_lifecycle_operation {
	enum wtwm_lifecycle_operation_type type;
	/* Circle operations require the target selected by the X circulation oracle. */
	uint64_t target_id;
	uint64_t parent_id;
	/* RAISELOWER requires a caller-supplied WTWM_LIFECYCLE_STACK_* decision. */
	uint32_t value;
};

struct wtwm_lifecycle_window {
	uint64_t id;
	uint64_t parent_id;
	uint32_t title_revision;
	bool active;
	bool ever_mapped;
	bool mapped;
	bool iconified;
};

struct wtwm_lifecycle_model {
	struct wtwm_lifecycle_window windows[WTWM_LIFECYCLE_MAX_WINDOWS];
	uint64_t stack[WTWM_LIFECYCLE_MAX_WINDOWS];
	size_t stack_count;
	uint64_t focus_id;
	uint64_t next_id;
};

void wtwm_lifecycle_model_init(struct wtwm_lifecycle_model *model);

enum wtwm_lifecycle_result wtwm_lifecycle_apply(
	struct wtwm_lifecycle_model *model,
	const struct wtwm_lifecycle_operation *operation,
	uint64_t *created_id);

const struct wtwm_lifecycle_window *wtwm_lifecycle_find(
	const struct wtwm_lifecycle_model *model, uint64_t id);

bool wtwm_lifecycle_validate(const struct wtwm_lifecycle_model *model,
	char *error, size_t error_size);

uint64_t wtwm_lifecycle_digest(const struct wtwm_lifecycle_model *model);

#endif
