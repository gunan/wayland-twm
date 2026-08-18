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

enum wtwm_handoff_result {
	WTWM_HANDOFF_UNSUPPORTED,
	WTWM_HANDOFF_RELOAD,
	WTWM_HANDOFF_RELOAD_CONFIG,
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

/*
 * A safe Wayland handoff is deliberately narrower than exec(3): only a direct
 * invocation of the running compositor, optionally with one -f configuration,
 * can be translated to an in-process reload without disconnecting clients.
 * config_path borrows storage from plan until the plan is destroyed.
 */
enum wtwm_handoff_result wtwm_command_handoff(
	const struct wtwm_command_plan *plan, const char *running_program,
	const char **config_path);

#endif
