/* SPDX-License-Identifier: MIT */

#include <wtwm/output_restore.h>

#include <assert.h>
#include <limits.h>
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

static struct wtwm_output_restore_output output(
		const struct wtwm_output_identity *identity, int x, int y,
		int width, int height) {
	return (struct wtwm_output_restore_output){
		.identity = identity,
		.box = {x, y, width, height},
	};
}

static struct wtwm_output_restore_client client(int parent, int x, int y,
		int width, int height) {
	return (struct wtwm_output_restore_client){
		.parent = parent,
		.frame = {x, y, width, height},
	};
}

static void assert_box(struct wtwm_restore_box box, int x, int y,
		int width, int height) {
	assert(box.x == x);
	assert(box.y == y);
	assert(box.width == width);
	assert(box.height == height);
}

static void disappeared_output_family(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output old_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
	};
	struct wtwm_output_restore_output new_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {old_outputs, 2};
	struct wtwm_output_restore_snapshot after = {&new_output, 1};
	struct wtwm_output_restore_client clients[] = {
		client(-1, 370, 40, 100, 100),
		client(0, 400, 70, 80, 60),
	};
	struct wtwm_output_restore_client saved_clients[2];
	memcpy(saved_clients, clients, sizeof(clients));
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, clients, 2, &plan));
	assert(!plan.pending && plan.count == 2);
	assert_box(plan.records[0].frame, 50, 40, 100, 100);
	assert(plan.records[0].source_output == 1 &&
		plan.records[0].target_output == 0 && plan.records[0].frame_changed);
	assert(plan.records[0].frame_dx == -320 && plan.records[0].frame_dy == 0);
	assert_box(plan.records[1].frame, 80, 70, 80, 60);
	assert(plan.records[1].target_output == 0 &&
		plan.records[1].frame_changed);
	assert(memcmp(saved_clients, clients, sizeof(clients)) == 0);
	wtwm_output_restore_plan_finish(&plan);
}

static void surviving_owner_and_no_repatriation(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output old_output =
		output(&alpha, 320, 0, 320, 240);
	struct wtwm_output_restore_output moved_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {&old_output, 1};
	struct wtwm_output_restore_snapshot after = {&moved_output, 1};
	struct wtwm_output_restore_client value = client(-1, 370, 40, 100, 80);
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert_box(plan.records[0].frame, 50, 40, 100, 80);
	assert(plan.records[0].source_output == 0 &&
		plan.records[0].target_output == 0);
	wtwm_output_restore_plan_finish(&plan);

	old_output = output(&alpha, 0, 0, 320, 240);
	moved_output = output(&alpha, 0, 0, 200, 160);
	value = client(-1, 180, 40, 100, 80);
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert_box(plan.records[0].frame, 180, 40, 100, 80);
	assert(!plan.records[0].frame_changed);
	wtwm_output_restore_plan_finish(&plan);

	struct wtwm_output_restore_output returned_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
	};
	old_output = returned_outputs[0];
	after = (struct wtwm_output_restore_snapshot){returned_outputs, 2};
	value = client(-1, 40, 40, 100, 80);
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert_box(plan.records[0].frame, 40, 40, 100, 80);
	assert(!plan.records[0].frame_changed);
	wtwm_output_restore_plan_finish(&plan);
}

static void visible_geometry_is_exact(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output old_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
	};
	struct wtwm_output_restore_output new_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {old_outputs, 2};
	struct wtwm_output_restore_snapshot after = {&new_output, 1};
	struct wtwm_output_restore_client clients[] = {
		client(-1, 300, 200, 100, 100),
		client(-1, 40, 40, 600, 400),
	};
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, clients, 2, &plan));
	assert_box(plan.records[0].frame, 300, 200, 100, 100);
	assert_box(plan.records[1].frame, 40, 40, 600, 400);
	assert(!plan.records[0].frame_changed && !plan.records[1].frame_changed);
	wtwm_output_restore_plan_finish(&plan);
}

static void clamp_and_oversize(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output old_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
	};
	struct wtwm_output_restore_output new_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {old_outputs, 2};
	struct wtwm_output_restore_snapshot after = {&new_output, 1};
	struct wtwm_output_restore_client clients[] = {
		client(-1, 600, 220, 100, 80),
		client(-1, 700, 300, 500, 400),
	};
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, clients, 2, &plan));
	assert_box(plan.records[0].frame, 220, 160, 100, 80);
	assert_box(plan.records[1].frame, 0, 0, 500, 400);
	wtwm_output_restore_plan_finish(&plan);
}

