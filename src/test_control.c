/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "test_control.h"

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void set_error(char *error, size_t size, const char *format, ...) {
	if (error == NULL || size == 0) return;
	va_list args;
	va_start(args, format);
	vsnprintf(error, size, format, args);
	va_end(args);
}

static char *next_word(char **cursor) {
	char *word = *cursor;
	while (*word == ' ' || *word == '\t') ++word;
	if (*word == '\0') {
		*cursor = word;
		return NULL;
	}
	char *end = word;
	while (*end != '\0' && *end != ' ' && *end != '\t') ++end;
	if (*end != '\0') *end++ = '\0';
	*cursor = end;
	return word;
}

static char *remaining_text(char *cursor) {
	while (*cursor == ' ' || *cursor == '\t') ++cursor;
	char *end = cursor + strlen(cursor);
	while (end > cursor && (end[-1] == ' ' || end[-1] == '\t')) --end;
	*end = '\0';
	return cursor;
}

static bool parse_int(const char *text, int minimum, int maximum, int *value) {
	if (text == NULL || *text == '\0') return false;
	errno = 0;
	char *end = NULL;
	long parsed = strtol(text, &end, 10);
	if (errno != 0 || *end != '\0' || parsed < minimum || parsed > maximum)
		return false;
	*value = (int)parsed;
	return true;
}

static bool parse_double(const char *text, double *value) {
	if (text == NULL || *text == '\0') return false;
	errno = 0;
	char *end = NULL;
	double parsed = strtod(text, &end);
	if (errno != 0 || *end != '\0' || !isfinite(parsed)) return false;
	*value = parsed;
	return true;
}

static bool no_more_words(char *cursor) {
	return next_word(&cursor) == NULL;
}

static bool parse_state(const char *text, bool *pressed) {
	if (text != NULL && strcmp(text, "press") == 0) {
		*pressed = true;
		return true;
	}
	if (text != NULL && strcmp(text, "release") == 0) {
		*pressed = false;
		return true;
	}
	return false;
}

static bool set_output_name(struct wtwm_test_command *command,
		const char *name) {
	if (name == NULL || *name == '\0' ||
			strlen(name) >= sizeof(command->output_name)) return false;
	strcpy(command->output_name, name);
	return true;
}

static bool parse_output_transform(const char *text,
		enum wtwm_test_output_transform *transform) {
	static const struct {
		const char *name;
		enum wtwm_test_output_transform transform;
	} transforms[] = {
		{"normal", WTWM_TEST_TRANSFORM_NORMAL},
		{"90", WTWM_TEST_TRANSFORM_90},
		{"180", WTWM_TEST_TRANSFORM_180},
		{"270", WTWM_TEST_TRANSFORM_270},
		{"flipped", WTWM_TEST_TRANSFORM_FLIPPED},
		{"flipped-90", WTWM_TEST_TRANSFORM_FLIPPED_90},
		{"flipped-180", WTWM_TEST_TRANSFORM_FLIPPED_180},
		{"flipped-270", WTWM_TEST_TRANSFORM_FLIPPED_270},
	};
	if (text == NULL) return false;
	for (size_t i = 0; i < sizeof(transforms) / sizeof(transforms[0]); ++i) {
		if (strcmp(text, transforms[i].name) == 0) {
			*transform = transforms[i].transform;
			return true;
		}
	}
	return false;
}

