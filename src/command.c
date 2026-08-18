/* SPDX-License-Identifier: MIT */
#include <wtwm/command.h>

#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

enum quote_state {
	QUOTE_NONE,
	QUOTE_SINGLE,
	QUOTE_DOUBLE,
};

struct argument_builder {
	char **argv;
	size_t argc;
	size_t argv_capacity;
	char *word;
	size_t word_length;
	size_t word_capacity;
	bool word_started;
	bool requires_shell;
};

static char *copy_string(const char *source) {
	size_t length = strlen(source) + 1;
	char *copy = malloc(length);
	if (copy != NULL) memcpy(copy, source, length);
	return copy;
}

static void free_arguments(char **argv, size_t argc) {
	if (argv == NULL) return;
	for (size_t index = 0; index < argc; ++index) free(argv[index]);
	free(argv);
}

static bool grow_buffer(char **buffer, size_t *capacity, size_t required) {
	if (required <= *capacity) return true;

	size_t next = *capacity == 0 ? 16 : *capacity;
	while (next < required) {
		if (next > ((size_t)-1) / 2) {
			next = required;
			break;
		}
		next *= 2;
	}

	char *grown = realloc(*buffer, next);
	if (grown == NULL) return false;
	*buffer = grown;
	*capacity = next;
	return true;
}

static bool append_byte(struct argument_builder *builder, char byte) {
	if (!grow_buffer(&builder->word, &builder->word_capacity,
			builder->word_length + 1)) return false;
	builder->word[builder->word_length++] = byte;
	builder->word_started = true;
	return true;
}

static bool append_argument(struct argument_builder *builder) {
	if (!builder->word_started) return true;

	char *argument = malloc(builder->word_length + 1);
	if (argument == NULL) return false;
	if (builder->word_length != 0)
		memcpy(argument, builder->word, builder->word_length);
	argument[builder->word_length] = '\0';

	if (builder->argc + 2 > builder->argv_capacity) {
		size_t next = builder->argv_capacity == 0 ? 8 : builder->argv_capacity * 2;
		char **grown = realloc(builder->argv, next * sizeof(*grown));
		if (grown == NULL) {
			free(argument);
			return false;
		}
		builder->argv = grown;
		builder->argv_capacity = next;
	}

	builder->argv[builder->argc++] = argument;
	builder->argv[builder->argc] = NULL;
	builder->word_length = 0;
	builder->word_started = false;
	return true;
}

static bool is_shell_operator(char byte) {
	return byte == '|' || byte == '&' || byte == ';' || byte == '<' ||
		byte == '>' || byte == '(' || byte == ')';
}

static bool is_shell_expansion(char byte) {
	return byte == '$' || byte == '`' || byte == '*' || byte == '?' ||
		byte == '[';
}

static bool is_assignment(const char *word) {
	const unsigned char *cursor = (const unsigned char *)word;
	if (!(cursor[0] == '_' || (cursor[0] >= 'A' && cursor[0] <= 'Z') ||
			(cursor[0] >= 'a' && cursor[0] <= 'z'))) return false;

	for (++cursor; *cursor != '\0' && *cursor != '='; ++cursor) {
		if (!(*cursor == '_' || (*cursor >= 'A' && *cursor <= 'Z') ||
				(*cursor >= 'a' && *cursor <= 'z') ||
				(*cursor >= '0' && *cursor <= '9'))) return false;
	}
	return *cursor == '=';
}

static bool is_shell_command_word(const char *word) {
	/*
	 * Directly executing a shell built-in or reserved word changes its meaning.
	 * This includes the POSIX utilities normally built into sh and common /bin/sh
	 * built-ins whose external counterparts can behave differently.
	 */
	static const char *const words[] = {
		"!", ".", ":", "[", "alias", "bg", "break", "case", "cd",
		"command", "continue", "do", "done", "echo", "elif", "else",
		"esac", "eval", "exec", "exit", "export", "false", "fc", "fg",
		"fi", "for", "getopts", "hash", "if", "in", "jobs", "kill",
		"local", "newgrp", "printf", "pwd", "read", "readonly", "return",
		"set", "shift", "test", "then", "time", "times", "trap", "true", "type",
		"ulimit", "umask", "unalias", "unset", "until", "wait", "while",
		"{", "}",
	};

	for (size_t index = 0; index < sizeof(words) / sizeof(words[0]); ++index) {
		if (strcmp(word, words[index]) == 0) return true;
	}
	return false;
}