static void visible_root_repairs_only_stranded_child(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output old_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
	};
	struct wtwm_output_restore_output new_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {old_outputs, 2};
	struct wtwm_output_restore_snapshot after = {&new_output, 1};
	struct wtwm_output_restore_client clients[] = {
		client(-1, 40, 40, 100, 100),
		client(0, 380, 60, 80, 60),
		client(0, 120, 80, 80, 60),
	};
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, clients, 3, &plan));
	assert_box(plan.records[0].frame, 40, 40, 100, 100);
	assert_box(plan.records[1].frame, 240, 60, 80, 60);
	assert_box(plan.records[2].frame, 120, 80, 80, 60);
	assert(!plan.records[0].frame_changed && plan.records[1].frame_changed &&
		!plan.records[2].frame_changed);
	wtwm_output_restore_plan_finish(&plan);
}

static void icons_and_zoom_restore_are_independent(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output old_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
	};
	struct wtwm_output_restore_output new_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {old_outputs, 2};
	struct wtwm_output_restore_snapshot after = {&new_output, 1};
	struct wtwm_output_restore_client value = client(-1, 40, 40, 100, 100);
	value.icon_visible = true;
	value.icon = (struct wtwm_restore_box){500, 180, 60, 40};
	value.zoom_restore_valid = true;
	value.zoom_restore = (struct wtwm_restore_box){600, 220, 120, 80};
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert_box(plan.records[0].frame, 40, 40, 100, 100);
	assert_box(plan.records[0].icon, 180, 180, 60, 40);
	assert_box(plan.records[0].zoom_restore, 200, 160, 120, 80);
	assert(!plan.records[0].frame_changed && plan.records[0].icon_changed &&
		plan.records[0].zoom_restore_changed);
	wtwm_output_restore_plan_finish(&plan);
}

static void zoom_owner_change_recomputes(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_restore_output old_output =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_output new_output =
		output(&alpha, 100, 50, 200, 160);
	struct wtwm_output_restore_snapshot before = {&old_output, 1};
	struct wtwm_output_restore_snapshot after = {&new_output, 1};
	struct wtwm_output_restore_client value = client(-1, 0, 0, 320, 240);
	value.zoomed = true;
	value.zoom_restore_valid = true;
	value.zoom_restore = (struct wtwm_restore_box){40, 40, 100, 80};
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert(plan.records[0].recompute_zoom && plan.records[0].target_output == 0);
	assert_box(plan.records[0].frame, 100, 50, 320, 240);
	assert_box(plan.records[0].zoom_restore, 40, 40, 100, 80);
	wtwm_output_restore_plan_finish(&plan);

	after = before;
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert(!plan.records[0].recompute_zoom &&
		!plan.records[0].frame_changed);
	wtwm_output_restore_plan_finish(&plan);
}

static void zero_outputs_and_reappearance(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_restore_output old_output =
		output(&alpha, 320, 0, 320, 240);
	struct wtwm_output_restore_snapshot before = {&old_output, 1};
	struct wtwm_output_restore_snapshot empty = {0};
	struct wtwm_output_restore_client value = client(-1, 370, 40, 100, 80);
	value.icon_visible = true;
	value.icon = (struct wtwm_restore_box){500, 180, 60, 40};
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &empty, &value, 1, &plan));
	assert(plan.pending && plan.records[0].pending);
	assert_box(plan.records[0].frame, 370, 40, 100, 80);
	assert_box(plan.records[0].icon, 500, 180, 60, 40);
	wtwm_output_restore_plan_finish(&plan);

	struct wtwm_output_restore_output returned =
		output(&alpha, -200, -100, 200, 160);
	struct wtwm_output_restore_snapshot after = {&returned, 1};
	assert(wtwm_output_restore_plan_build(&empty, &after, &value, 1, &plan));
	assert(!plan.pending && plan.records[0].frame_changed);
	assert_box(plan.records[0].frame, -100, -20, 100, 80);
	wtwm_output_restore_plan_finish(&plan);
}

static void canonical_nearest_tie_and_extremes(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_identity charlie = identity("charlie", 2);
	struct wtwm_output_restore_output old_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&bravo, 320, 0, 320, 240),
		output(&charlie, 640, 0, 320, 240),
	};
	struct wtwm_output_restore_output new_outputs[] = {
		output(&alpha, 0, 0, 320, 240), output(&charlie, 640, 0, 320, 240),
	};
	struct wtwm_output_restore_snapshot before = {old_outputs, 3};
	struct wtwm_output_restore_snapshot after = {new_outputs, 2};
	struct wtwm_output_restore_client value = client(-1, 460, 300, 40, 40);
	struct wtwm_output_restore_plan plan = {0};
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert(plan.records[0].target_output == 0);
	assert_box(plan.records[0].frame, 140, 200, 40, 40);
	wtwm_output_restore_plan_finish(&plan);

	struct wtwm_output_restore_output extreme_old =
		output(&alpha, INT_MAX, INT_MAX, 1, 1);
	struct wtwm_output_restore_output extreme_new =
		output(&alpha, INT_MIN, INT_MIN, INT_MAX, INT_MAX);
	before = (struct wtwm_output_restore_snapshot){&extreme_old, 1};
	after = (struct wtwm_output_restore_snapshot){&extreme_new, 1};
	value = client(-1, INT_MAX, INT_MAX, INT_MAX, INT_MAX);
	assert(wtwm_output_restore_plan_build(&before, &after, &value, 1, &plan));
	assert_box(plan.records[0].frame, INT_MIN, INT_MIN, INT_MAX, INT_MAX);
	wtwm_output_restore_plan_finish(&plan);
}

