/* SPDX-License-Identifier: MIT */
#include "wtwm/icon_manager.h"

#include <stdio.h>
#include <string.h>

static bool label_valid(const char *label) {
	return label != NULL && strlen(label) < WTWM_ICON_MANAGER_LABEL_SIZE;
}

static struct wtwm_icon_manager *find_manager_mutable(
		struct wtwm_icon_manager_state *state, uint64_t identity) {
	if (state == NULL || identity == 0) return NULL;
	for (size_t i = 0; i < state->manager_count; ++i) {
		if (state->managers[i].identity == identity) return &state->managers[i];
	}
	return NULL;
}

const struct wtwm_icon_manager *wtwm_icon_manager_find(
		const struct wtwm_icon_manager_state *state, uint64_t identity) {
	if (state == NULL || identity == 0) return NULL;
	for (size_t i = 0; i < state->manager_count; ++i) {
		if (state->managers[i].identity == identity) return &state->managers[i];
	}
	return NULL;
}

static struct wtwm_icon_manager_entry *find_entry_mutable(
		struct wtwm_icon_manager_state *state, uint64_t identity) {
	if (state == NULL || identity == 0) return NULL;
	for (size_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
		if (state->entries[i].occupied && state->entries[i].identity == identity)
			return &state->entries[i];
	}
	return NULL;
}

const struct wtwm_icon_manager_entry *wtwm_icon_manager_entry_find(
		const struct wtwm_icon_manager_state *state, uint64_t identity) {
	if (state == NULL || identity == 0) return NULL;
	for (size_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
		if (state->entries[i].occupied && state->entries[i].identity == identity)
			return &state->entries[i];
	}
	return NULL;
}

const struct wtwm_icon_manager_entry *wtwm_icon_manager_entry_at(
		const struct wtwm_icon_manager_state *state, uint64_t manager_identity,
		size_t position) {
	const struct wtwm_icon_manager *manager =
		wtwm_icon_manager_find(state, manager_identity);
	if (manager == NULL || position >= manager->entry_count) return NULL;
	size_t slot = manager->order[position];
	if (slot >= WTWM_ICON_MANAGER_MAX_ENTRIES) return NULL;
	return &state->entries[slot];
}

void wtwm_icon_manager_state_init(struct wtwm_icon_manager_state *state) {
	if (state == NULL) return;
	memset(state, 0, sizeof(*state));
	state->next_insertion_serial = 1;
}

static void repack(struct wtwm_icon_manager_state *state,
		struct wtwm_icon_manager *manager) {
	for (size_t i = 0; i < manager->entry_count; ++i) {
		struct wtwm_icon_manager_entry *entry = &state->entries[manager->order[i]];
		entry->row = i / manager->columns;
		entry->column = i % manager->columns;
	}
	manager->current_rows = manager->entry_count == 0 ? 0 :
		(manager->entry_count + manager->columns - 1) / manager->columns;
	manager->current_columns = manager->entry_count < manager->columns ?
		manager->entry_count : manager->columns;
}

static int compare_entries(const struct wtwm_icon_manager_entry *left,
		const struct wtwm_icon_manager_entry *right) {
	int result = strcmp(left->label, right->label);
	if (result != 0) return result;
	if (left->insertion_serial < right->insertion_serial) return -1;
	if (left->insertion_serial > right->insertion_serial) return 1;
	return 0;
}

static bool sort_order(struct wtwm_icon_manager_state *state,
		struct wtwm_icon_manager *manager) {
	bool changed = false;
	for (size_t i = 1; i < manager->entry_count; ++i) {
		size_t slot = manager->order[i];
		size_t position = i;
		while (position > 0 && compare_entries(&state->entries[slot],
				&state->entries[manager->order[position - 1]]) < 0) {
			manager->order[position] = manager->order[position - 1];
			--position;
			changed = true;
		}
		manager->order[position] = slot;
	}
	repack(state, manager);
	return changed;
}

