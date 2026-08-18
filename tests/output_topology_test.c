/* SPDX-License-Identifier: MIT */

#include <wtwm/output_topology.h>

#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

static struct wtwm_output_identity identity(const char *name,
		uint64_t ordinal) {
	return (struct wtwm_output_identity){
		.name = (char *)name,
		.make = "make",
		.model = "model",
		.serial = "serial",
		.announcement_ordinal = ordinal,
	};
}

static struct wtwm_output_topology_output enabled(
		const struct wtwm_output_identity *identity, int x) {
	return (struct wtwm_output_topology_output){
		.identity = identity,
		.enabled = true,
		.mode = {1920, 1080, 60000},
		.scale = 1.0,
		.transform = WTWM_OUTPUT_TRANSFORM_NORMAL,
		.x = x,
		.y = 0,
		.width = 1920,
		.height = 1080,
	};
}

static struct wtwm_output_topology_output disabled(
		const struct wtwm_output_identity *identity) {
	struct wtwm_output_topology_output output = enabled(identity, 0);
	output.enabled = false;
	output.x = 0;
	output.y = 0;
	output.width = 0;
	output.height = 0;
	return output;
}

static const struct wtwm_output_topology_record *record_named(
		const struct wtwm_output_topology_plan *plan, const char *name) {
	for (size_t index = 0; index < plan->count; ++index) {
		const struct wtwm_output_topology_output *output =
			plan->records[index].after != NULL ? plan->records[index].after :
			plan->records[index].before;
		if (strcmp(output->identity->name, name) == 0)
			return &plan->records[index];
	}
	return NULL;
}

static void canonical_add_remove_and_history(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_identity aardvark = identity("aardvark", 2);
	struct wtwm_output_identity charlie = identity("charlie", 3);
	struct wtwm_output_topology_output old_outputs[] = {
		enabled(&bravo, 1920), enabled(&alpha, 0),
	};
	struct wtwm_output_topology_output new_outputs[] = {
		enabled(&charlie, 3840), enabled(&alpha, 0),
		enabled(&aardvark, -1920),
	};
	struct wtwm_output_topology_snapshot before = {old_outputs, 2};
	struct wtwm_output_topology_snapshot after = {new_outputs, 3};
	struct wtwm_output_topology_plan plan;
	wtwm_output_topology_plan_init(&plan);
	assert(wtwm_output_topology_plan_build(&before, &after, 0, &plan));
	assert(plan.count == 4 && plan.old_enabled_count == 2 &&
		plan.new_enabled_count == 3);
	assert(plan.changed == (WTWM_OUTPUT_TOPOLOGY_ADDED |
		WTWM_OUTPUT_TOPOLOGY_REMOVED | WTWM_OUTPUT_TOPOLOGY_INDEX));
	const struct wtwm_output_topology_record *item = record_named(&plan,
		"aardvark");
	assert(item != NULL && item->changed == WTWM_OUTPUT_TOPOLOGY_ADDED &&
		item->old_index == -1 && item->new_index == 0);
	item = record_named(&plan, "alpha");
	assert(item != NULL && item->changed == WTWM_OUTPUT_TOPOLOGY_INDEX &&
		item->old_index == 0 && item->new_index == 1);
	item = record_named(&plan, "bravo");
	assert(item != NULL && item->changed == WTWM_OUTPUT_TOPOLOGY_REMOVED &&
		item->old_index == 1 && item->new_index == -1);
	item = record_named(&plan, "charlie");
	assert(item != NULL && item->changed == WTWM_OUTPUT_TOPOLOGY_ADDED &&
		item->new_index == 2);
	assert(plan.previous == 1 &&
		plan.history == WTWM_OUTPUT_HISTORY_RENUMBERED);
	wtwm_output_topology_plan_finish(&plan);
	assert(wtwm_output_topology_plan_build(&before, &after, 1, &plan));
	assert(plan.previous == -1 &&
		plan.history == WTWM_OUTPUT_HISTORY_INVALIDATED);
	wtwm_output_topology_plan_finish(&plan);
}

