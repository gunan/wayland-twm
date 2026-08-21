/* SPDX-License-Identifier: MIT */
#include <wtwm/icon_layout.h>

#include <ctype.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct icon_entry {
	struct icon_entry *next;
	int x;
	int y;
	int width;
	int height;
	int icon_width;
	int icon_height;
	uint64_t key;
};

struct icon_region_state {
	struct wtwm_icon_layout_region geometry;
	struct icon_entry *entries;
};

struct wtwm_icon_layout {
	struct icon_region_state *regions;
	size_t region_count;
	size_t allocation_count;
};

static bool direction_is_vertical(enum wtwm_icon_layout_direction direction) {
	return direction == WTWM_ICON_LAYOUT_NORTH ||
		direction == WTWM_ICON_LAYOUT_SOUTH;
}

static bool direction_is_horizontal(enum wtwm_icon_layout_direction direction) {
	return direction == WTWM_ICON_LAYOUT_EAST ||
		direction == WTWM_ICON_LAYOUT_WEST;
}

static bool valid_directions(enum wtwm_icon_layout_direction primary,
		enum wtwm_icon_layout_direction secondary) {
	return (direction_is_vertical(primary) && direction_is_horizontal(secondary)) ||
		(direction_is_horizontal(primary) && direction_is_vertical(secondary));
}

static bool equal_ascii_ci(const char *first, const char *second) {
	if (first == NULL || second == NULL) return false;
	while (*first != '\0' && *second != '\0') {
		unsigned char a = (unsigned char)*first++;
		unsigned char b = (unsigned char)*second++;
		if (tolower(a) != tolower(b)) return false;
	}
	return *first == '\0' && *second == '\0';
}

static bool parse_vertical_direction(const char *text,
		enum wtwm_icon_layout_direction *direction) {
	if (equal_ascii_ci(text, "North")) {
		*direction = WTWM_ICON_LAYOUT_NORTH;
		return true;
	}
	if (equal_ascii_ci(text, "South")) {
		*direction = WTWM_ICON_LAYOUT_SOUTH;
		return true;
	}
	return false;
}

static bool parse_horizontal_direction(const char *text,
		enum wtwm_icon_layout_direction *direction) {
	if (equal_ascii_ci(text, "East")) {
		*direction = WTWM_ICON_LAYOUT_EAST;
		return true;
	}
	if (equal_ascii_ci(text, "West")) {
		*direction = WTWM_ICON_LAYOUT_WEST;
		return true;
	}
	return false;
}

static bool parse_decimal(const char **cursor, int64_t *value) {
	const unsigned char *text = (const unsigned char *)*cursor;
	if (!isdigit(*text)) return false;
	int64_t result = 0;
	do {
		int digit = *text - '0';
		if (result > (INT_MAX - digit) / 10) return false;
		result = result * 10 + digit;
		++text;
	} while (isdigit(*text));
	*cursor = (const char *)text;
	*value = result;
	return true;
}

static bool parse_offset(const char **cursor, int64_t *value,
		bool *negative) {
	if (**cursor != '+' && **cursor != '-') return false;
	*negative = **cursor == '-';
	++*cursor;
	int64_t magnitude;
	if (!parse_decimal(cursor, &magnitude)) return false;
	*value = *negative ? -magnitude : magnitude;
	return true;
}

static bool parse_geometry(const char *text, int output_width, int output_height,
		int *x, int *y, int *width, int *height) {
	if (text == NULL || output_width <= 0 || output_height <= 0) return false;
	const char *cursor = text;
	if (*cursor == '=') ++cursor;

	int64_t parsed_width;
	int64_t parsed_height;
	if (!parse_decimal(&cursor, &parsed_width) ||
			(*cursor != 'x' && *cursor != 'X')) return false;
	++cursor;
	if (!parse_decimal(&cursor, &parsed_height) ||
			parsed_width <= 0 || parsed_height <= 0) return false;

	int64_t parsed_x = 0;
	int64_t parsed_y = 0;
	bool x_negative = false;
	bool y_negative = false;
	if (*cursor == '+' || *cursor == '-') {
		if (!parse_offset(&cursor, &parsed_x, &x_negative)) return false;
		if (*cursor == '+' || *cursor == '-') {
			if (!parse_offset(&cursor, &parsed_y, &y_negative)) return false;
		}
	}
	if (*cursor != '\0') return false;

	if (x_negative) parsed_x += (int64_t)output_width - parsed_width;
	if (y_negative) parsed_y += (int64_t)output_height - parsed_height;
	int64_t right = parsed_x + parsed_width;
	int64_t bottom = parsed_y + parsed_height;
	if (parsed_x < INT_MIN || parsed_x > INT_MAX ||
			parsed_y < INT_MIN || parsed_y > INT_MAX ||
			right < INT_MIN || right > INT_MAX ||
			bottom < INT_MIN || bottom > INT_MAX) return false;

	*x = (int)parsed_x;
	*y = (int)parsed_y;
	*width = (int)parsed_width;
	*height = (int)parsed_height;
	return true;
}

