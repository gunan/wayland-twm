/* SPDX-License-Identifier: MIT */
#include <wtwm/placement.h>

#include <ctype.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static int saturate_int(int64_t value) {
	if (value > INT_MAX) return INT_MAX;
	if (value < INT_MIN) return INT_MIN;
	return (int)value;
}

struct uint128_value {
	uint64_t high;
	uint64_t low;
};

static struct uint128_value uint128_add(struct uint128_value left,
		struct uint128_value right) {
	struct uint128_value result = {
		.high = left.high + right.high,
		.low = left.low + right.low,
	};
	if (result.low < left.low) ++result.high;
	return result;
}

static struct uint128_value uint128_square(uint64_t value) {
	uint64_t low = value & UINT32_MAX;
	uint64_t high = value >> 32;
	uint64_t low_square = low * low;
	uint64_t cross = low * high;
	struct uint128_value result = {
		.high = high * high + (cross >> 31),
		.low = low_square + (cross << 33),
	};
	if (result.low < low_square) ++result.high;
	return result;
}

static int uint128_compare(struct uint128_value left,
		struct uint128_value right) {
	if (left.high != right.high) return left.high < right.high ? -1 : 1;
	if (left.low != right.low) return left.low < right.low ? -1 : 1;
	return 0;
}

static uint64_t absolute_difference(int64_t left, int64_t right) {
	return left >= right ? (uint64_t)(left - right) :
		(uint64_t)(right - left);
}

static bool valid_area(const struct wtwm_placement_area *area) {
	return area != NULL && area->width > 0 && area->height > 0;
}

static bool area_contains(const struct wtwm_placement_area *area,
		int point_x, int point_y) {
	int64_t right = (int64_t)area->x + area->width;
	int64_t bottom = (int64_t)area->y + area->height;
	return valid_area(area) && point_x >= area->x && (int64_t)point_x < right &&
		point_y >= area->y && (int64_t)point_y < bottom;
}

static struct uint128_value distance_to_area(const struct wtwm_placement_area *area,
		int64_t point_x, int64_t point_y, int scale) {
	int64_t left = (int64_t)scale * area->x;
	int64_t top = (int64_t)scale * area->y;
	int64_t right = (int64_t)scale * ((int64_t)area->x + area->width);
	int64_t bottom = (int64_t)scale * ((int64_t)area->y + area->height);
	uint64_t dx = point_x < left ? absolute_difference(point_x, left) :
		(point_x > right ? absolute_difference(point_x, right) : 0);
	uint64_t dy = point_y < top ? absolute_difference(point_y, top) :
		(point_y > bottom ? absolute_difference(point_y, bottom) : 0);
	return uint128_add(uint128_square(dx), uint128_square(dy));
}

bool wtwm_placement_output_for_point(const struct wtwm_placement_area *areas,
		size_t count, int point_x, int point_y, size_t *selected) {
	if (areas == NULL || selected == NULL) return false;
	for (size_t i = 0; i < count; ++i) {
		if (area_contains(&areas[i], point_x, point_y)) {
			*selected = i;
			return true;
		}
	}
	bool found = false;
	struct uint128_value best = {0, 0};
	for (size_t i = 0; i < count; ++i) {
		if (!valid_area(&areas[i])) continue;
		struct uint128_value distance = distance_to_area(&areas[i],
			point_x, point_y, 1);
		if (!found || uint128_compare(distance, best) < 0) {
			found = true;
			best = distance;
			*selected = i;
		}
	}
	return found;
}

static uint64_t intersection_area(const struct wtwm_placement_area *area,
		int x, int y, int width, int height) {
	if (!valid_area(area) || width <= 0 || height <= 0) return 0;
	int64_t left = x > area->x ? x : area->x;
	int64_t top = y > area->y ? y : area->y;
	int64_t outer_right = (int64_t)x + width;
	int64_t outer_bottom = (int64_t)y + height;
	int64_t area_right = (int64_t)area->x + area->width;
	int64_t area_bottom = (int64_t)area->y + area->height;
	int64_t right = outer_right < area_right ? outer_right : area_right;
	int64_t bottom = outer_bottom < area_bottom ? outer_bottom : area_bottom;
	if (right <= left || bottom <= top) return 0;
	return (uint64_t)(right - left) * (uint64_t)(bottom - top);
}