static void enable_disable_and_invalidate(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_topology_output old_outputs[] = {
		disabled(&bravo), enabled(&alpha, 0),
	};
	struct wtwm_output_topology_output new_outputs[] = {
		disabled(&alpha), enabled(&bravo, 0),
	};
	struct wtwm_output_topology_snapshot before = {old_outputs, 2};
	struct wtwm_output_topology_snapshot after = {new_outputs, 2};
	struct wtwm_output_topology_plan plan = {0};
	assert(wtwm_output_topology_plan_build(&before, &after, 0, &plan));
	const struct wtwm_output_topology_record *item = record_named(&plan,
		"alpha");
	assert(item != NULL && item->changed == (WTWM_OUTPUT_TOPOLOGY_DISABLED |
		WTWM_OUTPUT_TOPOLOGY_LAYOUT | WTWM_OUTPUT_TOPOLOGY_INDEX));
	assert(item->old_index == 0 && item->new_index == -1);
	item = record_named(&plan, "bravo");
	assert(item != NULL && item->changed == (WTWM_OUTPUT_TOPOLOGY_ENABLED |
		WTWM_OUTPUT_TOPOLOGY_LAYOUT | WTWM_OUTPUT_TOPOLOGY_INDEX));
	assert(item->old_index == -1 && item->new_index == 0);
	assert(plan.previous == -1 &&
		plan.history == WTWM_OUTPUT_HISTORY_INVALIDATED);
	wtwm_output_topology_plan_finish(&plan);
}

static void property_changes_and_stable_order(void) {
	struct wtwm_output_identity alpha = identity("alpha", 9);
	struct wtwm_output_topology_output old_output = enabled(&alpha, INT_MIN);
	struct wtwm_output_topology_output new_output = old_output;
	new_output.mode.width = 3840;
	new_output.mode.height = 2160;
	new_output.mode.refresh_mhz = 120000;
	new_output.scale = 1.5;
	new_output.transform = WTWM_OUTPUT_TRANSFORM_FLIPPED_90;
	new_output.x = INT_MAX;
	new_output.y = INT_MIN;
	new_output.width = INT_MAX;
	new_output.height = INT_MAX;
	struct wtwm_output_topology_snapshot before = {&old_output, 1};
	struct wtwm_output_topology_snapshot after = {&new_output, 1};
	struct wtwm_output_topology_plan plan = {0};
	assert(wtwm_output_topology_plan_build(&before, &after, 0, &plan));
	assert(plan.count == 1 && plan.changed == (WTWM_OUTPUT_TOPOLOGY_MODE |
		WTWM_OUTPUT_TOPOLOGY_SCALE | WTWM_OUTPUT_TOPOLOGY_TRANSFORM |
		WTWM_OUTPUT_TOPOLOGY_LAYOUT));
	assert(plan.records[0].old_index == 0 && plan.records[0].new_index == 0);
	assert(plan.previous == 0 &&
		plan.history == WTWM_OUTPUT_HISTORY_PRESERVED);
	wtwm_output_topology_plan_finish(&plan);
}

static void renumber_history_by_identity(void) {
	struct wtwm_output_identity bravo = identity("bravo", 0);
	struct wtwm_output_identity charlie = identity("charlie", 1);
	struct wtwm_output_identity alpha = identity("alpha", 2);
	struct wtwm_output_topology_output old_outputs[] = {
		enabled(&charlie, 1920), enabled(&bravo, 0),
	};
	struct wtwm_output_topology_output new_outputs[] = {
		enabled(&alpha, -1920), enabled(&bravo, 0), enabled(&charlie, 1920),
	};
	struct wtwm_output_topology_snapshot before = {old_outputs, 2};
	struct wtwm_output_topology_snapshot after = {new_outputs, 3};
	struct wtwm_output_topology_plan plan = {0};
	assert(wtwm_output_topology_plan_build(&before, &after, 1, &plan));
	assert(plan.previous == 2 &&
		plan.history == WTWM_OUTPUT_HISTORY_RENUMBERED);
	const struct wtwm_output_topology_record *item = record_named(&plan,
		"charlie");
	assert(item != NULL && item->old_index == 1 && item->new_index == 2 &&
		item->changed == WTWM_OUTPUT_TOPOLOGY_INDEX);
	wtwm_output_topology_plan_finish(&plan);
}