bool wtwm_icon_layout_region_from_config(const struct wtwm_icon_region *config,
		int output_width, int output_height,
		struct wtwm_icon_layout_region *region) {
	if (config == NULL || region == NULL) return false;
	struct wtwm_icon_layout_region converted = {0};
	if (!parse_geometry(config->geometry, output_width, output_height,
			&converted.x, &converted.y, &converted.width, &converted.height) ||
			!parse_vertical_direction(config->vertical_gravity,
				&converted.primary) ||
			!parse_horizontal_direction(config->horizontal_gravity,
				&converted.secondary)) return false;
	converted.grid_width = config->grid_width > 0 ? config->grid_width : 1;
	converted.grid_height = config->grid_height > 0 ? config->grid_height : 1;
	*region = converted;
	return true;
}

bool wtwm_icon_reference_clamp(int screen_x, int screen_y, int screen_width,
		int screen_height, int icon_width, int icon_height, int *x, int *y) {
	if (screen_width <= 0 || screen_height <= 0 || icon_width <= 0 ||
			icon_height <= 0 || x == NULL || y == NULL) return false;

	int64_t right = (int64_t)screen_x + screen_width;
	int64_t bottom = (int64_t)screen_y + screen_height;
	int64_t adjusted_x = *x;
	int64_t adjusted_y = *y;
	if (adjusted_x > right) adjusted_x = right - icon_width;
	if (adjusted_y > bottom) adjusted_y = bottom - icon_height;
	if (adjusted_x < INT_MIN || adjusted_x > INT_MAX ||
			adjusted_y < INT_MIN || adjusted_y > INT_MAX) return false;

	*x = (int)adjusted_x;
	*y = (int)adjusted_y;
	return true;
}

static void free_entries(struct icon_entry *entry) {
	while (entry != NULL) {
		struct icon_entry *next = entry->next;
		free(entry);
		entry = next;
	}
}

void wtwm_icon_layout_destroy(struct wtwm_icon_layout *layout) {
	if (layout == NULL) return;
	for (size_t i = 0; i < layout->region_count; ++i)
		free_entries(layout->regions[i].entries);
	free(layout->regions);
	free(layout);
}

struct wtwm_icon_layout *wtwm_icon_layout_create(
		const struct wtwm_icon_layout_region *regions, size_t region_count) {
	if (region_count > 0 && regions == NULL) return NULL;
	if (region_count > SIZE_MAX / sizeof(struct icon_region_state)) return NULL;
	struct wtwm_icon_layout *layout = calloc(1, sizeof(*layout));
	if (layout == NULL) return NULL;
	if (region_count > 0) {
		layout->regions = calloc(region_count, sizeof(*layout->regions));
		if (layout->regions == NULL) {
			free(layout);
			return NULL;
		}
	}
	layout->region_count = region_count;

	for (size_t i = 0; i < region_count; ++i) {
		if (regions[i].width <= 0 || regions[i].height <= 0 ||
				!valid_directions(regions[i].primary, regions[i].secondary)) {
			wtwm_icon_layout_destroy(layout);
			return NULL;
		}
		int64_t right = (int64_t)regions[i].x + regions[i].width;
		int64_t bottom = (int64_t)regions[i].y + regions[i].height;
		if (right < INT_MIN || right > INT_MAX ||
				bottom < INT_MIN || bottom > INT_MAX) {
			wtwm_icon_layout_destroy(layout);
			return NULL;
		}

		layout->regions[i].geometry = regions[i];
		if (layout->regions[i].geometry.grid_width <= 0)
			layout->regions[i].geometry.grid_width = 1;
		if (layout->regions[i].geometry.grid_height <= 0)
			layout->regions[i].geometry.grid_height = 1;
		struct icon_entry *entry = calloc(1, sizeof(*entry));
		if (entry == NULL) {
			wtwm_icon_layout_destroy(layout);
			return NULL;
		}
		entry->x = regions[i].x;
		entry->y = regions[i].y;
		entry->width = regions[i].width;
		entry->height = regions[i].height;
		layout->regions[i].entries = entry;
	}
	return layout;
}