static void invalid_inputs_are_atomic(void) {
	struct wtwm_output_identity alpha = identity("alpha", 0);
	struct wtwm_output_identity changed = identity("changed", 0);
	struct wtwm_output_restore_output output_value =
		output(&alpha, 0, 0, 320, 240);
	struct wtwm_output_restore_snapshot good = {&output_value, 1};
	struct wtwm_output_restore_client client_value = client(-1, 0, 0, 100, 80);
	struct wtwm_output_restore_plan plan = {0};
	struct wtwm_output_restore_plan saved = plan;
	assert(!wtwm_output_restore_plan_build(NULL, &good, &client_value, 1,
		&plan));
	assert(memcmp(&plan, &saved, sizeof(plan)) == 0);

	struct wtwm_output_restore_output bad_output = output_value;
	bad_output.box.width = 0;
	struct wtwm_output_restore_snapshot bad = {&bad_output, 1};
	assert(!wtwm_output_restore_plan_build(&good, &bad, &client_value, 1,
		&plan));
	assert(memcmp(&plan, &saved, sizeof(plan)) == 0);
	bad_output = output_value;
	bad_output.identity = &changed;
	bad = (struct wtwm_output_restore_snapshot){&bad_output, 1};
	assert(!wtwm_output_restore_plan_build(&good, &bad, &client_value, 1,
		&plan));
	struct wtwm_output_identity bravo = identity("bravo", 1);
	struct wtwm_output_restore_output unsorted_outputs[] = {
		output(&bravo, 320, 0, 320, 240), output(&alpha, 0, 0, 320, 240),
	};
	bad = (struct wtwm_output_restore_snapshot){unsorted_outputs, 2};
	assert(!wtwm_output_restore_plan_build(&good, &bad, &client_value, 1,
		&plan));
	struct wtwm_output_identity duplicate_ordinal = identity("zulu", 0);
	struct wtwm_output_restore_output duplicate_outputs[] = {
		output(&alpha, 0, 0, 320, 240),
		output(&duplicate_ordinal, 320, 0, 320, 240),
	};
	bad = (struct wtwm_output_restore_snapshot){duplicate_outputs, 2};
	assert(!wtwm_output_restore_plan_build(&good, &bad, &client_value, 1,
		&plan));

	client_value.frame.width = 0;
	assert(!wtwm_output_restore_plan_build(&good, &good, &client_value, 1,
		&plan));
	client_value = client(0, 0, 0, 100, 80);
	assert(!wtwm_output_restore_plan_build(&good, &good, &client_value, 1,
		&plan));
	struct wtwm_output_restore_client cycle[] = {
		client(1, 0, 0, 100, 80), client(0, 20, 20, 80, 60),
	};
	assert(!wtwm_output_restore_plan_build(&good, &good, cycle, 2, &plan));
	cycle[1].parent = 2;
	assert(!wtwm_output_restore_plan_build(&good, &good, cycle, 2, &plan));
	assert(memcmp(&plan, &saved, sizeof(plan)) == 0);
	wtwm_output_restore_plan_init(NULL);
	assert(!wtwm_output_restore_plan_build(&good, &good, NULL, 1, &plan));
	assert(!wtwm_output_restore_plan_build(&good, &good, &client_value, 1,
		NULL));

	client_value = client(-1, 0, 0, 100, 80);
	assert(wtwm_output_restore_plan_build(&good, &good, &client_value, 1,
		&plan));
	struct wtwm_output_restore_plan occupied = plan;
	assert(!wtwm_output_restore_plan_build(&good, &good, &client_value, 1,
		&plan));
	assert(memcmp(&plan, &occupied, sizeof(plan)) == 0);
	wtwm_output_restore_plan_finish(&plan);
	wtwm_output_restore_plan_finish(NULL);
}

int main(void) {
	disappeared_output_family();
	surviving_owner_and_no_repatriation();
	visible_geometry_is_exact();
	clamp_and_oversize();
	visible_root_repairs_only_stranded_child();
	icons_and_zoom_restore_are_independent();
	zoom_owner_change_recomputes();
	zero_outputs_and_reappearance();
	canonical_nearest_tie_and_extremes();
	invalid_inputs_are_atomic();
	return 0;
}