static void zero_output_cases(void) {
	struct wtwm_output_topology_snapshot empty = {0};
	struct wtwm_output_topology_plan plan = {0};
	assert(wtwm_output_topology_plan_build(&empty, &empty, -1, &plan));
	assert(plan.records == NULL && plan.count == 0 && plan.changed == 0 &&
		plan.old_enabled_count == 0 && plan.new_enabled_count == 0 &&
		plan.previous == -1 && plan.history == WTWM_OUTPUT_HISTORY_UNSET);
	wtwm_output_topology_plan_finish(&plan);
	assert(wtwm_output_topology_plan_build(&empty, &empty, 0, &plan));
	assert(plan.previous == -1 &&
		plan.history == WTWM_OUTPUT_HISTORY_INVALIDATED);
	wtwm_output_topology_plan_finish(&plan);
	wtwm_output_topology_plan_finish(NULL);
}

static void unchanged_reversed_input(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_topology_output old_outputs[] = {
		enabled(&alpha, 0), enabled(&bravo, 1920),
	};
	struct wtwm_output_topology_output new_outputs[] = {
		enabled(&bravo, 1920), enabled(&alpha, 0),
	};
	struct wtwm_output_topology_snapshot before = {old_outputs, 2};
	struct wtwm_output_topology_snapshot after = {new_outputs, 2};
	struct wtwm_output_topology_plan plan = {0};
	assert(wtwm_output_topology_plan_build(&before, &after, -1, &plan));
	assert(plan.count == 2 && plan.changed == 0);
	assert(strcmp(plan.records[0].after->identity->name, "alpha") == 0);
	assert(strcmp(plan.records[1].after->identity->name, "bravo") == 0);
	assert(plan.records[0].old_index == 0 && plan.records[0].new_index == 0);
	assert(plan.records[1].old_index == 1 && plan.records[1].new_index == 1);
	wtwm_output_topology_plan_finish(&plan);
}

static void assert_invalid_unchanged(
		const struct wtwm_output_topology_snapshot *before,
		const struct wtwm_output_topology_snapshot *after) {
	struct wtwm_output_topology_plan plan;
	wtwm_output_topology_plan_init(&plan);
	struct wtwm_output_topology_plan saved = plan;
	assert(!wtwm_output_topology_plan_build(before, after, -1, &plan));
	assert(memcmp(&plan, &saved, sizeof(plan)) == 0);
}

static void invalid_snapshots_are_atomic(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity changed = identity("changed", 0);
	struct wtwm_output_topology_output valid = enabled(&alpha, 0);
	struct wtwm_output_topology_output invalid = valid;
	struct wtwm_output_topology_snapshot good = {&valid, 1};
	struct wtwm_output_topology_snapshot bad = {&invalid, 1};
	assert_invalid_unchanged(NULL, &good);
	struct wtwm_output_topology_snapshot missing = {NULL, 1};
	assert_invalid_unchanged(&good, &missing);

	invalid.identity = NULL;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.mode.width = 0;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.scale = 0.0;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.scale = NAN;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.scale = INFINITY;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.scale = 16.0001;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.transform = (enum wtwm_output_transform)8;
	assert_invalid_unchanged(&good, &bad);
	invalid = valid;
	invalid.width = 0;
	assert_invalid_unchanged(&good, &bad);
	invalid = disabled(&alpha);
	invalid.x = 1;
	assert_invalid_unchanged(&good, &bad);

	struct wtwm_output_topology_output duplicates[] = {valid, valid};
	struct wtwm_output_topology_snapshot duplicate = {duplicates, 2};
	assert_invalid_unchanged(&good, &duplicate);
	invalid = valid;
	invalid.identity = &changed;
	assert_invalid_unchanged(&good, &bad);

	struct wtwm_output_topology_plan occupied = {0};
	assert(wtwm_output_topology_plan_build(&good, &good, -1, &occupied));
	struct wtwm_output_topology_plan saved = occupied;
	assert(!wtwm_output_topology_plan_build(&good, &good, -1, &occupied));
	assert(memcmp(&occupied, &saved, sizeof(occupied)) == 0);
	wtwm_output_topology_plan_finish(&occupied);
}

int main(void) {
	canonical_add_remove_and_history();
	enable_disable_and_invalidate();
	property_changes_and_stable_order();
	renumber_history_by_identity();
	zero_output_cases();
	unchanged_reversed_input();
	invalid_snapshots_are_atomic();
	return 0;
}
