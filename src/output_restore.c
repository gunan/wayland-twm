/* SPDX-License-Identifier: MIT */

#include "wtwm/output_restore.h"

#include <wtwm/placement.h>

#include <limits.h>
#include <stdint.h>
#include <stdlib.h>

struct restore_snapshot {
	const struct wtwm_output_restore_snapshot *snapshot;
	struct wtwm_placement_area *areas;
};

struct spatial_plan {
	struct wtwm_restore_box box;
	int source;
	int target;
	int64_t dx;
	int64_t dy;
	bool changed;
	bool stranded;
	bool pending;
};

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

static bool valid_box(const struct wtwm_restore_box *box) {
	return box->width > 0 && box->height > 0;
}

static bool valid_snapshot(const struct wtwm_output_restore_snapshot *snapshot) {
	if (snapshot == NULL || snapshot->count > (size_t)INT_MAX ||
			(snapshot->count > 0 && snapshot->outputs == NULL)) return false;
	for (size_t index = 0; index < snapshot->count; ++index) {
		const struct wtwm_output_restore_output *output =
			&snapshot->outputs[index];
		if (output->identity == NULL || !valid_box(&output->box)) return false;
		if (index > 0 && compare_identity(
				snapshot->outputs[index - 1].identity, output->identity) >= 0)
			return false;
		for (size_t prior = 0; prior < index; ++prior) {
			if (snapshot->outputs[prior].identity->announcement_ordinal ==
					output->identity->announcement_ordinal) return false;
		}
	}
	return true;
}

static const struct wtwm_output_restore_output *find_ordinal(
		const struct wtwm_output_restore_snapshot *snapshot, uint64_t ordinal,
		int *selected) {
	for (size_t index = 0; index < snapshot->count; ++index) {
		if (snapshot->outputs[index].identity->announcement_ordinal == ordinal) {
			if (selected != NULL) *selected = (int)index;
			return &snapshot->outputs[index];
		}
	}
	return NULL;
}

static bool stable_survivors(
		const struct wtwm_output_restore_snapshot *before,
		const struct wtwm_output_restore_snapshot *after) {
	for (size_t index = 0; index < after->count; ++index) {
		const struct wtwm_output_restore_output *old_output = find_ordinal(before,
			after->outputs[index].identity->announcement_ordinal, NULL);
		if (old_output != NULL && compare_identity(old_output->identity,
				after->outputs[index].identity) != 0) return false;
	}
	return true;
}

static bool valid_clients(const struct wtwm_output_restore_client *clients,
		size_t count) {
	if (count > (size_t)INT_MAX || (count > 0 && clients == NULL)) return false;
	for (size_t index = 0; index < count; ++index) {
		const struct wtwm_output_restore_client *client = &clients[index];
		if (!valid_box(&client->frame) || client->parent < -1 ||
				client->parent >= (int)count || client->parent == (int)index ||
				(client->icon_visible && !valid_box(&client->icon)) ||
				(client->zoom_restore_valid &&
				!valid_box(&client->zoom_restore))) return false;
		int parent = client->parent;
		for (size_t depth = 0; parent >= 0; ++depth) {
			if (depth >= count || parent >= (int)count) return false;
			parent = clients[parent].parent;
		}
	}
	return true;
}

static bool snapshot_init(struct restore_snapshot *result,
		const struct wtwm_output_restore_snapshot *snapshot) {
	*result = (struct restore_snapshot){.snapshot = snapshot};
	if (snapshot->count == 0) return true;
	result->areas = calloc(snapshot->count, sizeof(result->areas[0]));
	if (result->areas == NULL) return false;
	for (size_t index = 0; index < snapshot->count; ++index) {
		const struct wtwm_restore_box *box = &snapshot->outputs[index].box;
		result->areas[index] = (struct wtwm_placement_area){
			.x = box->x,
			.y = box->y,
			.width = box->width,
			.height = box->height,
		};
	}
	return true;
}

static void snapshot_finish(struct restore_snapshot *snapshot) {
	free(snapshot->areas);
	*snapshot = (struct restore_snapshot){0};
}