static bool parse_output_command(char *cursor,
		struct wtwm_test_command *command, char *error, size_t error_size) {
	char *operation = next_word(&cursor);
	int width = 0;
	if (parse_int(operation, 1, 16384, &width)) {
		char *height = next_word(&cursor);
		if (!parse_int(height, 1, 16384, &command->second) ||
				!no_more_words(cursor)) {
			set_error(error, error_size, "usage: OUTPUT width height");
			return false;
		}
		command->output_operation = WTWM_TEST_OUTPUT_ADD;
		command->first = width;
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
	}
	if (operation == NULL) {
		set_error(error, error_size, "usage: OUTPUT width height|operation ...");
		return false;
	}

	char *name = next_word(&cursor);
	if (!set_output_name(command, name)) {
		set_error(error, error_size, "OUTPUT %s requires an output name", operation);
		return false;
	}
	if (strcmp(operation, "DESTROY") == 0 ||
			strcmp(operation, "ENABLE") == 0 ||
			strcmp(operation, "DISABLE") == 0) {
		if (!no_more_words(cursor)) {
			set_error(error, error_size, "usage: OUTPUT %s name", operation);
			return false;
		}
		command->output_operation = strcmp(operation, "DESTROY") == 0 ?
			WTWM_TEST_OUTPUT_DESTROY :
			strcmp(operation, "ENABLE") == 0 ? WTWM_TEST_OUTPUT_ENABLE :
			WTWM_TEST_OUTPUT_DISABLE;
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
	}
	if (strcmp(operation, "MODE") == 0) {
		char *width_text = next_word(&cursor);
		char *height_text = next_word(&cursor);
		char *refresh_text = next_word(&cursor);
		if (!parse_int(width_text, 1, 16384, &command->first) ||
				!parse_int(height_text, 1, 16384, &command->second) ||
				!parse_int(refresh_text, 0, 1000000, &command->third) ||
				!no_more_words(cursor)) {
			set_error(error, error_size,
				"usage: OUTPUT MODE name width height refresh_mhz");
			return false;
		}
		command->output_operation = WTWM_TEST_OUTPUT_MODE;
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
	}
	if (strcmp(operation, "SCALE") == 0) {
		char *scale = next_word(&cursor);
		if (!parse_double(scale, &command->x) || command->x < 0.25 ||
				command->x > 16.0 || !no_more_words(cursor)) {
			set_error(error, error_size, "usage: OUTPUT SCALE name scale");
			return false;
		}
		command->output_operation = WTWM_TEST_OUTPUT_SCALE;
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
	}
	if (strcmp(operation, "TRANSFORM") == 0) {
		char *transform = next_word(&cursor);
		if (!parse_output_transform(transform, &command->output_transform) ||
				!no_more_words(cursor)) {
			set_error(error, error_size,
				"usage: OUTPUT TRANSFORM name normal|90|180|270|"
				"flipped|flipped-90|flipped-180|flipped-270");
			return false;
		}
		command->output_operation = WTWM_TEST_OUTPUT_TRANSFORM;
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
	}
	if (strcmp(operation, "POSITION") == 0) {
		char *x = next_word(&cursor);
		if (x != NULL && strcmp(x, "AUTO") == 0 && no_more_words(cursor)) {
			command->output_auto = true;
		} else {
			char *y = next_word(&cursor);
			if (!parse_int(x, -1000000, 1000000, &command->first) ||
					!parse_int(y, -1000000, 1000000, &command->second) ||
					!no_more_words(cursor)) {
				set_error(error, error_size,
					"usage: OUTPUT POSITION name AUTO|x y");
				return false;
			}
		}
		command->output_operation = WTWM_TEST_OUTPUT_POSITION;
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
	}
	set_error(error, error_size, "unknown OUTPUT operation: %s", operation);
	return false;
}

