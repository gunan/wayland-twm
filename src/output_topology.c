/* SPDX-License-Identifier: MIT */

#include "wtwm/output_topology.h"

#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

static int compare_bytes(const char *left, const char *right) {
	if (left == NULL) left = "";
	if (right == NULL) right = "";
	const unsigned char *a = (const unsigned char *)left;
	const unsigned char *b = (const unsigned char *)right;
	while (*a != '\0' && *a == *b) {
		++a;
		++b;
	}
	return *a < *b ? -1 : *a > *b;
}

static int compare_identity(const struct wtwm_output_identity *left,
		const struct wtwm_output_identity *right) {
	int result = compare_bytes(left->name, right->name);
	if (result == 0) result = compare_bytes(left->make, right->make);
	if (result == 0) result = compare_bytes(left->model, right->model);
	if (result == 0) result = compare_bytes(left->serial, right->serial);
	if (result != 0) return result;
	return left->announcement_ordinal < right->announcement_ordinal ? -1 :
		left->announcement_ordinal > right->announcement_ordinal;
}

static bool same_identity(const struct wtwm_output_identity *left,
		const struct wtwm_output_identity *right) {
	return compare_identity(left, right) == 0;
}

static bool valid_output(const struct wtwm_output_topology_output *output) {
	if (output->identity == NULL || output->mode.width <= 0 ||
			output->mode.height <= 0 || !isfinite(output->scale) ||
			output->scale <= 0.0 ||
			output->scale > WTWM_OUTPUT_TOPOLOGY_MAX_SCALE ||
			output->transform < WTWM_OUTPUT_TRANSFORM_NORMAL ||
			output->transform > WTWM_OUTPUT_TRANSFORM_FLIPPED_270) return false;
	if (output->enabled) return output->width > 0 && output->height > 0;
	return output->x == 0 && output->y == 0 && output->width == 0 &&
		output->height == 0;
}

static bool valid_snapshot(const struct wtwm_output_topology_snapshot *snapshot,
		size_t *enabled_count) {
	if (snapshot == NULL || (snapshot->count > 0 && snapshot->outputs == NULL))
		return false;
	*enabled_count = 0;
	for (size_t index = 0; index < snapshot->count; ++index) {
		const struct wtwm_output_topology_output *output =
			&snapshot->outputs[index];
		if (!valid_output(output)) return false;
		if (output->enabled) {
			if (*enabled_count == (size_t)INT_MAX) return false;
			++*enabled_count;
		}
		for (size_t prior = 0; prior < index; ++prior) {
			if (snapshot->outputs[prior].identity->announcement_ordinal ==
					output->identity->announcement_ordinal) return false;
		}
	}
	return true;
}

static const struct wtwm_output_topology_output *find_ordinal(
		const struct wtwm_output_topology_snapshot *snapshot, uint64_t ordinal) {
	for (size_t index = 0; index < snapshot->count; ++index) {
		if (snapshot->outputs[index].identity->announcement_ordinal == ordinal)
			return &snapshot->outputs[index];
	}
	return NULL;
}

static int canonical_index(const struct wtwm_output_topology_snapshot *snapshot,
		const struct wtwm_output_topology_output *selected) {
	if (selected == NULL || !selected->enabled) return -1;
	int result = 0;
	for (size_t index = 0; index < snapshot->count; ++index) {
		const struct wtwm_output_topology_output *candidate =
			&snapshot->outputs[index];
		if (candidate->enabled && compare_identity(candidate->identity,
				selected->identity) < 0) ++result;
	}
	return result;
}

static int compare_record(const void *left, const void *right) {
	const struct wtwm_output_topology_record *a = left;
	const struct wtwm_output_topology_record *b = right;
	const struct wtwm_output_identity *a_identity =
		a->after != NULL ? a->after->identity : a->before->identity;
	const struct wtwm_output_identity *b_identity =
		b->after != NULL ? b->after->identity : b->before->identity;
	return compare_identity(a_identity, b_identity);
}

static bool same_mode(const struct wtwm_output_topology_mode *left,
		const struct wtwm_output_topology_mode *right) {
	return left->width == right->width && left->height == right->height &&
		left->refresh_mhz == right->refresh_mhz;
}

static bool same_layout(const struct wtwm_output_topology_output *left,
		const struct wtwm_output_topology_output *right) {
	return left->x == right->x && left->y == right->y &&
		left->width == right->width && left->height == right->height;
}

