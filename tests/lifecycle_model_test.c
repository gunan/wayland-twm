/* SPDX-License-Identifier: MIT */
#include "wtwm/lifecycle_model.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define OPERATIONS_PER_SEED 6000

static enum wtwm_lifecycle_result apply(struct wtwm_lifecycle_model *model,
		enum wtwm_lifecycle_operation_type type, uint64_t target,
		uint64_t parent, uint32_t value, uint64_t *created) {
	struct wtwm_lifecycle_operation operation = {
		.type = type,
		.target_id = target,
		.parent_id = parent,
		.value = value,
	};
	return wtwm_lifecycle_apply(model, &operation, created);
}

static uint64_t create(struct wtwm_lifecycle_model *model, uint64_t parent) {
	uint64_t id = 0;
	assert(apply(model, WTWM_LIFECYCLE_CREATE, 0, parent, 1, &id) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(id != 0);
	return id;
}

static void assert_valid(const struct wtwm_lifecycle_model *model) {
	char error[128];
	if (!wtwm_lifecycle_validate(model, error, sizeof(error))) {
		fprintf(stderr, "invalid lifecycle model: %s\n", error);
		assert(false);
	}
}

static void known_lifecycle_and_transients(void) {
	struct wtwm_lifecycle_model model;
	wtwm_lifecycle_model_init(&model);
	uint64_t parent = create(&model, 0);
	uint64_t child = create(&model, parent);
	assert(parent == 1 && child == 2);
	assert(apply(&model, WTWM_LIFECYCLE_MAP, parent, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(apply(&model, WTWM_LIFECYCLE_MAP, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == 0);
	assert(apply(&model, WTWM_LIFECYCLE_FOCUS, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == child);
	assert(apply(&model, WTWM_LIFECYCLE_TITLE, child, 0, 9, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(wtwm_lifecycle_find(&model, child)->title_revision == 9);

	assert(apply(&model, WTWM_LIFECYCLE_UNMAP, parent, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(wtwm_lifecycle_find(&model, child)->mapped);
	assert(wtwm_lifecycle_find(&model, child)->parent_id == parent);
	assert(model.focus_id == child);
	assert(apply(&model, WTWM_LIFECYCLE_DESTROY, parent, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(wtwm_lifecycle_find(&model, parent) == NULL);
	assert(wtwm_lifecycle_find(&model, child)->parent_id == 0);

	assert(apply(&model, WTWM_LIFECYCLE_ICONIFY, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == 0);
	assert(apply(&model, WTWM_LIFECYCLE_DEICONIFY, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == 0);
	assert(apply(&model, WTWM_LIFECYCLE_FOCUS, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == child);
	assert(apply(&model, WTWM_LIFECYCLE_UNMAP, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(apply(&model, WTWM_LIFECYCLE_REMAP, child, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(wtwm_lifecycle_find(&model, child)->id == child);
	assert_valid(&model);
}

static void known_stacking(void) {
	struct wtwm_lifecycle_model model;
	wtwm_lifecycle_model_init(&model);
	uint64_t one = create(&model, 0);
	uint64_t two = create(&model, 0);
	uint64_t three = create(&model, 0);
	assert(apply(&model, WTWM_LIFECYCLE_MAP, one, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(apply(&model, WTWM_LIFECYCLE_MAP, two, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(apply(&model, WTWM_LIFECYCLE_MAP, three, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == 0);
	assert(apply(&model, WTWM_LIFECYCLE_FOCUS, three, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.focus_id == three);
	assert(apply(&model, WTWM_LIFECYCLE_RAISELOWER, one, 0, 0, NULL) ==
		WTWM_LIFECYCLE_IGNORED);
	assert(apply(&model, WTWM_LIFECYCLE_RAISE, one, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.stack[0] == two && model.stack[1] == three &&
		model.stack[2] == one && model.focus_id == three);
	assert(apply(&model, WTWM_LIFECYCLE_LOWER, three, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.stack[0] == three && model.stack[1] == two &&
		model.stack[2] == one && model.focus_id == three);
	assert(apply(&model, WTWM_LIFECYCLE_RAISELOWER, one, 0,
		WTWM_LIFECYCLE_STACK_LOWER, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.stack[0] == one && model.stack[1] == three &&
		model.stack[2] == two);
	assert(apply(&model, WTWM_LIFECYCLE_CIRCLE_UP, one, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.stack[0] == three && model.stack[1] == two &&
		model.stack[2] == one);
	assert(apply(&model, WTWM_LIFECYCLE_CIRCLE_DOWN, one, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert(model.stack[0] == one && model.stack[1] == three &&
		model.stack[2] == two);
	assert(model.focus_id == three);
	assert_valid(&model);
}

static uint32_t next_random(uint32_t *state) {
	uint32_t value = *state;
	value ^= value << 13;
	value ^= value >> 17;
	value ^= value << 5;
	*state = value;
	return value;
}

static uint64_t choose_window(const struct wtwm_lifecycle_model *model,
		enum wtwm_lifecycle_operation_type type, uint32_t random) {
	uint64_t eligible[WTWM_LIFECYCLE_MAX_WINDOWS];
	size_t count = 0;
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		const struct wtwm_lifecycle_window *window = &model->windows[i];
		if (!window->active) continue;
		bool matches = false;
		switch (type) {
		case WTWM_LIFECYCLE_MAP:
			matches = !window->ever_mapped; break;
		case WTWM_LIFECYCLE_UNMAP:
			matches = window->mapped; break;
		case WTWM_LIFECYCLE_REMAP:
			matches = window->ever_mapped && !window->mapped; break;
		case WTWM_LIFECYCLE_ICONIFY:
			matches = window->mapped && !window->iconified; break;
		case WTWM_LIFECYCLE_DEICONIFY:
			matches = window->mapped && window->iconified; break;
		case WTWM_LIFECYCLE_RAISE:
		case WTWM_LIFECYCLE_LOWER:
		case WTWM_LIFECYCLE_RAISELOWER:
		case WTWM_LIFECYCLE_CIRCLE_UP:
		case WTWM_LIFECYCLE_CIRCLE_DOWN:
			matches = window->mapped; break;
		case WTWM_LIFECYCLE_FOCUS:
			matches = window->mapped && !window->iconified; break;
		default:
			matches = true; break;
		}
		if (matches) eligible[count++] = window->id;
	}
	if (count == 0 || (random & UINT32_C(15)) == 0)
		return model->next_id + 100 + random % 31;
	return eligible[random % count];
}

static uint64_t random_parent(const struct wtwm_lifecycle_model *model,
		uint32_t random) {
	if ((random & 3) != 0) return 0;
	uint64_t active[WTWM_LIFECYCLE_MAX_WINDOWS];
	size_t count = 0;
	for (size_t i = 0; i < WTWM_LIFECYCLE_MAX_WINDOWS; ++i) {
		if (model->windows[i].active)
			active[count++] = model->windows[i].id;
	}
	return count == 0 ? 0 : active[random % count];
}

static uint64_t mix(uint64_t digest, uint64_t value) {
	return (digest ^ value) * UINT64_C(1099511628211);
}

static uint64_t run_randomized(uint32_t seed,
		unsigned applied[WTWM_LIFECYCLE_OPERATION_COUNT]) {
	struct wtwm_lifecycle_model model;
	wtwm_lifecycle_model_init(&model);
	uint32_t random = seed;
	uint64_t history = UINT64_C(1469598103934665603);
	uint64_t previous_next_id = model.next_id;
	for (unsigned step = 0; step < OPERATIONS_PER_SEED; ++step) {
		enum wtwm_lifecycle_operation_type type =
			(enum wtwm_lifecycle_operation_type)(
				next_random(&random) % WTWM_LIFECYCLE_OPERATION_COUNT);
		uint64_t parent = type == WTWM_LIFECYCLE_CREATE ?
			random_parent(&model, next_random(&random)) : 0;
		uint64_t target = choose_window(&model, type, next_random(&random));
		uint32_t value = next_random(&random);
		if (type == WTWM_LIFECYCLE_RAISELOWER) {
			value = (value & 1) != 0 ? WTWM_LIFECYCLE_STACK_RAISE :
				WTWM_LIFECYCLE_STACK_LOWER;
		}
		uint64_t created = 0;
		enum wtwm_lifecycle_result result = apply(&model, type, target,
			parent, value, &created);
		assert(result != WTWM_LIFECYCLE_ERROR);
		if (result == WTWM_LIFECYCLE_APPLIED) ++applied[type];
		if (created != 0) {
			assert(created == previous_next_id);
			previous_next_id = model.next_id;
		}
		assert_valid(&model);
		history = mix(history, type);
		history = mix(history, result);
		history = mix(history, created);
		history = mix(history, wtwm_lifecycle_digest(&model));
	}
	return history;
}

static void randomized_sequences_are_valid_and_repeatable(void) {
	static const uint32_t seeds[] = {
		UINT32_C(1), UINT32_C(7), UINT32_C(42),
		UINT32_C(305419896), UINT32_C(3735928559),
	};
	unsigned applied[WTWM_LIFECYCLE_OPERATION_COUNT] = {0};
	for (size_t i = 0; i < sizeof(seeds) / sizeof(seeds[0]); ++i) {
		unsigned replayed[WTWM_LIFECYCLE_OPERATION_COUNT] = {0};
		uint64_t first = run_randomized(seeds[i], applied);
		uint64_t second = run_randomized(seeds[i], replayed);
		assert(first == second);
	}
	for (size_t i = 0; i < WTWM_LIFECYCLE_OPERATION_COUNT; ++i)
		assert(applied[i] != 0);
}

static void validator_rejects_tampering(void) {
	struct wtwm_lifecycle_model model;
	wtwm_lifecycle_model_init(&model);
	uint64_t id = create(&model, 0);
	assert(apply(&model, WTWM_LIFECYCLE_MAP, id, 0, 0, NULL) ==
		WTWM_LIFECYCLE_APPLIED);
	assert_valid(&model);
	model.stack[0] = id + 1;
	assert(!wtwm_lifecycle_validate(&model, NULL, 0));
	model.stack[0] = id;
	model.focus_id = id + 1;
	assert(!wtwm_lifecycle_validate(&model, NULL, 0));
	model.focus_id = id;
	model.windows[0].parent_id = id + 1;
	assert(!wtwm_lifecycle_validate(&model, NULL, 0));
	model.windows[0].parent_id = 0;
	model.windows[1] = model.windows[0];
	assert(!wtwm_lifecycle_validate(&model, NULL, 0));
}

int main(void) {
	known_lifecycle_and_transients();
	known_stacking();
	randomized_sequences_are_valid_and_repeatable();
	validator_rejects_tampering();
	return 0;
}
