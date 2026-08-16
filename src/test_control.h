/* SPDX-License-Identifier: MIT */
#ifndef WTWM_TEST_CONTROL_H
#define WTWM_TEST_CONTROL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_TEST_CONTROL_TEXT_MAX 512

enum wtwm_test_command_type {
	WTWM_TEST_COMMAND_PING,
	WTWM_TEST_COMMAND_OUTPUT,
	WTWM_TEST_COMMAND_POINTER,
	WTWM_TEST_COMMAND_BUTTON,
	WTWM_TEST_COMMAND_KEY,
	WTWM_TEST_COMMAND_STATE,
	WTWM_TEST_COMMAND_TRACE,
	WTWM_TEST_COMMAND_WAIT,
	WTWM_TEST_COMMAND_CAPTURE,
	WTWM_TEST_COMMAND_SET_ANIMATION_MS,
	WTWM_TEST_COMMAND_SET_PLACEMENT_SEED,
	WTWM_TEST_COMMAND_SET_CURSOR,
	WTWM_TEST_COMMAND_SET_FONT,
	WTWM_TEST_COMMAND_QUIT,
};

struct wtwm_test_command {
	enum wtwm_test_command_type type;
	int first;
	int second;
	double x;
	double y;
	uint32_t code;
	bool pressed;
	char text[WTWM_TEST_CONTROL_TEXT_MAX];
};

bool wtwm_test_command_parse(const char *line, struct wtwm_test_command *command,
	char *error, size_t error_size);

#endif
