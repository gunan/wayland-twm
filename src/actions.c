/* SPDX-License-Identifier: MIT */

#include "wtwm/actions.h"

#include <limits.h>
#include <string.h>

static int at_least_one(int value) {
	return value > 0 ? value : 1;
}

bool wtwm_action_is_zoom(enum wtwm_action_type type) {
	switch (type) {
	case WTWM_ACTION_ZOOM:
	case WTWM_ACTION_HORIZOOM:
	case WTWM_ACTION_FULLZOOM:
	case WTWM_ACTION_LEFTZOOM:
	case WTWM_ACTION_RIGHTZOOM:
	case WTWM_ACTION_TOPZOOM:
	case WTWM_ACTION_BOTTOMZOOM:
		return true;
	default:
		return false;
	}
}

struct wtwm_interaction_box wtwm_action_zoom(
		enum wtwm_action_type type,
		const struct wtwm_interaction_box *output,
		int decoration_width, int decoration_height,
		const struct wtwm_interaction_box *current,
		struct wtwm_zoom_state *state) {
	if (!wtwm_action_is_zoom(type) || output == NULL || current == NULL ||
			state == NULL) return current != NULL ? *current :
			(struct wtwm_interaction_box){0};
	if (state->mode == type) {
		struct wtwm_interaction_box restored = state->saved;
		state->mode = WTWM_ACTION_NOP;
		return restored;
	}
	if (!wtwm_action_is_zoom(state->mode)) state->saved = *current;
	state->mode = type;
	struct wtwm_interaction_box result = *current;
	int full_width = at_least_one(output->width - decoration_width);
	int full_height = at_least_one(output->height - decoration_height);
	int half_width = at_least_one(output->width / 2 - decoration_width);
	int half_height = at_least_one(output->height / 2 - decoration_height);
	switch (type) {
	case WTWM_ACTION_ZOOM:
		result.y = output->y;
		result.height = full_height;
		break;
	case WTWM_ACTION_HORIZOOM:
		result.x = output->x;
		result.width = full_width;
		break;
	case WTWM_ACTION_FULLZOOM:
		result.x = output->x;
		result.y = output->y;
		result.width = full_width;
		result.height = full_height;
		break;
	case WTWM_ACTION_LEFTZOOM:
		result.x = output->x;
		result.y = output->y;
		result.width = half_width;
		result.height = full_height;
		break;
	case WTWM_ACTION_RIGHTZOOM:
		result.x = output->x + output->width / 2;
		result.y = output->y;
		result.width = half_width;
		result.height = full_height;
		break;
	case WTWM_ACTION_TOPZOOM:
		result.x = output->x;
		result.y = output->y;
		result.width = full_width;
		result.height = half_height;
		break;
	case WTWM_ACTION_BOTTOMZOOM:
		result.x = output->x;
		result.y = output->y + output->height / 2;
		result.width = full_width;
		result.height = half_height;
		break;
	default:
		break;
	}
	return result;
}

int wtwm_action_cycle_index(int count, int current, bool forward) {
	if (count <= 0) return -1;
	if (current < 0 || current >= count) return forward ? 0 : count - 1;
	return forward ? (current + 1) % count : (current + count - 1) % count;
}

int wtwm_action_screen_target(const char *argument, int current,
		int previous, int count) {
	if (argument == NULL || count <= 0) return -1;
	if (strcmp(argument, "next") == 0)
		return (current + 1) % count;
	if (strcmp(argument, "prev") == 0)
		return (current + count - 1) % count;
	if (strcmp(argument, "back") == 0)
		return previous >= 0 && previous < count ? previous : current;
	if (argument[0] == '\0') return -1;
	int parsed = 0;
	for (const unsigned char *cursor = (const unsigned char *)argument;
			*cursor != '\0'; ++cursor) {
		if (*cursor < '0' || *cursor > '9') return -1;
		int digit = *cursor - '0';
		if (parsed > (INT_MAX - digit) / 10) return -1;
		parsed = parsed * 10 + digit;
	}
	return parsed < count ? parsed : -1;
}
