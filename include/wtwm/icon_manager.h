/* SPDX-License-Identifier: MIT */
#ifndef WTWM_ICON_MANAGER_H
#define WTWM_ICON_MANAGER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_ICON_MANAGER_MAX_MANAGERS 16
#define WTWM_ICON_MANAGER_MAX_ENTRIES 256
#define WTWM_ICON_MANAGER_LABEL_SIZE 256

enum wtwm_icon_manager_result {
	WTWM_ICON_MANAGER_INVALID = -1,
	WTWM_ICON_MANAGER_UNCHANGED,
	WTWM_ICON_MANAGER_APPLIED,
	WTWM_ICON_MANAGER_CAPACITY,
};

enum wtwm_icon_manager_direction {
	WTWM_ICON_MANAGER_FORWARD,
	WTWM_ICON_MANAGER_BACKWARD,
	WTWM_ICON_MANAGER_UP,
	WTWM_ICON_MANAGER_DOWN,
	WTWM_ICON_MANAGER_LEFT,
	WTWM_ICON_MANAGER_RIGHT,
};

struct wtwm_icon_manager_entry {
	uint64_t identity;
	uint64_t manager_identity;
	uint64_t insertion_serial;
	char label[WTWM_ICON_MANAGER_LABEL_SIZE];
	size_t row;
	size_t column;
	bool occupied;
};

struct wtwm_icon_manager {
	uint64_t identity;
	uint64_t selected_entry_identity;
	char label[WTWM_ICON_MANAGER_LABEL_SIZE];
	size_t columns;
	size_t current_rows;
	size_t current_columns;
	size_t entry_count;
	size_t order[WTWM_ICON_MANAGER_MAX_ENTRIES];
	bool sorted;
	bool case_sensitive;
	bool visible;
};

struct wtwm_icon_manager_state {
	struct wtwm_icon_manager managers[WTWM_ICON_MANAGER_MAX_MANAGERS];
	struct wtwm_icon_manager_entry entries[WTWM_ICON_MANAGER_MAX_ENTRIES];
	size_t manager_count;
	size_t entry_count;
	uint64_t active_manager_identity;
	uint64_t active_entry_identity;
	uint64_t next_insertion_serial;
};

void wtwm_icon_manager_state_init(struct wtwm_icon_manager_state *state);

enum wtwm_icon_manager_result wtwm_icon_manager_add(
	struct wtwm_icon_manager_state *state, uint64_t identity,
	const char *label, size_t columns, bool sorted, bool visible);
enum wtwm_icon_manager_result wtwm_icon_manager_remove(
	struct wtwm_icon_manager_state *state, uint64_t identity);

const struct wtwm_icon_manager *wtwm_icon_manager_find(
	const struct wtwm_icon_manager_state *state, uint64_t identity);
const struct wtwm_icon_manager_entry *wtwm_icon_manager_entry_find(
	const struct wtwm_icon_manager_state *state, uint64_t identity);
const struct wtwm_icon_manager_entry *wtwm_icon_manager_entry_at(
	const struct wtwm_icon_manager_state *state, uint64_t manager_identity,
	size_t position);

enum wtwm_icon_manager_result wtwm_icon_manager_set_visible(
	struct wtwm_icon_manager_state *state, uint64_t identity, bool visible);
enum wtwm_icon_manager_result wtwm_icon_manager_set_columns(
	struct wtwm_icon_manager_state *state, uint64_t identity, size_t columns);
enum wtwm_icon_manager_result wtwm_icon_manager_set_sorted(
	struct wtwm_icon_manager_state *state, uint64_t identity, bool sorted);
enum wtwm_icon_manager_result wtwm_icon_manager_set_case_sensitive(
	struct wtwm_icon_manager_state *state, uint64_t identity,
	bool case_sensitive);
enum wtwm_icon_manager_result wtwm_icon_manager_sort(
	struct wtwm_icon_manager_state *state, uint64_t identity);

enum wtwm_icon_manager_result wtwm_icon_manager_entry_add(
	struct wtwm_icon_manager_state *state, uint64_t manager_identity,
	uint64_t entry_identity, const char *label);
enum wtwm_icon_manager_result wtwm_icon_manager_entry_remove(
	struct wtwm_icon_manager_state *state, uint64_t entry_identity);
enum wtwm_icon_manager_result wtwm_icon_manager_entry_update(
	struct wtwm_icon_manager_state *state, uint64_t entry_identity,
	uint64_t manager_identity, const char *label);

enum wtwm_icon_manager_result wtwm_icon_manager_select(
	struct wtwm_icon_manager_state *state, uint64_t entry_identity);
enum wtwm_icon_manager_result wtwm_icon_manager_move(
	struct wtwm_icon_manager_state *state,
	enum wtwm_icon_manager_direction direction, uint64_t *entry_identity);
enum wtwm_icon_manager_result wtwm_icon_manager_next(
	struct wtwm_icon_manager_state *state, uint64_t *entry_identity);
enum wtwm_icon_manager_result wtwm_icon_manager_previous(
	struct wtwm_icon_manager_state *state, uint64_t *entry_identity);

bool wtwm_icon_manager_validate(const struct wtwm_icon_manager_state *state,
	char *error, size_t error_size);

#endif
