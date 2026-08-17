/* SPDX-License-Identifier: MIT */
#include "wtwm/icon_manager.h"

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void assert_valid(const struct wtwm_icon_manager_state *state) {
	char error[128];
	if (!wtwm_icon_manager_validate(state, error, sizeof(error))) {
		fprintf(stderr, "invalid icon-manager state: %s\n", error);
		assert(false);
	}
}

static void add_manager(struct wtwm_icon_manager_state *state, uint64_t id,
		const char *label, size_t columns, bool sorted, bool visible) {
	assert(wtwm_icon_manager_add(state, id, label, columns, sorted, visible) ==
		WTWM_ICON_MANAGER_APPLIED);
}

static void add_entry(struct wtwm_icon_manager_state *state, uint64_t manager,
		uint64_t id, const char *label) {
	assert(wtwm_icon_manager_entry_add(state, manager, id, label) ==
		WTWM_ICON_MANAGER_APPLIED);
}

static void assert_order(const struct wtwm_icon_manager_state *state,
		uint64_t manager, const uint64_t *expected, size_t count) {
	const struct wtwm_icon_manager_model *found =
		wtwm_icon_manager_find(state, manager);
	assert(found != NULL && found->entry_count == count);
	for (size_t i = 0; i < count; ++i) {
		const struct wtwm_icon_manager_entry *entry =
			wtwm_icon_manager_entry_at(state, manager, i);
		assert(entry != NULL && entry->identity == expected[i]);
		assert(entry->row == i / found->columns);
		assert(entry->column == i % found->columns);
	}
	assert(wtwm_icon_manager_entry_at(state, manager, count) == NULL);
}

static void insertion_sorting_and_layout(void) {
	struct wtwm_icon_manager_state state;
	wtwm_icon_manager_state_init(&state);
	add_manager(&state, 10, "main", 3, false, true);
	add_entry(&state, 10, 1, "delta");
	add_entry(&state, 10, 2, "alpha");
	add_entry(&state, 10, 3, "alpha");
	add_entry(&state, 10, 4, "bravo");
	const uint64_t insertion[] = {1, 2, 3, 4};
	assert_order(&state, 10, insertion, 4);
	const struct wtwm_icon_manager_model *manager =
		wtwm_icon_manager_find(&state, 10);
	assert(manager->current_rows == 2 && manager->current_columns == 3);

	assert(wtwm_icon_manager_sort(&state, 10) == WTWM_ICON_MANAGER_APPLIED);
	const uint64_t sorted[] = {2, 3, 4, 1};
	assert_order(&state, 10, sorted, 4);
	assert(!manager->sorted);
	add_entry(&state, 10, 5, "aardvark");
	const uint64_t appended[] = {2, 3, 4, 1, 5};
	assert_order(&state, 10, appended, 5);

	assert(wtwm_icon_manager_set_sorted(&state, 10, true) ==
		WTWM_ICON_MANAGER_APPLIED);
	const uint64_t resorted[] = {5, 2, 3, 4, 1};
	assert_order(&state, 10, resorted, 5);
	add_entry(&state, 10, 6, "alpha");
	const uint64_t stable_equal[] = {5, 2, 3, 6, 4, 1};
	assert_order(&state, 10, stable_equal, 6);
	assert(wtwm_icon_manager_entry_update(&state, 4, 10, "Alpha") ==
		WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_set_case_sensitive(&state, 10, false) ==
		WTWM_ICON_MANAGER_APPLIED);
	const uint64_t folded[] = {5, 2, 3, 4, 6, 1};
	assert_order(&state, 10, folded, 6);
	assert(wtwm_icon_manager_set_case_sensitive(&state, 10, true) ==
		WTWM_ICON_MANAGER_APPLIED);
	const uint64_t sensitive_again[] = {4, 5, 2, 3, 6, 1};
	assert_order(&state, 10, sensitive_again, 6);
	assert(wtwm_icon_manager_entry_update(&state, 1, 10, "00-delta") ==
		WTWM_ICON_MANAGER_APPLIED);
	const uint64_t renamed[] = {1, 4, 5, 2, 3, 6};
	assert_order(&state, 10, renamed, 6);

	assert(wtwm_icon_manager_set_columns(&state, 10, 4) ==
		WTWM_ICON_MANAGER_APPLIED);
	manager = wtwm_icon_manager_find(&state, 10);
	assert(manager->current_rows == 2 && manager->current_columns == 4);
	assert_order(&state, 10, renamed, 6);
	assert(wtwm_icon_manager_set_columns(&state, 10, 0) ==
		WTWM_ICON_MANAGER_INVALID);
	assert(wtwm_icon_manager_set_columns(&state, 10,
		WTWM_ICON_MANAGER_MAX_ENTRIES + 1) == WTWM_ICON_MANAGER_INVALID);
	assert_valid(&state);
}