static uint32_t changed_fields(struct wtwm_output_topology_record *record) {
	if (record->before == NULL) return WTWM_OUTPUT_TOPOLOGY_ADDED;
	if (record->after == NULL) return WTWM_OUTPUT_TOPOLOGY_REMOVED;
	uint32_t changed = 0;
	if (record->before->enabled != record->after->enabled)
		changed |= record->after->enabled ? WTWM_OUTPUT_TOPOLOGY_ENABLED :
			WTWM_OUTPUT_TOPOLOGY_DISABLED;
	if (!same_mode(&record->before->mode, &record->after->mode))
		changed |= WTWM_OUTPUT_TOPOLOGY_MODE;
	if (record->before->scale != record->after->scale)
		changed |= WTWM_OUTPUT_TOPOLOGY_SCALE;
	if (record->before->transform != record->after->transform)
		changed |= WTWM_OUTPUT_TOPOLOGY_TRANSFORM;
	if (!same_layout(record->before, record->after))
		changed |= WTWM_OUTPUT_TOPOLOGY_LAYOUT;
	if (record->old_index != record->new_index)
		changed |= WTWM_OUTPUT_TOPOLOGY_INDEX;
	return changed;
}

static const struct wtwm_output_topology_output *output_at_canonical_index(
		const struct wtwm_output_topology_snapshot *snapshot, int selected) {
	if (selected < 0) return NULL;
	for (size_t index = 0; index < snapshot->count; ++index) {
		const struct wtwm_output_topology_output *output =
			&snapshot->outputs[index];
		if (canonical_index(snapshot, output) == selected) return output;
	}
	return NULL;
}

void wtwm_output_topology_plan_init(struct wtwm_output_topology_plan *plan) {
	if (plan != NULL) *plan = (struct wtwm_output_topology_plan){0};
}

void wtwm_output_topology_plan_finish(struct wtwm_output_topology_plan *plan) {
	if (plan == NULL) return;
	free(plan->records);
	wtwm_output_topology_plan_init(plan);
}

static bool plan_is_initialized(const struct wtwm_output_topology_plan *plan) {
	return plan != NULL && plan->records == NULL && plan->count == 0 &&
		plan->old_enabled_count == 0 && plan->new_enabled_count == 0 &&
		plan->changed == 0 && plan->previous == 0 &&
		plan->history == WTWM_OUTPUT_HISTORY_UNSET;
}

bool wtwm_output_topology_plan_build(
		const struct wtwm_output_topology_snapshot *before,
		const struct wtwm_output_topology_snapshot *after, int previous,
		struct wtwm_output_topology_plan *plan) {
	if (!plan_is_initialized(plan)) return false;
	size_t old_enabled_count = 0, new_enabled_count = 0;
	if (!valid_snapshot(before, &old_enabled_count) ||
			!valid_snapshot(after, &new_enabled_count) ||
			before->count > SIZE_MAX - after->count) return false;

	struct wtwm_output_topology_plan result = {
		.old_enabled_count = old_enabled_count,
		.new_enabled_count = new_enabled_count,
		.previous = -1,
	};
	size_t capacity = before->count + after->count;
	if (capacity > SIZE_MAX / sizeof(result.records[0])) return false;
	if (capacity > 0) {
		result.records = calloc(capacity, sizeof(result.records[0]));
		if (result.records == NULL) return false;
	}

	for (size_t index = 0; index < before->count; ++index) {
		result.records[result.count++].before = &before->outputs[index];
	}
	for (size_t index = 0; index < after->count; ++index) {
		const struct wtwm_output_topology_output *new_output =
			&after->outputs[index];
		const struct wtwm_output_topology_output *old_output = find_ordinal(before,
			new_output->identity->announcement_ordinal);
		if (old_output != NULL && !same_identity(old_output->identity,
				new_output->identity)) {
			free(result.records);
			return false;
		}
		if (old_output == NULL) {
			result.records[result.count++].after = new_output;
			continue;
		}
		for (size_t record = 0; record < result.count; ++record) {
			if (result.records[record].before == old_output) {
				result.records[record].after = new_output;
				break;
			}
		}
	}

	for (size_t index = 0; index < result.count; ++index) {
		struct wtwm_output_topology_record *record = &result.records[index];
		record->old_index = canonical_index(before, record->before);
		record->new_index = canonical_index(after, record->after);
		record->changed = changed_fields(record);
		result.changed |= record->changed;
	}
	if (result.count > 1)
		qsort(result.records, result.count, sizeof(result.records[0]),
			compare_record);

	if (previous == -1) {
		result.history = WTWM_OUTPUT_HISTORY_UNSET;
	} else {
		const struct wtwm_output_topology_output *old_previous =
			output_at_canonical_index(before, previous);
		const struct wtwm_output_topology_output *new_previous =
			old_previous != NULL ? find_ordinal(after,
				old_previous->identity->announcement_ordinal) : NULL;
		if (new_previous == NULL || !new_previous->enabled) {
			result.history = WTWM_OUTPUT_HISTORY_INVALIDATED;
		} else {
			result.previous = canonical_index(after, new_previous);
			result.history = result.previous == previous ?
				WTWM_OUTPUT_HISTORY_PRESERVED :
				WTWM_OUTPUT_HISTORY_RENUMBERED;
		}
	}
	*plan = result;
	return true;
}