bool wtwm_placement_output_for_outer(const struct wtwm_placement_area *areas,
		size_t count, int outer_x, int outer_y, int outer_width, int outer_height,
		size_t *selected) {
	if (areas == NULL || selected == NULL) return false;
	bool found = false;
	uint64_t best_intersection = 0;
	for (size_t i = 0; i < count; ++i) {
		uint64_t intersection = intersection_area(&areas[i], outer_x, outer_y,
			outer_width, outer_height);
		if (intersection > best_intersection) {
			found = true;
			best_intersection = intersection;
			*selected = i;
		}
	}
	if (found) return true;
	int64_t center_x = (int64_t)2 * outer_x +
		(outer_width > 0 ? outer_width : 0);
	int64_t center_y = (int64_t)2 * outer_y +
		(outer_height > 0 ? outer_height : 0);
	struct uint128_value best = {0, 0};
	for (size_t i = 0; i < count; ++i) {
		if (!valid_area(&areas[i])) continue;
		struct uint128_value distance = distance_to_area(&areas[i],
			center_x, center_y, 2);
		if (!found || uint128_compare(distance, best) < 0) {
			found = true;
			best = distance;
			*selected = i;
		}
	}
	return found;
}

bool wtwm_parse_use_p_position(const char *text,
		enum wtwm_use_p_position *mode) {
	if (text == NULL || mode == NULL) return false;
	if (strcasecmp(text, "off") == 0) {
		*mode = WTWM_USE_P_POSITION_OFF;
		return true;
	}
	if (strcasecmp(text, "on") == 0) {
		*mode = WTWM_USE_P_POSITION_ON;
		return true;
	}
	if (strcasecmp(text, "non-zero") == 0 ||
			strcasecmp(text, "nonzero") == 0) {
		*mode = WTWM_USE_P_POSITION_NON_ZERO;
		return true;
	}
	return false;
}

static bool parse_unsigned_dimension(const char **cursor, int *dimension) {
	const unsigned char *start = (const unsigned char *)*cursor;
	if (!isdigit(*start)) return false;
	char *end = NULL;
	unsigned long value = strtoul(*cursor, &end, 10);
	if (end == *cursor || value == 0 || value > INT_MAX) return false;
	*cursor = end;
	*dimension = (int)value;
	return true;
}

static bool parse_offset(const char **cursor) {
	if (**cursor != '+' && **cursor != '-') return false;
	++*cursor;
	const unsigned char *start = (const unsigned char *)*cursor;
	if (!isdigit(*start)) return false;
	while (isdigit((unsigned char)**cursor)) ++*cursor;
	return true;
}

bool wtwm_parse_max_window_size(const char *text, int *width, int *height) {
	if (text == NULL || width == NULL || height == NULL) return false;
	const char *cursor = text;
	if (*cursor == '=') ++cursor;
	int parsed_width = 0, parsed_height = 0;
	if (!parse_unsigned_dimension(&cursor, &parsed_width) ||
			(*cursor != 'x' && *cursor != 'X')) return false;
	++cursor;
	if (!parse_unsigned_dimension(&cursor, &parsed_height)) return false;
	if (*cursor != '\0' && !parse_offset(&cursor)) return false;
	if (*cursor != '\0' && !parse_offset(&cursor)) return false;
	if (*cursor != '\0') return false;
	*width = parsed_width;
	*height = parsed_height;
	return true;
}

void wtwm_default_max_window_size(int screen_width, int screen_height,
		int *width, int *height) {
	int64_t derived_width = INT16_MAX - (int64_t)screen_width;
	int64_t derived_height = INT16_MAX - (int64_t)screen_height;
	*width = derived_width > 0 ? saturate_int(derived_width) : 1;
	*height = derived_height > 0 ? saturate_int(derived_height) : 1;
}

void wtwm_clip_initial_size(int max_width, int max_height,
		int *width, int *height) {
	if (max_width < 1) max_width = 1;
	if (max_height < 1) max_height = 1;
	if (*width > max_width) *width = max_width;
	if (*height > max_height) *height = max_height;
	if (*width < 1) *width = 1;
	if (*height < 1) *height = 1;
}