static void updates_removals_and_manager_lifecycle(void) {
	struct wtwm_icon_manager_state state;
	wtwm_icon_manager_state_init(&state);
	add_manager(&state, 10, "main", 2, true, true);
	add_manager(&state, 20, "other", 1, false, false);
	add_entry(&state, 10, 1, "one");
	add_entry(&state, 10, 2, "two");
	add_entry(&state, 10, 3, "three");
	add_entry(&state, 20, 4, "four");
	assert(wtwm_icon_manager_select(&state, 2) == WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_entry_update(&state, 2, 20, "moved") ==
		WTWM_ICON_MANAGER_APPLIED);
	assert(state.active_manager_identity == 20 && state.active_entry_identity == 2);
	assert(wtwm_icon_manager_entry_find(&state, 2)->manager_identity == 20);
	const uint64_t main_after_move[] = {1, 3};
	const uint64_t other_after_move[] = {4, 2};
	assert_order(&state, 10, main_after_move, 2);
	assert_order(&state, 20, other_after_move, 2);
	assert(wtwm_icon_manager_find(&state, 20)->selected_entry_identity == 2);

	assert(wtwm_icon_manager_entry_remove(&state, 2) ==
		WTWM_ICON_MANAGER_APPLIED);
	assert(state.active_manager_identity == 20 && state.active_entry_identity == 4);
	assert(wtwm_icon_manager_entry_find(&state, 2) == NULL);
	assert(wtwm_icon_manager_entry_remove(&state, 2) ==
		WTWM_ICON_MANAGER_UNCHANGED);
	assert(wtwm_icon_manager_remove(&state, 20) == WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_find(&state, 20) == NULL);
	assert(wtwm_icon_manager_entry_find(&state, 4) == NULL);
	assert(state.active_manager_identity == 0 && state.active_entry_identity == 0);
	assert(state.manager_count == 1 && state.entry_count == 2);
	assert(wtwm_icon_manager_remove(&state, 20) == WTWM_ICON_MANAGER_UNCHANGED);
	assert_valid(&state);
}

