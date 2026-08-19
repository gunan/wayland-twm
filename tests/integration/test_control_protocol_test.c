/* SPDX-License-Identifier: MIT */
#include "test_control.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct wtwm_test_command parse(const char *line) {
	struct wtwm_test_command command;
	char error[256];
	assert(wtwm_test_command_parse(line, &command, error, sizeof(error)));
	return command;
}

static void reject(const char *line) {
	struct wtwm_test_command command;
	char error[256];
	assert(!wtwm_test_command_parse(line, &command, error, sizeof(error)));
	assert(error[0] != '\0');
}

static void reject_with(const char *line, const char *expected) {
	struct wtwm_test_command command;
	char error[256];
	assert(!wtwm_test_command_parse(line, &command, error, sizeof(error)));
	assert(strcmp(error, expected) == 0);
}

int main(void) {
	struct wtwm_test_command command = parse("OUTPUT 1280 720\n");
	assert(command.type == WTWM_TEST_COMMAND_OUTPUT);
	assert(command.output_operation == WTWM_TEST_OUTPUT_ADD);
	assert(command.first == 1280 && command.second == 720);

	command = parse("OUTPUT DESTROY HEADLESS-2");
	assert(command.output_operation == WTWM_TEST_OUTPUT_DESTROY);
	assert(strcmp(command.output_name, "HEADLESS-2") == 0);
	command = parse("OUTPUT ENABLE HEADLESS-2");
	assert(command.output_operation == WTWM_TEST_OUTPUT_ENABLE);
	command = parse("OUTPUT DISABLE HEADLESS-2");
	assert(command.output_operation == WTWM_TEST_OUTPUT_DISABLE);

	command = parse("OUTPUT MODE HEADLESS-2 2560 1440 59940");
	assert(command.output_operation == WTWM_TEST_OUTPUT_MODE);
	assert(strcmp(command.output_name, "HEADLESS-2") == 0);
	assert(command.first == 2560 && command.second == 1440);
	assert(command.third == 59940);
	command = parse("OUTPUT MODE HEADLESS-2 1 16384 0");
	assert(command.first == 1 && command.second == 16384 && command.third == 0);

	command = parse("OUTPUT SCALE HEADLESS-2 1.25");
	assert(command.output_operation == WTWM_TEST_OUTPUT_SCALE);
	assert(command.x == 1.25);
	command = parse("OUTPUT SCALE HEADLESS-2 16");
	assert(command.x == 16.0);

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
	for (size_t i = 0; i < sizeof(transforms) / sizeof(transforms[0]); ++i) {
		char line[128];
		snprintf(line, sizeof(line), "OUTPUT TRANSFORM HEADLESS-2 %s",
			transforms[i].name);
		command = parse(line);
		assert(command.output_operation == WTWM_TEST_OUTPUT_TRANSFORM);
		assert(command.output_transform == transforms[i].transform);
	}

	command = parse("OUTPUT POSITION HEADLESS-2 AUTO");
	assert(command.output_operation == WTWM_TEST_OUTPUT_POSITION);
	assert(command.output_auto);
	command = parse("OUTPUT POSITION HEADLESS-2 -1000000 1000000");
	assert(command.output_operation == WTWM_TEST_OUTPUT_POSITION);
	assert(!command.output_auto);
	assert(command.first == -1000000 && command.second == 1000000);

	command = parse("INPUT CLEAR");
	assert(command.type == WTWM_TEST_COMMAND_INPUT);
	assert(command.input_operation == WTWM_TEST_INPUT_CLEAR);
	command = parse("INPUT ADD KEYBOARD alpha-keyboard");
	assert(command.type == WTWM_TEST_COMMAND_INPUT);
	assert(command.input_operation == WTWM_TEST_INPUT_ADD);
	assert(command.input_device_type == WTWM_TEST_INPUT_DEVICE_KEYBOARD);
	assert(strcmp(command.input_name, "alpha-keyboard") == 0);
	command = parse("INPUT ADD POINTER alpha-pointer");
	assert(command.input_device_type == WTWM_TEST_INPUT_DEVICE_POINTER);
	assert(strcmp(command.input_name, "alpha-pointer") == 0);
	command = parse("INPUT REMOVE alpha-keyboard");
	assert(command.input_operation == WTWM_TEST_INPUT_REMOVE);
	command = parse("INPUT KEY alpha-keyboard 56 press");
	assert(command.input_operation == WTWM_TEST_INPUT_KEY);
	assert(command.code == 56 && command.pressed);
	command = parse("INPUT KEY alpha-keyboard 56 release");
	assert(!command.pressed);
	command = parse("INPUT POINTER alpha-pointer -12.5 900");
	assert(command.input_operation == WTWM_TEST_INPUT_POINTER);
	assert(command.x == -12.5 && command.y == 900.0);
	command = parse("INPUT BUTTON alpha-pointer 272 press");
	assert(command.input_operation == WTWM_TEST_INPUT_BUTTON);
	assert(command.code == 272 && command.pressed);

	command = parse("POINTER 123.5 67");
	assert(command.type == WTWM_TEST_COMMAND_POINTER);
	assert(command.x == 123.5 && command.y == 67.0);

	command = parse("BUTTON 272 press");
	assert(command.type == WTWM_TEST_COMMAND_BUTTON);
	assert(command.code == 272 && command.pressed);
	command = parse("KEY 1 release");
	assert(command.type == WTWM_TEST_COMMAND_KEY && !command.pressed);

	command = parse("WAIT");
	assert(command.type == WTWM_TEST_COMMAND_WAIT && command.first == 1);
	command = parse("WAIT 3");
	assert(command.first == 3);

	command = parse("CAPTURE /tmp/a capture.ppm");
	assert(strcmp(command.text, "/tmp/a capture.ppm") == 0);
	command = parse("SET ANIMATION_MS 0");
	assert(command.type == WTWM_TEST_COMMAND_SET_ANIMATION_MS && command.first == 0);
	command = parse("SET PLACEMENT_SEED 42");
	assert(command.type == WTWM_TEST_COMMAND_SET_PLACEMENT_SEED && command.first == 42);
	command = parse("SET CURSOR 10 20");
	assert(command.type == WTWM_TEST_COMMAND_SET_CURSOR && command.x == 10.0);
	command = parse("SET FONT DejaVu Sans Mono 10");
	assert(command.type == WTWM_TEST_COMMAND_SET_FONT);
	assert(strcmp(command.text, "DejaVu Sans Mono 10") == 0);

	assert(parse("PING").type == WTWM_TEST_COMMAND_PING);
	assert(parse("STATE").type == WTWM_TEST_COMMAND_STATE);
	command = parse("TRACE");
	assert(command.type == WTWM_TEST_COMMAND_TRACE && command.first == 0);
	command = parse("TRACE CLEAR");
	assert(command.type == WTWM_TEST_COMMAND_TRACE && command.first == 1);
	assert(parse("QUIT").type == WTWM_TEST_COMMAND_QUIT);

	reject("");
	reject("OUTPUT 0 10");
	reject("OUTPUT 10");
	reject("OUTPUT 10 20 extra");
	reject_with("OUTPUT DESTROY",
		"OUTPUT DESTROY requires an output name");
	reject_with("OUTPUT DESTROY HEADLESS-1 extra",
		"usage: OUTPUT DESTROY name");
	reject("OUTPUT ENABLE");
	reject("OUTPUT DISABLE HEADLESS-1 extra");
	reject_with("OUTPUT MODE HEADLESS-1 0 720 60000",
		"usage: OUTPUT MODE name width height refresh_mhz");
	reject("OUTPUT MODE HEADLESS-1 1280 16385 60000");
	reject("OUTPUT MODE HEADLESS-1 1280 720 1000001");
	reject("OUTPUT MODE HEADLESS-1 1280 720 60000 extra");
	reject_with("OUTPUT SCALE HEADLESS-1 0.249",
		"usage: OUTPUT SCALE name scale");
	reject("OUTPUT SCALE HEADLESS-1 16.001");
	reject("OUTPUT SCALE HEADLESS-1 nan");
	reject("OUTPUT SCALE HEADLESS-1 1.25 extra");
	reject_with("OUTPUT TRANSFORM HEADLESS-1 Normal",
		"usage: OUTPUT TRANSFORM name normal|90|180|270|"
		"flipped|flipped-90|flipped-180|flipped-270");
	reject("OUTPUT TRANSFORM HEADLESS-1 flipped-360");
	reject("OUTPUT POSITION HEADLESS-1 AUTO extra");
	reject_with("OUTPUT POSITION HEADLESS-1 10",
		"usage: OUTPUT POSITION name AUTO|x y");
	reject("OUTPUT POSITION HEADLESS-1 -1000001 0");
	reject("OUTPUT POSITION HEADLESS-1 0 1000001");
	reject_with("OUTPUT FROB HEADLESS-1",
		"unknown OUTPUT operation: FROB");
	reject_with("INPUT", "usage: INPUT operation ...");
	reject_with("INPUT CLEAR now", "INPUT CLEAR takes no arguments");
	reject_with("INPUT ADD keyboard device",
		"usage: INPUT ADD KEYBOARD|POINTER name");
	reject("INPUT ADD KEYBOARD");
	reject("INPUT ADD POINTER pointer extra");
	reject_with("INPUT REMOVE", "INPUT REMOVE requires a device name");
	reject_with("INPUT REMOVE pointer extra", "usage: INPUT REMOVE name");
	reject_with("INPUT KEY keyboard 1 down",
		"usage: INPUT KEY name code press|release");
	reject("INPUT KEY keyboard -1 press");
	reject("INPUT KEY keyboard 1 press extra");
	reject_with("INPUT POINTER pointer nan 0",
		"usage: INPUT POINTER name x y");
	reject("INPUT POINTER pointer 0");
	reject("INPUT BUTTON pointer 272 release extra");
	reject_with("INPUT FROB device", "unknown INPUT operation: FROB");
	reject("BUTTON 1 down");
	reject("POINTER nan 1");
	reject("WAIT 0");
	reject("WAIT 121");
	reject("SET FONT");
	reject("PING now");
	reject("TRACE RESET");
	reject("TRACE CLEAR now");
	reject("UNKNOWN");
	return 0;
}