bool wtwm_test_command_parse(const char *line, struct wtwm_test_command *command,
	char *error, size_t error_size) {
	if (line == NULL || command == NULL) {
		set_error(error, error_size, "invalid parser arguments");
		return false;
	}
	if (strlen(line) >= WTWM_TEST_CONTROL_TEXT_MAX) {
		set_error(error, error_size, "command is too long");
		return false;
	}
	char input[WTWM_TEST_CONTROL_TEXT_MAX];
	strcpy(input, line);
	char *newline = strpbrk(input, "\r\n");
	if (newline != NULL) *newline = '\0';
	char *cursor = input;
	char *verb = next_word(&cursor);
	memset(command, 0, sizeof(*command));
	if (verb == NULL) {
		set_error(error, error_size, "empty command");
		return false;
	}
	if (strcmp(verb, "PING") == 0 || strcmp(verb, "STATE") == 0 ||
		strcmp(verb, "QUIT") == 0) {
		if (!no_more_words(cursor)) {
			set_error(error, error_size, "%s takes no arguments", verb);
			return false;
		}
		command->type = strcmp(verb, "PING") == 0 ? WTWM_TEST_COMMAND_PING :
			strcmp(verb, "STATE") == 0 ? WTWM_TEST_COMMAND_STATE :
			WTWM_TEST_COMMAND_QUIT;
		return true;
	}
	if (strcmp(verb, "TRACE") == 0) {
		char *option = next_word(&cursor);
		if (option != NULL && strcmp(option, "CLEAR") == 0 && no_more_words(cursor)) {
			command->first = 1;
		} else if (option != NULL) {
			set_error(error, error_size, "usage: TRACE [CLEAR]");
			return false;
		}
		command->type = WTWM_TEST_COMMAND_TRACE;
		return true;
	}
	if (strcmp(verb, "OUTPUT") == 0) {
		return parse_output_command(cursor, command, error, error_size);
	}
	if (strcmp(verb, "POINTER") == 0) {
		char *x = next_word(&cursor);
		char *y = next_word(&cursor);
		if (!parse_double(x, &command->x) || !parse_double(y, &command->y) ||
			!no_more_words(cursor)) {
			set_error(error, error_size, "usage: POINTER x y");
			return false;
		}
		command->type = WTWM_TEST_COMMAND_POINTER;
		return true;
	}
	if (strcmp(verb, "BUTTON") == 0 || strcmp(verb, "KEY") == 0) {
		int code = 0;
		char *code_text = next_word(&cursor);
		char *state = next_word(&cursor);
		if (!parse_int(code_text, 0, INT_MAX, &code) ||
			!parse_state(state, &command->pressed) || !no_more_words(cursor)) {
			set_error(error, error_size, "usage: %s code press|release", verb);
			return false;
		}
		command->code = (uint32_t)code;
		command->type = strcmp(verb, "BUTTON") == 0 ?
			WTWM_TEST_COMMAND_BUTTON : WTWM_TEST_COMMAND_KEY;
		return true;
	}
	if (strcmp(verb, "WAIT") == 0) {
		char *frames = next_word(&cursor);
		command->first = 1;
		if ((frames != NULL && !parse_int(frames, 1, 120, &command->first)) ||
			!no_more_words(cursor)) {
			set_error(error, error_size, "usage: WAIT [frames]");
			return false;
		}
		command->type = WTWM_TEST_COMMAND_WAIT;
		return true;
	}
	if (strcmp(verb, "CAPTURE") == 0) {
		char *path = remaining_text(cursor);
		if (*path == '\0') {
			set_error(error, error_size, "usage: CAPTURE path");
			return false;
		}
		strcpy(command->text, path);
		command->type = WTWM_TEST_COMMAND_CAPTURE;
		return true;
	}
	if (strcmp(verb, "SET") == 0) {
		char *setting = next_word(&cursor);
		if (setting != NULL && strcmp(setting, "ANIMATION_MS") == 0) {
			char *duration = next_word(&cursor);
			if (!parse_int(duration, 0, 60000, &command->first) ||
				!no_more_words(cursor)) goto invalid_set;
			command->type = WTWM_TEST_COMMAND_SET_ANIMATION_MS;
			return true;
		}
		if (setting != NULL && strcmp(setting, "PLACEMENT_SEED") == 0) {
			char *seed = next_word(&cursor);
			if (!parse_int(seed, 0, INT_MAX, &command->first) ||
				!no_more_words(cursor)) goto invalid_set;
			command->type = WTWM_TEST_COMMAND_SET_PLACEMENT_SEED;
			return true;
		}
		if (setting != NULL && strcmp(setting, "CURSOR") == 0) {
			char *x = next_word(&cursor);
			char *y = next_word(&cursor);
			if (!parse_double(x, &command->x) || !parse_double(y, &command->y) ||
				!no_more_words(cursor)) goto invalid_set;
			command->type = WTWM_TEST_COMMAND_SET_CURSOR;
			return true;
		}
		if (setting != NULL && strcmp(setting, "FONT") == 0) {
			char *font = remaining_text(cursor);
			if (*font == '\0') goto invalid_set;
			strcpy(command->text, font);
			command->type = WTWM_TEST_COMMAND_SET_FONT;
			return true;
		}
	invalid_set:
		set_error(error, error_size,
			"usage: SET ANIMATION_MS n|PLACEMENT_SEED n|CURSOR x y|FONT description");
		return false;
	}
	set_error(error, error_size, "unknown command: %s", verb);
	return false;
}