bool wtwm_placement_asks_user(bool transient, bool us_position,
		bool p_position, enum wtwm_use_p_position use_p_position,
		int requested_x, int requested_y) {
	if (transient || us_position) return false;
	if (!p_position || use_p_position == WTWM_USE_P_POSITION_OFF) return true;
	if (use_p_position == WTWM_USE_P_POSITION_ON) return false;
	return requested_x == 0 && requested_y == 0;
}

void wtwm_random_placement_init(struct wtwm_random_placement *state) {
	state->next_x = 50;
	state->next_y = 50;
}

void wtwm_random_placement_seed(struct wtwm_random_placement *state,
		unsigned index) {
	int64_t coordinate = 50 + (int64_t)30 * index;
	state->next_x = saturate_int(coordinate);
	state->next_y = saturate_int(coordinate);
}

static int edge_adjust(int next, int screen, int client) {
	if ((int64_t)next + client <= screen) return next;
	int adjusted = saturate_int((int64_t)screen - client);
	if (adjusted < 0) adjusted = 0;
	if (adjusted > 50) adjusted = 50;
	return adjusted;
}

void wtwm_random_placement_next(struct wtwm_random_placement *state,
		int screen_width, int screen_height, int client_width, int client_height,
		int *x, int *y) {
	state->next_x = edge_adjust(state->next_x, screen_width, client_width);
	state->next_y = edge_adjust(state->next_y, screen_height, client_height);
	*x = state->next_x;
	*y = state->next_y;
	state->next_x = saturate_int((int64_t)state->next_x + 30);
	state->next_y = saturate_int((int64_t)state->next_y + 30);
}

void wtwm_pointer_placement(unsigned index, int pointer_x, int pointer_y,
		int *x, int *y) {
	(void)index;
	*x = pointer_x;
	*y = pointer_y;
}

enum wtwm_placement_button_action wtwm_placement_button(unsigned button) {
	switch (button) {
	case 1: return WTWM_PLACEMENT_BUTTON_CONFIRM;
	case 2: return WTWM_PLACEMENT_BUTTON_RESIZE;
	case 3: return WTWM_PLACEMENT_BUTTON_FILL;
	default: return WTWM_PLACEMENT_BUTTON_IGNORE;
	}
}

void wtwm_placement_prompt_position(const struct wtwm_placement_area *area,
		bool dont_move_off, int outer_width, int outer_height,
		int pointer_x, int pointer_y, int *x, int *y) {
	*x = pointer_x;
	*y = pointer_y;
	if (dont_move_off)
		wtwm_clamp_outer_position(area, outer_width, outer_height, x, y);
}

void wtwm_placement_fill_size(const struct wtwm_placement_area *area,
		int x, int y, int horizontal_inset, int vertical_inset,
		int *client_width, int *client_height) {
	int64_t right = area != NULL ? (int64_t)area->x + area->width : x + 1;
	int64_t bottom = area != NULL ? (int64_t)area->y + area->height : y + 1;
	int64_t width = right - x - horizontal_inset;
	int64_t height = bottom - y - vertical_inset;
	*client_width = width > 0 ? saturate_int(width) : 1;
	*client_height = height > 0 ? saturate_int(height) : 1;
}

void wtwm_clamp_outer_position(const struct wtwm_placement_area *area,
		int outer_width, int outer_height, int *x, int *y) {
	if (area == NULL || area->width <= 0 || area->height <= 0) return;
	int max_x = saturate_int((int64_t)area->x + area->width - outer_width);
	int max_y = saturate_int((int64_t)area->y + area->height - outer_height);
	/* Reference move/placement checks the near edge, then the far edge. */
	if (*x < area->x) *x = area->x;
	if (*y < area->y) *y = area->y;
	if (*x > max_x) *x = max_x;
	if (*y > max_y) *y = max_y;
}

const char *wtwm_placement_kind_name(enum wtwm_placement_kind kind) {
	switch (kind) {
	case WTWM_PLACEMENT_REQUESTED: return "requested";
	case WTWM_PLACEMENT_RANDOM: return "random";
	case WTWM_PLACEMENT_INTERACTIVE: return "interactive";
	case WTWM_PLACEMENT_POINTER: return "pointer";
	case WTWM_PLACEMENT_REMAPPED: return "remapped";
	}
	return "unknown";
}