enum wtwm_icon_manager_result wtwm_icon_manager_add(
		struct wtwm_icon_manager_state *state, uint64_t identity,
		const char *label, size_t columns, bool sorted, bool visible) {
	if (state == NULL || identity == 0 || !label_valid(label) || columns == 0 ||
			columns > WTWM_ICON_MANAGER_MAX_ENTRIES)
		return WTWM_ICON_MANAGER_INVALID;
	if (wtwm_icon_manager_find(state, identity) != NULL)
		return WTWM_ICON_MANAGER_INVALID;
	if (state->manager_count == WTWM_ICON_MANAGER_MAX_MANAGERS)
		return WTWM_ICON_MANAGER_CAPACITY;
	struct wtwm_icon_manager *manager = &state->managers[state->manager_count++];
	memset(manager, 0, sizeof(*manager));
	manager->identity = identity;
	manager->columns = columns;
	manager->sorted = sorted;
	manager->visible = visible;
	(void)snprintf(manager->label, sizeof(manager->label), "%s", label);
	return WTWM_ICON_MANAGER_APPLIED;
}

static size_t manager_position(const struct wtwm_icon_manager_state *state,
		uint64_t identity) {
	for (size_t i = 0; i < state->manager_count; ++i) {
		if (state->managers[i].identity == identity) return i;
	}
	return SIZE_MAX;
}