static bool rounded_dimension(int value, int step, int *rounded) {
	int64_t result = ((int64_t)value + step - 1) / step * step;
	if (result > INT_MAX) return false;
	*rounded = (int)result;
	return true;
}

static struct icon_entry *take_entry(struct icon_entry **pool, size_t *used) {
	return pool[(*used)++];
}

static void split_entry(struct icon_entry *entry,
		enum wtwm_icon_layout_direction primary,
		enum wtwm_icon_layout_direction secondary, int width, int height,
		struct icon_entry **pool, size_t *pool_used) {
	if (direction_is_vertical(primary)) {
		if (width != entry->width)
			split_entry(entry, secondary, primary, width, entry->height,
				pool, pool_used);
		if (height != entry->height) {
			struct icon_entry *remainder = take_entry(pool, pool_used);
			remainder->next = entry->next;
			entry->next = remainder;
			remainder->x = entry->x;
			remainder->height = entry->height - height;
			remainder->width = entry->width;
			entry->height = height;
			if (primary == WTWM_ICON_LAYOUT_SOUTH) {
				remainder->y = entry->y;
				entry->y = remainder->y + remainder->height;
			} else {
				remainder->y = entry->y + entry->height;
			}
		}
		return;
	}

	if (height != entry->height)
		split_entry(entry, secondary, primary, entry->width, height,
			pool, pool_used);
	if (width != entry->width) {
		struct icon_entry *remainder = take_entry(pool, pool_used);
		remainder->next = entry->next;
		entry->next = remainder;
		remainder->y = entry->y;
		remainder->width = entry->width - width;
		remainder->height = entry->height;
		entry->width = width;
		if (primary == WTWM_ICON_LAYOUT_EAST) {
			remainder->x = entry->x;
			entry->x = remainder->x + remainder->width;
		} else {
			remainder->x = entry->x + entry->width;
		}
	}
}

static void set_placement(size_t region_index, const struct icon_entry *entry,
		struct wtwm_icon_layout_placement *placement) {
	if (placement == NULL) return;
	placement->region_index = region_index;
	placement->x = entry->x + (entry->width - entry->icon_width) / 2;
	placement->y = entry->y + (entry->height - entry->icon_height) / 2;
	placement->width = entry->icon_width;
	placement->height = entry->icon_height;
	placement->cell_x = entry->x;
	placement->cell_y = entry->y;
	placement->cell_width = entry->width;
	placement->cell_height = entry->height;
}

bool wtwm_icon_layout_lookup(const struct wtwm_icon_layout *layout,
		uint64_t key, struct wtwm_icon_layout_placement *placement) {
	if (layout == NULL || key == 0) return false;
	for (size_t i = 0; i < layout->region_count; ++i) {
		for (const struct icon_entry *entry = layout->regions[i].entries;
				entry != NULL; entry = entry->next) {
			if (entry->key == key) {
				set_placement(i, entry, placement);
				return true;
			}
		}
	}
	return false;
}

bool wtwm_icon_layout_contains_point(const struct wtwm_icon_layout *layout,
		int x, int y) {
	if (layout == NULL) return false;
	for (size_t i = 0; i < layout->region_count; ++i) {
		const struct wtwm_icon_layout_region *region =
			&layout->regions[i].geometry;
		int64_t right = (int64_t)region->x + region->width;
		int64_t bottom = (int64_t)region->y + region->height;
		if ((int64_t)x >= region->x && (int64_t)x < right &&
				(int64_t)y >= region->y && (int64_t)y < bottom)
			return true;
	}
	return false;
}

