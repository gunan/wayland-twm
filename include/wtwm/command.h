/* SPDX-License-Identifier: MIT */
#ifndef WTWM_COMMAND_H
#define WTWM_COMMAND_H

#include <stddef.h>

enum wtwm_command_mode {
	WTWM_COMMAND_DIRECT,
	WTWM_COMMAND_SHELL,
};

enum wtwm_command_result {
	WTWM_COMMAND_OK,
	WTWM_COMMAND_INVALID_ARGUMENT,
	WTWM_COMMAND_EMPTY,
	WTWM_COMMAND_UNTERMINATED_SINGLE_QUOTE,
	WTWM_COMMAND_UNTERMINATED_DOUBLE_QUOTE,
	WTWM_COMMAND_TRAILING_BACKSLASH,
	WTWM_COMMAND_NO_MEMORY,
};

/*
 * A command plan owns command and argv.  A shell plan has an empty argv and
 * command must be passed unchanged to `/bin/sh -c`.  A direct plan has a
 * NULL-terminated argv suitable for execvp(3).  In both modes command is an
 * exact copy of the input, including its whitespace and quoting.
 */
struct wtwm_command_plan {
	enum wtwm_command_mode mode;
	char *command;
	char **argv;
	size_t argc;
};

enum wtwm_command_result wtwm_command_plan_create(
	const char *command, struct wtwm_command_plan *plan);
void wtwm_command_plan_destroy(struct wtwm_command_plan *plan);
const char *wtwm_command_result_message(enum wtwm_command_result result);

#endif