static enum wtwm_command_result parse_arguments(
		const char *command, struct argument_builder *builder) {
	enum quote_state quote = QUOTE_NONE;

	for (size_t index = 0; command[index] != '\0'; ++index) {
		char byte = command[index];

		if (quote == QUOTE_SINGLE) {
			if (byte == '\'') {
				quote = QUOTE_NONE;
			} else if (!append_byte(builder, byte)) {
				return WTWM_COMMAND_NO_MEMORY;
			}
			continue;
		}

		if (quote == QUOTE_DOUBLE) {
			if (byte == '"') {
				quote = QUOTE_NONE;
				continue;
			}
			if (byte == '$' || byte == '`') builder->requires_shell = true;
			if (byte != '\\') {
				if (!append_byte(builder, byte)) return WTWM_COMMAND_NO_MEMORY;
				continue;
			}

			char next = command[index + 1];
			if (next == '\0') return WTWM_COMMAND_TRAILING_BACKSLASH;
			++index;
			if (next == '\n') continue;
			if (next == '$' || next == '`' || next == '"' || next == '\\') {
				if (!append_byte(builder, next)) return WTWM_COMMAND_NO_MEMORY;
			} else {
				if (!append_byte(builder, '\\') || !append_byte(builder, next))
					return WTWM_COMMAND_NO_MEMORY;
			}
			continue;
		}

		if (byte == ' ' || byte == '\t') {
			if (!append_argument(builder)) return WTWM_COMMAND_NO_MEMORY;
			continue;
		}
		if (byte == '\'') {
			quote = QUOTE_SINGLE;
			builder->word_started = true;
			continue;
		}
		if (byte == '"') {
			quote = QUOTE_DOUBLE;
			builder->word_started = true;
			continue;
		}
		if (byte == '\\') {
			char next = command[index + 1];
			if (next == '\0') return WTWM_COMMAND_TRAILING_BACKSLASH;
			++index;
			if (next != '\n' && !append_byte(builder, next))
				return WTWM_COMMAND_NO_MEMORY;
			continue;
		}
		if (byte == '\n' || is_shell_operator(byte) ||
				is_shell_expansion(byte) ||
				(byte == '~' && !builder->word_started) ||
				(byte == '#' && !builder->word_started))
			builder->requires_shell = true;
		if (!append_byte(builder, byte)) return WTWM_COMMAND_NO_MEMORY;
	}

	if (quote == QUOTE_SINGLE) return WTWM_COMMAND_UNTERMINATED_SINGLE_QUOTE;
	if (quote == QUOTE_DOUBLE) return WTWM_COMMAND_UNTERMINATED_DOUBLE_QUOTE;
	if (!append_argument(builder)) return WTWM_COMMAND_NO_MEMORY;
	return builder->argc == 0 ? WTWM_COMMAND_EMPTY : WTWM_COMMAND_OK;
}

enum wtwm_command_result wtwm_command_plan_create(
		const char *command, struct wtwm_command_plan *plan) {
	if (command == NULL || plan == NULL) return WTWM_COMMAND_INVALID_ARGUMENT;
	memset(plan, 0, sizeof(*plan));

	struct argument_builder builder = {0};
	enum wtwm_command_result result = parse_arguments(command, &builder);
	free(builder.word);
	if (result != WTWM_COMMAND_OK) {
		free_arguments(builder.argv, builder.argc);
		return result;
	}

	plan->command = copy_string(command);
	if (plan->command == NULL) {
		free_arguments(builder.argv, builder.argc);
		return WTWM_COMMAND_NO_MEMORY;
	}

	if (builder.requires_shell || is_assignment(builder.argv[0]) ||
			is_shell_command_word(builder.argv[0])) {
		plan->mode = WTWM_COMMAND_SHELL;
		free_arguments(builder.argv, builder.argc);
		return WTWM_COMMAND_OK;
	}

	plan->mode = WTWM_COMMAND_DIRECT;
	plan->argv = builder.argv;
	plan->argc = builder.argc;
	return WTWM_COMMAND_OK;
}

void wtwm_command_plan_destroy(struct wtwm_command_plan *plan) {
	if (plan == NULL) return;
	free(plan->command);
	free_arguments(plan->argv, plan->argc);
	memset(plan, 0, sizeof(*plan));
}

const char *wtwm_command_result_message(enum wtwm_command_result result) {
	switch (result) {
	case WTWM_COMMAND_OK: return "success";
	case WTWM_COMMAND_INVALID_ARGUMENT: return "invalid argument";
	case WTWM_COMMAND_EMPTY: return "command is empty";
	case WTWM_COMMAND_UNTERMINATED_SINGLE_QUOTE:
		return "unterminated single quote";
	case WTWM_COMMAND_UNTERMINATED_DOUBLE_QUOTE:
		return "unterminated double quote";
	case WTWM_COMMAND_TRAILING_BACKSLASH: return "trailing backslash";
	case WTWM_COMMAND_NO_MEMORY: return "out of memory";
	}
	return "unknown command result";
}

static const char *program_basename(const char *path) {
	if (path == NULL) return NULL;
	const char *slash = strrchr(path, '/');
	return slash != NULL ? slash + 1 : path;
}

enum wtwm_handoff_result wtwm_command_handoff(
		const struct wtwm_command_plan *plan, const char *running_program,
		const char **config_path) {
	if (config_path != NULL) *config_path = NULL;
	if (plan == NULL || running_program == NULL || config_path == NULL ||
			plan->mode != WTWM_COMMAND_DIRECT || plan->argv == NULL ||
			plan->argc == 0) return WTWM_HANDOFF_UNSUPPORTED;
	const char *requested = program_basename(plan->argv[0]);
	const char *running = program_basename(running_program);
	if (requested == NULL || running == NULL || requested[0] == '\0' ||
			strcmp(requested, running) != 0)
		return WTWM_HANDOFF_UNSUPPORTED;
	if (plan->argc == 1) return WTWM_HANDOFF_RELOAD;
	if (plan->argc == 3 && strcmp(plan->argv[1], "-f") == 0 &&
			plan->argv[2][0] != '\0') {
		*config_path = plan->argv[2];
		return WTWM_HANDOFF_RELOAD_CONFIG;
	}
	if (plan->argc == 2 && strncmp(plan->argv[1], "-f", 2) == 0 &&
			plan->argv[1][2] != '\0') {
		*config_path = plan->argv[1] + 2;
		return WTWM_HANDOFF_RELOAD_CONFIG;
	}
	return WTWM_HANDOFF_UNSUPPORTED;
}