static bool positive_intersection(const struct wtwm_placement_area *area,
		const struct wtwm_restore_box *box) {
	int64_t left = area->x > box->x ? area->x : box->x;
	int64_t top = area->y > box->y ? area->y : box->y;
	int64_t area_right = (int64_t)area->x + area->width;
	int64_t area_bottom = (int64_t)area->y + area->height;
	int64_t box_right = (int64_t)box->x + box->width;
	int64_t box_bottom = (int64_t)box->y + box->height;
	int64_t right = area_right < box_right ? area_right : box_right;
	int64_t bottom = area_bottom < box_bottom ? area_bottom : box_bottom;
	return right > left && bottom > top;
}

static bool visible_in_snapshot(const struct restore_snapshot *snapshot,
		const struct wtwm_restore_box *box) {
	for (size_t index = 0; index < snapshot->snapshot->count; ++index) {
		if (positive_intersection(&snapshot->areas[index], box)) return true;
	}
	return false;
}

static int select_output(const struct restore_snapshot *snapshot,
		const struct wtwm_restore_box *box) {
	if (snapshot->snapshot->count == 0) return -1;
	size_t selected = 0;
	if (!wtwm_placement_output_for_outer(snapshot->areas,
			snapshot->snapshot->count, box->x, box->y, box->width,
			box->height, &selected)) return -1;
	return selected <= (size_t)INT_MAX ? (int)selected : -1;
}

static int saturate_int(int64_t value) {
	if (value < INT_MIN) return INT_MIN;
	if (value > INT_MAX) return INT_MAX;
	return (int)value;
}

static int clamp_axis(int64_t candidate, int size, int origin, int extent) {
	if (size > extent) return origin;
	int64_t maximum = (int64_t)origin + extent - size;
	if (candidate < origin) candidate = origin;
	if (candidate > maximum) candidate = maximum;
	return saturate_int(candidate);
}

static struct wtwm_restore_box clamp_box(struct wtwm_restore_box box,
		int64_t candidate_x, int64_t candidate_y,
		const struct wtwm_placement_area *target) {
	box.x = clamp_axis(candidate_x, box.width, target->x, target->width);
	box.y = clamp_axis(candidate_y, box.height, target->y, target->height);
	return box;
}

static bool same_box(const struct wtwm_restore_box *left,
		const struct wtwm_restore_box *right) {
	return left->x == right->x && left->y == right->y &&
		left->width == right->width && left->height == right->height;
}

static bool same_area_box(const struct wtwm_output_restore_output *left,
		const struct wtwm_output_restore_output *right) {
	return same_box(&left->box, &right->box);
}

static struct spatial_plan plan_box(const struct restore_snapshot *before,
		const struct restore_snapshot *after,
		const struct wtwm_restore_box *box) {
	struct spatial_plan result = {
		.box = *box,
		.source = select_output(before, box),
		.target = -1,
	};
	if (after->snapshot->count == 0) {
		result.pending = true;
		return result;
	}
	result.target = select_output(after, box);
	if (visible_in_snapshot(after, box)) return result;
	result.stranded = true;
	if (result.source >= 0) {
		const struct wtwm_output_restore_output *source =
			&before->snapshot->outputs[result.source];
		int surviving = -1;
		if (find_ordinal(after->snapshot,
				source->identity->announcement_ordinal, &surviving) != NULL)
			result.target = surviving;
	}
	const struct wtwm_placement_area *target = &after->areas[result.target];
	int64_t candidate_x = box->x;
	int64_t candidate_y = box->y;
	if (result.source >= 0) {
		const struct wtwm_placement_area *source = &before->areas[result.source];
		candidate_x = (int64_t)target->x + ((int64_t)box->x - source->x);
		candidate_y = (int64_t)target->y + ((int64_t)box->y - source->y);
	}
	result.box = clamp_box(*box, candidate_x, candidate_y, target);
	result.changed = !same_box(&result.box, box);
	result.dx = (int64_t)result.box.x - box->x;
	result.dy = (int64_t)result.box.y - box->y;
	return result;
}