enum wtwm_icon_manager_result wtwm_icon_manager_remove(
		struct wtwm_icon_manager_state *state, uint64_t identity) {
	if (state == NULL || identity == 0) return WTWM_ICON_MANAGER_INVALID;
	size_t position = manager_position(state, identity);
	if (position == SIZE_MAX) return WTWM_ICON_MANAGER_UNCHANGED;
	for (size_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
		if (!state->entries[i].occupied ||
				state->entries[i].manager_identity != identity) continue;
		memset(&state->entries[i], 0, sizeof(state->entries[i]));
		--state->entry_count;
	}
	if (state->active_manager_identity == identity) {
		state->active_manager_identity = 0;
		state->active_entry_identity = 0;
	}
	if (position + 1 < state->manager_count) {
		memmove(&state->managers[position], &state->managers[position + 1],
			(state->manager_count - position - 1) * sizeof(state->managers[0]));
	}
	--state->manager_count;
	memset(&state->managers[state->manager_count], 0,
		sizeof(state->managers[0]));
	return WTWM_ICON_MANAGER_APPLIED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_set_visible(
		struct wtwm_icon_manager_state *state, uint64_t identity, bool visible) {
	struct wtwm_icon_manager *manager = find_manager_mutable(state, identity);
	if (manager == NULL) return WTWM_ICON_MANAGER_INVALID;
	if (manager->visible == visible) return WTWM_ICON_MANAGER_UNCHANGED;
	manager->visible = visible;
	return WTWM_ICON_MANAGER_APPLIED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_set_columns(
		struct wtwm_icon_manager_state *state, uint64_t identity, size_t columns) {
	struct wtwm_icon_manager *manager = find_manager_mutable(state, identity);
	if (manager == NULL || columns == 0 ||
			columns > WTWM_ICON_MANAGER_MAX_ENTRIES)
		return WTWM_ICON_MANAGER_INVALID;
	if (manager->columns == columns) return WTWM_ICON_MANAGER_UNCHANGED;
	manager->columns = columns;
	repack(state, manager);
	return WTWM_ICON_MANAGER_APPLIED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_sort(
		struct wtwm_icon_manager_state *state, uint64_t identity) {
	struct wtwm_icon_manager *manager = find_manager_mutable(state, identity);
	if (manager == NULL) return WTWM_ICON_MANAGER_INVALID;
	return sort_order(state, manager) ? WTWM_ICON_MANAGER_APPLIED :
		WTWM_ICON_MANAGER_UNCHANGED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_set_sorted(
		struct wtwm_icon_manager_state *state, uint64_t identity, bool sorted) {
	struct wtwm_icon_manager *manager = find_manager_mutable(state, identity);
	if (manager == NULL) return WTWM_ICON_MANAGER_INVALID;
	if (manager->sorted == sorted) return WTWM_ICON_MANAGER_UNCHANGED;
	manager->sorted = sorted;
	if (sorted) (void)sort_order(state, manager);
	return WTWM_ICON_MANAGER_APPLIED;
}

static size_t free_entry_slot(const struct wtwm_icon_manager_state *state) {
	for (size_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
		if (!state->entries[i].occupied) return i;
	}
	return SIZE_MAX;
}

static void insert_slot(struct wtwm_icon_manager_state *state,
		struct wtwm_icon_manager *manager, size_t slot) {
	size_t position = manager->entry_count;
	if (manager->sorted) {
		position = 0;
		while (position < manager->entry_count &&
				compare_entries(&state->entries[manager->order[position]],
					&state->entries[slot]) <= 0)
			++position;
	}
	if (position < manager->entry_count) {
		memmove(&manager->order[position + 1], &manager->order[position],
			(manager->entry_count - position) * sizeof(manager->order[0]));
	}
	manager->order[position] = slot;
	++manager->entry_count;
	if (manager->selected_entry_identity == 0)
		manager->selected_entry_identity = state->entries[slot].identity;
	repack(state, manager);
}

enum wtwm_icon_manager_result wtwm_icon_manager_entry_add(
		struct wtwm_icon_manager_state *state, uint64_t manager_identity,
		uint64_t entry_identity, const char *label) {
	if (state == NULL || entry_identity == 0 || !label_valid(label))
		return WTWM_ICON_MANAGER_INVALID;
	struct wtwm_icon_manager *manager =
		find_manager_mutable(state, manager_identity);
	if (manager == NULL || wtwm_icon_manager_entry_find(state, entry_identity))
		return WTWM_ICON_MANAGER_INVALID;
	if (state->entry_count == WTWM_ICON_MANAGER_MAX_ENTRIES ||
			state->next_insertion_serial == 0 ||
			state->next_insertion_serial == UINT64_MAX)
		return WTWM_ICON_MANAGER_CAPACITY;
	size_t slot = free_entry_slot(state);
	if (slot == SIZE_MAX) return WTWM_ICON_MANAGER_CAPACITY;
	struct wtwm_icon_manager_entry *entry = &state->entries[slot];
	memset(entry, 0, sizeof(*entry));
	entry->identity = entry_identity;
	entry->manager_identity = manager_identity;
	entry->insertion_serial = state->next_insertion_serial++;
	entry->occupied = true;
	(void)snprintf(entry->label, sizeof(entry->label), "%s", label);
	insert_slot(state, manager, slot);
	++state->entry_count;
	if (state->active_entry_identity == 0) {
		state->active_manager_identity = manager_identity;
		state->active_entry_identity = entry_identity;
	}
	return WTWM_ICON_MANAGER_APPLIED;
}

static size_t order_position(const struct wtwm_icon_manager *manager,
		size_t slot) {
	for (size_t i = 0; i < manager->entry_count; ++i) {
		if (manager->order[i] == slot) return i;
	}
	return SIZE_MAX;
}

static void remove_slot(struct wtwm_icon_manager_state *state,
		struct wtwm_icon_manager *manager, size_t slot) {
	size_t position = order_position(manager, slot);
	if (position == SIZE_MAX) return;
	uint64_t removed_identity = state->entries[slot].identity;
	if (position + 1 < manager->entry_count) {
		memmove(&manager->order[position], &manager->order[position + 1],
			(manager->entry_count - position - 1) * sizeof(manager->order[0]));
	}
	--manager->entry_count;
	manager->order[manager->entry_count] = 0;
	if (manager->selected_entry_identity == removed_identity) {
		if (manager->entry_count == 0) manager->selected_entry_identity = 0;
		else {
			if (position == manager->entry_count) --position;
			manager->selected_entry_identity =
				state->entries[manager->order[position]].identity;
		}
	}
	repack(state, manager);
}

enum wtwm_icon_manager_result wtwm_icon_manager_entry_remove(
		struct wtwm_icon_manager_state *state, uint64_t entry_identity) {
	if (state == NULL || entry_identity == 0) return WTWM_ICON_MANAGER_INVALID;
	struct wtwm_icon_manager_entry *entry =
		find_entry_mutable(state, entry_identity);
	if (entry == NULL) return WTWM_ICON_MANAGER_UNCHANGED;
	struct wtwm_icon_manager *manager =
		find_manager_mutable(state, entry->manager_identity);
	if (manager == NULL) return WTWM_ICON_MANAGER_INVALID;
	size_t slot = (size_t)(entry - state->entries);
	bool active = state->active_entry_identity == entry_identity;
	remove_slot(state, manager, slot);
	if (active) {
		state->active_entry_identity = manager->selected_entry_identity;
		state->active_manager_identity = state->active_entry_identity == 0 ? 0 :
			manager->identity;
	}
	memset(entry, 0, sizeof(*entry));
	--state->entry_count;
	return WTWM_ICON_MANAGER_APPLIED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_entry_update(
		struct wtwm_icon_manager_state *state, uint64_t entry_identity,
		uint64_t manager_identity, const char *label) {
	if (state == NULL || entry_identity == 0 || !label_valid(label))
		return WTWM_ICON_MANAGER_INVALID;
	struct wtwm_icon_manager_entry *entry =
		find_entry_mutable(state, entry_identity);
	struct wtwm_icon_manager *target =
		find_manager_mutable(state, manager_identity);
	if (entry == NULL || target == NULL) return WTWM_ICON_MANAGER_INVALID;
	bool manager_changed = entry->manager_identity != manager_identity;
	bool label_changed = strcmp(entry->label, label) != 0;
	if (!manager_changed && !label_changed) return WTWM_ICON_MANAGER_UNCHANGED;
	size_t slot = (size_t)(entry - state->entries);
	if (manager_changed) {
		struct wtwm_icon_manager *source =
			find_manager_mutable(state, entry->manager_identity);
		if (source == NULL) return WTWM_ICON_MANAGER_INVALID;
		bool source_selected = source->selected_entry_identity == entry_identity;
		bool active = state->active_entry_identity == entry_identity;
		remove_slot(state, source, slot);
		entry->manager_identity = manager_identity;
		(void)snprintf(entry->label, sizeof(entry->label), "%s", label);
		insert_slot(state, target, slot);
		if (source_selected && (active ||
				state->active_manager_identity != target->identity))
			target->selected_entry_identity = entry_identity;
		if (active) {
			state->active_manager_identity = manager_identity;
			state->active_entry_identity = entry_identity;
		}
	} else {
		(void)snprintf(entry->label, sizeof(entry->label), "%s", label);
		if (target->sorted) (void)sort_order(state, target);
	}
	return WTWM_ICON_MANAGER_APPLIED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_select(
		struct wtwm_icon_manager_state *state, uint64_t entry_identity) {
	if (state == NULL || entry_identity == 0) return WTWM_ICON_MANAGER_INVALID;
	struct wtwm_icon_manager_entry *entry =
		find_entry_mutable(state, entry_identity);
	if (entry == NULL) return WTWM_ICON_MANAGER_INVALID;
	struct wtwm_icon_manager *manager =
		find_manager_mutable(state, entry->manager_identity);
	if (manager == NULL) return WTWM_ICON_MANAGER_INVALID;
	bool changed = state->active_entry_identity != entry_identity;
	manager->selected_entry_identity = entry_identity;
	state->active_manager_identity = manager->identity;
	state->active_entry_identity = entry_identity;
	return changed ? WTWM_ICON_MANAGER_APPLIED : WTWM_ICON_MANAGER_UNCHANGED;
}

static size_t directional_position(
		const struct wtwm_icon_manager_state *state,
		const struct wtwm_icon_manager *manager, size_t position,
		enum wtwm_icon_manager_direction direction) {
	if (direction == WTWM_ICON_MANAGER_FORWARD)
		return (position + 1) % manager->entry_count;
	if (direction == WTWM_ICON_MANAGER_BACKWARD)
		return position == 0 ? manager->entry_count - 1 : position - 1;
	const struct wtwm_icon_manager_entry *entry =
		&state->entries[manager->order[position]];
	size_t row = entry->row;
	size_t column = entry->column;
	size_t limit = (direction == WTWM_ICON_MANAGER_UP ||
		direction == WTWM_ICON_MANAGER_DOWN) ? manager->current_rows :
		manager->current_columns;
	for (size_t i = 0; i < limit; ++i) {
		switch (direction) {
		case WTWM_ICON_MANAGER_UP:
			row = row == 0 ? manager->current_rows - 1 : row - 1; break;
		case WTWM_ICON_MANAGER_DOWN:
			row = (row + 1) % manager->current_rows; break;
		case WTWM_ICON_MANAGER_LEFT:
			column = column == 0 ? manager->current_columns - 1 : column - 1;
			break;
		case WTWM_ICON_MANAGER_RIGHT:
			column = (column + 1) % manager->current_columns; break;
		default:
			return position;
		}
		size_t candidate = row * manager->columns + column;
		if (candidate < manager->entry_count) return candidate;
	}
	return position;
}

enum wtwm_icon_manager_result wtwm_icon_manager_move(
		struct wtwm_icon_manager_state *state,
		enum wtwm_icon_manager_direction direction, uint64_t *entry_identity) {
	if (entry_identity != NULL) *entry_identity = 0;
	if (state == NULL || (int)direction < (int)WTWM_ICON_MANAGER_FORWARD ||
			(int)direction > (int)WTWM_ICON_MANAGER_RIGHT)
		return WTWM_ICON_MANAGER_INVALID;
	struct wtwm_icon_manager *manager =
		find_manager_mutable(state, state->active_manager_identity);
	struct wtwm_icon_manager_entry *entry =
		find_entry_mutable(state, state->active_entry_identity);
	if (manager == NULL || entry == NULL || manager->entry_count == 0 ||
			entry->manager_identity != manager->identity)
		return WTWM_ICON_MANAGER_UNCHANGED;
	size_t slot = (size_t)(entry - state->entries);
	size_t position = order_position(manager, slot);
	if (position == SIZE_MAX) return WTWM_ICON_MANAGER_INVALID;
	size_t target_position = directional_position(state, manager, position,
		direction);
	uint64_t target = state->entries[manager->order[target_position]].identity;
	if (entry_identity != NULL) *entry_identity = target;
	return wtwm_icon_manager_select(state, target);
}

static enum wtwm_icon_manager_result jump_manager(
		struct wtwm_icon_manager_state *state, bool forward,
		uint64_t *entry_identity) {
	if (entry_identity != NULL) *entry_identity = 0;
	if (state == NULL) return WTWM_ICON_MANAGER_INVALID;
	if (state->manager_count == 0) return WTWM_ICON_MANAGER_UNCHANGED;
	size_t current = manager_position(state, state->active_manager_identity);
	if (current == SIZE_MAX) current = forward ? state->manager_count - 1 : 0;
	for (size_t offset = 1; offset <= state->manager_count; ++offset) {
		size_t index = forward ? (current + offset) % state->manager_count :
			(current + state->manager_count -
				(offset % state->manager_count)) % state->manager_count;
		struct wtwm_icon_manager *manager = &state->managers[index];
		if (!manager->visible || manager->entry_count == 0) continue;
		uint64_t target = manager->selected_entry_identity;
		const struct wtwm_icon_manager_entry *selected =
			wtwm_icon_manager_entry_find(state, target);
		if (selected == NULL || selected->manager_identity != manager->identity)
			target = state->entries[manager->order[0]].identity;
		if (entry_identity != NULL) *entry_identity = target;
		return wtwm_icon_manager_select(state, target);
	}
	return WTWM_ICON_MANAGER_UNCHANGED;
}

enum wtwm_icon_manager_result wtwm_icon_manager_next(
		struct wtwm_icon_manager_state *state, uint64_t *entry_identity) {
	return jump_manager(state, true, entry_identity);
}

enum wtwm_icon_manager_result wtwm_icon_manager_previous(
		struct wtwm_icon_manager_state *state, uint64_t *entry_identity) {
	return jump_manager(state, false, entry_identity);
}

static bool invalid(char *error, size_t error_size, const char *message) {
	if (error != NULL && error_size != 0)
		(void)snprintf(error, error_size, "%s", message);
	return false;
}

bool wtwm_icon_manager_validate(const struct wtwm_icon_manager_state *state,
		char *error, size_t error_size) {
	if (state == NULL) return invalid(error, error_size, "null state");
	if (state->manager_count > WTWM_ICON_MANAGER_MAX_MANAGERS)
		return invalid(error, error_size, "manager count overflow");
	if (state->entry_count > WTWM_ICON_MANAGER_MAX_ENTRIES)
		return invalid(error, error_size, "entry count overflow");
	if (state->next_insertion_serial == 0)
		return invalid(error, error_size, "insertion serial overflow");
	bool referenced[WTWM_ICON_MANAGER_MAX_ENTRIES] = {false};
	size_t references = 0;
	for (size_t i = 0; i < state->manager_count; ++i) {
		const struct wtwm_icon_manager *manager = &state->managers[i];
		if (manager->identity == 0 || manager->columns == 0 ||
				manager->columns > WTWM_ICON_MANAGER_MAX_ENTRIES ||
				manager->entry_count > WTWM_ICON_MANAGER_MAX_ENTRIES ||
				memchr(manager->label, '\0', sizeof(manager->label)) == NULL)
			return invalid(error, error_size, "invalid manager");
		for (size_t j = i + 1; j < state->manager_count; ++j) {
			if (state->managers[j].identity == manager->identity)
				return invalid(error, error_size, "duplicate manager identity");
		}
		size_t expected_rows = manager->entry_count == 0 ? 0 :
			(manager->entry_count + manager->columns - 1) / manager->columns;
		size_t expected_columns = manager->entry_count < manager->columns ?
			manager->entry_count : manager->columns;
		if (manager->current_rows != expected_rows ||
				manager->current_columns != expected_columns)
			return invalid(error, error_size, "invalid manager dimensions");
		bool selected_found = manager->selected_entry_identity == 0;
		for (size_t j = 0; j < manager->entry_count; ++j) {
			size_t slot = manager->order[j];
			if (slot >= WTWM_ICON_MANAGER_MAX_ENTRIES || referenced[slot])
				return invalid(error, error_size, "invalid entry ordering");
			const struct wtwm_icon_manager_entry *entry = &state->entries[slot];
			if (!entry->occupied || entry->identity == 0 ||
					entry->manager_identity != manager->identity ||
					entry->insertion_serial == 0 ||
					entry->insertion_serial >= state->next_insertion_serial ||
					entry->row != j / manager->columns ||
					entry->column != j % manager->columns ||
					memchr(entry->label, '\0', sizeof(entry->label)) == NULL)
				return invalid(error, error_size, "invalid entry");
			if (manager->sorted && j != 0 && compare_entries(
					&state->entries[manager->order[j - 1]], entry) > 0)
				return invalid(error, error_size, "unsorted manager");
			if (entry->identity == manager->selected_entry_identity)
				selected_found = true;
			referenced[slot] = true;
			++references;
		}
		if (!selected_found || (manager->entry_count == 0 &&
				manager->selected_entry_identity != 0))
			return invalid(error, error_size, "stale manager selection");
	}
	if (references != state->entry_count)
		return invalid(error, error_size, "entry count mismatch");
	for (size_t i = 0; i < WTWM_ICON_MANAGER_MAX_ENTRIES; ++i) {
		if (state->entries[i].occupied != referenced[i])
			return invalid(error, error_size, "unreferenced entry");
		if (!state->entries[i].occupied) continue;
		for (size_t j = i + 1; j < WTWM_ICON_MANAGER_MAX_ENTRIES; ++j) {
			if (state->entries[j].occupied &&
					state->entries[j].identity == state->entries[i].identity)
				return invalid(error, error_size, "duplicate entry identity");
		}
	}
	if ((state->active_manager_identity == 0) !=
			(state->active_entry_identity == 0))
		return invalid(error, error_size, "partial active selection");
	if (state->active_entry_identity != 0) {
		const struct wtwm_icon_manager_entry *entry =
			wtwm_icon_manager_entry_find(state, state->active_entry_identity);
		const struct wtwm_icon_manager *manager =
			wtwm_icon_manager_find(state, state->active_manager_identity);
		if (entry == NULL || manager == NULL ||
				entry->manager_identity != manager->identity ||
				manager->selected_entry_identity != entry->identity)
			return invalid(error, error_size, "stale active selection");
	}
	if (error != NULL && error_size != 0) error[0] = '\0';
	return true;
}