static void navigation_and_visibility(void) {
	struct wtwm_icon_manager_state state;
	wtwm_icon_manager_state_init(&state);
	add_manager(&state, 10, "first", 3, false, true);
	add_manager(&state, 20, "hidden", 1, false, false);
	add_manager(&state, 30, "third", 2, false, true);
	add_manager(&state, 40, "empty", 2, false, true);
	for (uint64_t id = 101; id <= 105; ++id) {
		char label[16];
		(void)snprintf(label, sizeof(label), "entry-%llu",
			(unsigned long long)id);
		add_entry(&state, 10, id, label);
	}
	add_entry(&state, 20, 201, "hidden-entry");
	add_entry(&state, 30, 301, "third-a");
	add_entry(&state, 30, 302, "third-b");
	uint64_t selected = 0;
	assert(wtwm_icon_manager_select(&state, 103) == WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_DOWN, &selected) ==
		WTWM_ICON_MANAGER_UNCHANGED && selected == 103);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_LEFT, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 102);
	assert(wtwm_icon_manager_select(&state, 105) == WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_RIGHT, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 104);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_UP, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 101);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_DOWN, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 104);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_FORWARD, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 105);
	assert(wtwm_icon_manager_move(&state, WTWM_ICON_MANAGER_BACKWARD, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 104);

	assert(wtwm_icon_manager_next(&state, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 301);
	assert(wtwm_icon_manager_previous(&state, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 104);
	assert(wtwm_icon_manager_set_visible(&state, 10, false) ==
		WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_next(&state, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 301);
	assert(wtwm_icon_manager_previous(&state, &selected) ==
		WTWM_ICON_MANAGER_UNCHANGED && selected == 301);
	assert(wtwm_icon_manager_set_visible(&state, 20, true) ==
		WTWM_ICON_MANAGER_APPLIED);
	assert(wtwm_icon_manager_next(&state, &selected) ==
		WTWM_ICON_MANAGER_APPLIED && selected == 201);
	assert(wtwm_icon_manager_set_visible(&state, 20, true) ==
		WTWM_ICON_MANAGER_UNCHANGED);
	assert_valid(&state);
}

static void capacity_and_invalid_inputs(void) {
	struct wtwm_icon_manager_state state;
	wtwm_icon_manager_state_init(&state);
	assert(wtwm_icon_manager_add(&state, 0, "bad", 1, false, true) ==
		WTWM_ICON_MANAGER_INVALID);
	for (uint64_t i = 1; i <= WTWM_ICON_MANAGER_MAX_MANAGERS; ++i) {
		char label[16];
		(void)snprintf(label, sizeof(label), "manager-%llu",
			(unsigned long long)i);
		add_manager(&state, i, label, 1, false, true);
	}
	assert(wtwm_icon_manager_add(&state, 99, "overflow", 1, false, true) ==
		WTWM_ICON_MANAGER_CAPACITY);
	for (uint64_t i = 1; i <= WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
		char label[24];
		(void)snprintf(label, sizeof(label), "entry-%03llu",
			(unsigned long long)i);
		add_entry(&state, 1, 1000 + i, label);
	}
	assert(wtwm_icon_manager_entry_add(&state, 1, 9999, "overflow") ==
		WTWM_ICON_MANAGER_CAPACITY);
	assert(wtwm_icon_manager_entry_add(&state, 999, 9998, "bad-manager") ==
		WTWM_ICON_MANAGER_INVALID);
	assert(wtwm_icon_manager_entry_add(&state, 1, 1001, "duplicate") ==
		WTWM_ICON_MANAGER_INVALID);
	char too_long[WTWM_ICON_MANAGER_LABEL_SIZE + 1];
	memset(too_long, 'x', sizeof(too_long) - 1);
	too_long[sizeof(too_long) - 1] = '\0';
	assert(wtwm_icon_manager_entry_update(&state, 1001, 1, too_long) ==
		WTWM_ICON_MANAGER_INVALID);
	assert(strcmp(wtwm_icon_manager_entry_find(&state, 1001)->label,
		"entry-001") == 0);
	assert_valid(&state);
}

static void large_lifecycle_churn(void) {
	struct wtwm_icon_manager_state state;
	wtwm_icon_manager_state_init(&state);
	add_manager(&state, 1, "one", 7, false, true);
	add_manager(&state, 2, "two", 11, true, true);
	add_manager(&state, 3, "three", 5, false, false);
	for (uint64_t cycle = 0; cycle < 40; ++cycle) {
		uint64_t base = UINT64_C(10000) + cycle * UINT64_C(1000);
		for (uint64_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
			char label[32];
			(void)snprintf(label, sizeof(label), "c%02llu-e%03llu",
				(unsigned long long)cycle, (unsigned long long)i);
			add_entry(&state, i % 3 + 1, base + i, label);
		}
		assert(state.entry_count == WTWM_ICON_MANAGER_MAX_ENTRIES);
		for (uint64_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
			char label[32];
			(void)snprintf(label, sizeof(label), "renamed-%03llu",
				(unsigned long long)(WTWM_ICON_MANAGER_MAX_ENTRIES - i));
			assert(wtwm_icon_manager_entry_update(&state, base + i,
				(i * 5 + cycle) % 3 + 1, label) == WTWM_ICON_MANAGER_APPLIED);
		}
		assert(wtwm_icon_manager_sort(&state, 1) != WTWM_ICON_MANAGER_INVALID);
		assert(wtwm_icon_manager_sort(&state, 3) != WTWM_ICON_MANAGER_INVALID);
		assert_valid(&state);
		for (uint64_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
			uint64_t index = (i * UINT64_C(73)) %
				WTWM_ICON_MANAGER_MAX_ENTRIES;
			assert(wtwm_icon_manager_entry_remove(&state, base + index) ==
				WTWM_ICON_MANAGER_APPLIED);
			assert(wtwm_icon_manager_entry_find(&state, base + index) == NULL);
		}
		assert(state.entry_count == 0);
		assert(state.active_manager_identity == 0 &&
			state.active_entry_identity == 0);
		for (uint64_t manager = 1; manager <= 3; ++manager) {
			const struct wtwm_icon_manager_model *found =
				wtwm_icon_manager_find(&state, manager);
			assert(found->entry_count == 0 && found->current_rows == 0 &&
				found->current_columns == 0 &&
				found->selected_entry_identity == 0);
		}
		assert_valid(&state);
	}
}

int main(void) {
	insertion_sorting_and_layout();
	updates_removals_and_manager_lifecycle();
	navigation_and_visibility();
	capacity_and_invalid_inputs();
	large_lifecycle_churn();
	puts("icon manager model tests passed");
	return 0;
}