static struct spatial_plan plan_zoom_frame(
		const struct restore_snapshot *before,
		const struct restore_snapshot *after,
		const struct wtwm_restore_box *box, bool *recompute) {
	struct spatial_plan result = plan_box(before, after, box);
	*recompute = false;
	if (result.pending) return result;
	int target = -1;
	const struct wtwm_output_restore_output *old_owner = result.source >= 0 ?
		&before->snapshot->outputs[result.source] : NULL;
	const struct wtwm_output_restore_output *new_owner = old_owner != NULL ?
		find_ordinal(after->snapshot,
			old_owner->identity->announcement_ordinal, &target) : NULL;
	if (new_owner != NULL && same_area_box(old_owner, new_owner)) {
		result.box = *box;
		result.target = target;
		result.dx = 0;
		result.dy = 0;
		result.changed = false;
		return result;
	}
	*recompute = true;
	if (new_owner == NULL) target = select_output(after, box);
	result.target = target;
	const struct wtwm_placement_area *target_area = &after->areas[target];
	int64_t candidate_x = box->x;
	int64_t candidate_y = box->y;
	if (result.source >= 0) {
		const struct wtwm_placement_area *source = &before->areas[result.source];
		candidate_x = (int64_t)target_area->x + ((int64_t)box->x - source->x);
		candidate_y = (int64_t)target_area->y + ((int64_t)box->y - source->y);
	}
	result.box = clamp_box(*box, candidate_x, candidate_y, target_area);
	result.changed = !same_box(&result.box, box);
	result.stranded = !visible_in_snapshot(after, box);
	result.dx = (int64_t)result.box.x - box->x;
	result.dy = (int64_t)result.box.y - box->y;
	return result;
}

static int family_root(const struct wtwm_output_restore_client *clients,
		int index) {
	while (clients[index].parent >= 0) index = clients[index].parent;
	return index;
}

static struct spatial_plan plan_family_member(
		const struct restore_snapshot *before,
		const struct restore_snapshot *after,
		const struct wtwm_restore_box *box, const struct spatial_plan *root,
		bool repair_family) {
	struct spatial_plan result = {
		.box = *box,
		.source = select_output(before, box),
		.target = -1,
	};
	if (after->snapshot->count == 0) {
		result.pending = true;
		return result;
	}
	result.target = select_output(after, box);
	bool stranded = !visible_in_snapshot(after, box);
	if (!repair_family && !stranded) return result;
	result.stranded = stranded;
	result.target = root->target;
	int64_t candidate_x = (int64_t)box->x +
		(repair_family ? root->dx : 0);
	int64_t candidate_y = (int64_t)box->y +
		(repair_family ? root->dy : 0);
	result.box = clamp_box(*box, candidate_x, candidate_y,
		&after->areas[result.target]);
	result.changed = !same_box(&result.box, box);
	result.dx = (int64_t)result.box.x - box->x;
	result.dy = (int64_t)result.box.y - box->y;
	return result;
}

void wtwm_output_restore_plan_init(struct wtwm_output_restore_plan *plan) {
	if (plan != NULL) *plan = (struct wtwm_output_restore_plan){0};
}

void wtwm_output_restore_plan_finish(struct wtwm_output_restore_plan *plan) {
	if (plan == NULL) return;
	free(plan->records);
	wtwm_output_restore_plan_init(plan);
}

static bool plan_is_initialized(const struct wtwm_output_restore_plan *plan) {
	return plan != NULL && plan->records == NULL && plan->count == 0 &&
		!plan->pending && !plan->built;
}

