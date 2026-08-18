/* SPDX-License-Identifier: MIT */
#ifndef WTWM_TEST_CONTROL_H
#define WTWM_TEST_CONTROL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_TEST_CONTROL_TEXT_MAX 512

enum wtwm_test_output_operation {
	WTWM_TEST_OUTPUT_ADD,
	WTWM_TEST_OUTPUT_DESTROY,
	WTWM_TEST_OUTPUT_ENABLE,
	WTWM_TEST_OUTPUT_DISABLE,
	WTWM_TEST_OUTPUT_MODE,
	WTWM_TEST_OUTPUT_SCALE,
	WTWM_TEST_OUTPUT_TRANSFORM,
	WTWM_TEST_OUTPUT_POSITION,
};

enum wtwm_test_output_transform {
	WTWM_TEST_TRANSFORM_NORMAL,
	WTWM_TEST_TRANSFORM_90,
	WTWM_TEST_TRANSFORM_180,
	WTWM_TEST_TRANSFORM_270,
	WTWM_TEST_TRANSFORM_FLIPPED,
	WTWM_TEST_TRANSFORM_FLIPPED_90,
	WTWM_TEST_TRANSFORM_FLIPPED_180,
	WTWM_TEST_TRANSFORM_FLIPPED_270,
};

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
	enum wtwm_test_output_operation output_operation;
	enum wtwm_test_output_transform output_transform;
	int first;
	int second;
	int third;
	double x;
	double y;
	uint32_t code;
	bool pressed;
	bool output_auto;
	char output_name[WTWM_TEST_CONTROL_TEXT_MAX];
	char text[WTWM_TEST_CONTROL_TEXT_MAX];
};

bool wtwm_test_command_parse(const char *line, struct wtwm_test_command *command,
	char *error, size_t error_size);

#endif
