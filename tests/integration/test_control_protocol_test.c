/* SPDX-License-Identifier: MIT */
#include "test_control.h"

#include <assert.h>
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

int main(void) {
	struct wtwm_test_command command = parse("OUTPUT 1280 720\n");
	assert(command.type == WTWM_TEST_COMMAND_OUTPUT);
	assert(command.first == 1280 && command.second == 720);

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
	assert(parse("QUIT").type == WTWM_TEST_COMMAND_QUIT);

	reject("");
	reject("OUTPUT 0 10");
	reject("OUTPUT 10");
	reject("BUTTON 1 down");
	reject("POINTER nan 1");
	reject("WAIT 0");
	reject("WAIT 121");
	reject("SET FONT");
	reject("PING now");
	reject("UNKNOWN");
	return 0;
}