bool wtwm_output_restore_plan_build(
		const struct wtwm_output_restore_snapshot *before_snapshot,
		const struct wtwm_output_restore_snapshot *after_snapshot,
		const struct wtwm_output_restore_client *clients, size_t client_count,
		struct wtwm_output_restore_plan *plan) {
	if (!plan_is_initialized(plan) || !valid_snapshot(before_snapshot) ||
			!valid_snapshot(after_snapshot) ||
			!stable_survivors(before_snapshot, after_snapshot) ||
			!valid_clients(clients, client_count)) return false;
	struct restore_snapshot before = {0}, after = {0};
	if (!snapshot_init(&before, before_snapshot) ||
			!snapshot_init(&after, after_snapshot)) {
		snapshot_finish(&before);
		snapshot_finish(&after);
		return false;
	}
	struct wtwm_output_restore_plan result = {
		.count = client_count,
		.pending = after_snapshot->count == 0,
		.built = true,
	};
	if (client_count > SIZE_MAX / sizeof(result.records[0])) {
		snapshot_finish(&before);
		snapshot_finish(&after);
		return false;
	}
	if (client_count > 0) {
		result.records = calloc(client_count, sizeof(result.records[0]));
		if (result.records == NULL) {
			snapshot_finish(&before);
			snapshot_finish(&after);
			return false;
		}
	}

	for (size_t index = 0; index < client_count; ++index) {
		if (clients[index].parent >= 0) continue;
		struct wtwm_output_restore_record *record = &result.records[index];
		struct spatial_plan frame = clients[index].zoomed ?
			plan_zoom_frame(&before, &after, &clients[index].frame,
				&record->recompute_zoom) :
			plan_box(&before, &after, &clients[index].frame);
		record->frame = frame.box;
		record->source_output = frame.source;
		record->target_output = frame.target;
		record->frame_dx = frame.dx;
		record->frame_dy = frame.dy;
		record->frame_changed = frame.changed;
		record->pending = frame.pending;
	}

	for (size_t index = 0; index < client_count; ++index) {
		if (clients[index].parent < 0) continue;
		int root_index = family_root(clients, (int)index);
		const struct wtwm_output_restore_record *root_record =
			&result.records[root_index];
		struct spatial_plan root = {
			.box = root_record->frame,
			.source = root_record->source_output,
			.target = root_record->target_output,
			.dx = root_record->frame_dx,
			.dy = root_record->frame_dy,
			.changed = root_record->frame_changed,
			.pending = root_record->pending,
		};
		bool repair_family = !visible_in_snapshot(&after,
			&clients[root_index].frame) || root_record->recompute_zoom;
		struct wtwm_output_restore_record *record = &result.records[index];
		struct spatial_plan frame = plan_family_member(&before, &after,
			&clients[index].frame, &root, repair_family);
		record->frame = frame.box;
		record->source_output = frame.source;
		record->target_output = frame.target;
		record->frame_dx = frame.dx;
		record->frame_dy = frame.dy;
		record->frame_changed = frame.changed;
		record->pending = frame.pending;
		if (clients[index].zoomed && !frame.pending) {
			int surviving = -1;
			const struct wtwm_output_restore_output *old_owner =
				frame.source >= 0 ? &before_snapshot->outputs[frame.source] : NULL;
			const struct wtwm_output_restore_output *new_owner =
				old_owner != NULL ? find_ordinal(after_snapshot,
					old_owner->identity->announcement_ordinal, &surviving) : NULL;
			record->recompute_zoom = repair_family || old_owner == NULL ||
				new_owner == NULL || !same_area_box(old_owner, new_owner);
			if (record->recompute_zoom)
				record->target_output = root.target;
		}
	}

	for (size_t index = 0; index < client_count; ++index) {
		struct wtwm_output_restore_record *record = &result.records[index];
		if (clients[index].icon_visible) {
			struct spatial_plan icon = plan_box(&before, &after,
				&clients[index].icon);
			record->icon = icon.box;
			record->icon_source_output = icon.source;
			record->icon_target_output = icon.target;
			record->icon_changed = icon.changed;
		} else {
			record->icon = clients[index].icon;
			record->icon_source_output = -1;
			record->icon_target_output = -1;
		}
		if (clients[index].zoom_restore_valid) {
			struct spatial_plan saved = plan_box(&before, &after,
				&clients[index].zoom_restore);
			record->zoom_restore = saved.box;
			record->zoom_restore_source_output = saved.source;
			record->zoom_restore_target_output = saved.target;
			record->zoom_restore_changed = saved.changed;
		} else {
			record->zoom_restore = clients[index].zoom_restore;
			record->zoom_restore_source_output = -1;
			record->zoom_restore_target_output = -1;
		}
	}

	snapshot_finish(&before);
	snapshot_finish(&after);
	*plan = result;
	return true;
}
