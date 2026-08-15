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
	if (strcmp(verb, "OUTPUT") == 0) {
		char *width = next_word(&cursor);
		char *height = next_word(&cursor);
		if (!parse_int(width, 1, 16384, &command->first) ||
			!parse_int(height, 1, 16384, &command->second) || !no_more_words(cursor)) {
			set_error(error, error_size, "usage: OUTPUT width height");
			return false;
		}
		command->type = WTWM_TEST_COMMAND_OUTPUT;
		return true;
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