enum wtwm_icon_layout_result wtwm_icon_layout_allocate(
		struct wtwm_icon_layout *layout, uint64_t key, int width, int height,
		struct wtwm_icon_layout_placement *placement) {
	if (layout == NULL || key == 0 || width <= 0 || height <= 0)
		return WTWM_ICON_LAYOUT_INVALID;
	if (wtwm_icon_layout_lookup(layout, key, NULL))
		return WTWM_ICON_LAYOUT_DUPLICATE;

	for (size_t i = 0; i < layout->region_count; ++i) {
		struct icon_region_state *region = &layout->regions[i];
		int rounded_width;
		int rounded_height;
		if (!rounded_dimension(width, region->geometry.grid_width,
				&rounded_width) ||
				!rounded_dimension(height, region->geometry.grid_height,
					&rounded_height)) continue;

		for (struct icon_entry *entry = region->entries; entry != NULL;
				entry = entry->next) {
			if (entry->key != 0 || entry->width < rounded_width ||
					entry->height < rounded_height) continue;

			size_t split_count = (entry->width != rounded_width) +
				(entry->height != rounded_height);
			struct icon_entry *pool[2] = {NULL, NULL};
			for (size_t j = 0; j < split_count; ++j) {
				pool[j] = calloc(1, sizeof(*pool[j]));
				if (pool[j] == NULL) {
					for (size_t k = 0; k < j; ++k) free(pool[k]);
					return WTWM_ICON_LAYOUT_OUT_OF_MEMORY;
				}
			}
			size_t pool_used = 0;
			split_entry(entry, region->geometry.primary,
				region->geometry.secondary, rounded_width, rounded_height,
				pool, &pool_used);
			entry->key = key;
			entry->icon_width = width;
			entry->icon_height = height;
			++layout->allocation_count;
			set_placement(i, entry, placement);
			return WTWM_ICON_LAYOUT_OK;
		}
	}
	return WTWM_ICON_LAYOUT_FULL;
}

static struct icon_entry *previous_entry(struct icon_region_state *region,
		struct icon_entry *entry) {
	if (entry == region->entries) return NULL;
	struct icon_entry *previous = region->entries;
	while (previous != NULL && previous->next != entry)
		previous = previous->next;
	return previous;
}

static bool mergeable(const struct icon_entry *first,
		const struct icon_entry *second) {
	return (first->x == second->x && first->width == second->width) ||
		(first->y == second->y && first->height == second->height);
}

static void merge_entries(const struct icon_entry *old,
		struct icon_entry *kept) {
	if (old->y == kept->y) {
		kept->width += old->width;
		if (old->x < kept->x) kept->x = old->x;
	} else {
		kept->height += old->height;
		if (old->y < kept->y) kept->y = old->y;
	}
}

bool wtwm_icon_layout_release(struct wtwm_icon_layout *layout, uint64_t key) {
	if (layout == NULL || key == 0) return false;
	for (size_t i = 0; i < layout->region_count; ++i) {
		struct icon_region_state *region = &layout->regions[i];
		for (struct icon_entry *entry = region->entries; entry != NULL;
				entry = entry->next) {
			if (entry->key != key) continue;
			entry->key = 0;
			entry->icon_width = 0;
			entry->icon_height = 0;
			struct icon_entry *previous = previous_entry(region, entry);
			struct icon_entry *next = entry->next;
			for (;;) {
				if (previous != NULL && previous->key == 0 &&
						mergeable(previous, entry)) {
					previous->next = entry->next;
					merge_entries(entry, previous);
					free(entry);
					entry = previous;
					previous = previous_entry(region, entry);
				} else if (next != NULL && next->key == 0 &&
						mergeable(next, entry)) {
					entry->next = next->next;
					merge_entries(next, entry);
					free(next);
					next = entry->next;
				} else {
					break;
				}
			}
			--layout->allocation_count;
			return true;
		}
	}
	return false;
}

size_t wtwm_icon_layout_allocation_count(const struct wtwm_icon_layout *layout) {
	return layout == NULL ? 0 : layout->allocation_count;
}
