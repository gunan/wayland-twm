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
