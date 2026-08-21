/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum {
	MAX_ARGUMENTS = 64,
	MAX_RECORD_BYTES = 32768,
};

static int (*next_system)(const char *command);
static int (*next_execv)(const char *path, char *const argv[]);
static int (*next_execvp)(const char *file, char *const argv[]);
static char call_log[4096];

static void load_symbol(void *target, const char *name) {
	void *symbol = dlsym(RTLD_NEXT, name);
	memcpy(target, &symbol, sizeof(symbol));
}

static void initialize(void) __attribute__((constructor));

static void initialize(void) {
	load_symbol(&next_system, "system");
	load_symbol(&next_execv, "execv");
	load_symbol(&next_execvp, "execvp");
	const char *path = getenv("WTWM_COMMAND_CALL_LOG");
	if (path != NULL) (void)snprintf(call_log, sizeof(call_log), "%s", path);
}

static bool append_text(char *record, size_t *used, const char *text) {
	size_t length = strlen(text);
	if (length >= MAX_RECORD_BYTES - *used) return false;
	memcpy(record + *used, text, length);
	*used += length;
	record[*used] = '\0';
	return true;
}

static bool append_hex(char *record, size_t *used, const char *text) {
	static const char digits[] = "0123456789abcdef";
	if (text == NULL) return append_text(record, used, "-");
	for (const unsigned char *byte = (const unsigned char *)text;
			*byte != '\0'; ++byte) {
		if (*used > MAX_RECORD_BYTES - 3) return false;
		record[(*used)++] = digits[*byte >> 4];
		record[(*used)++] = digits[*byte & 15];
	}
	record[*used] = '\0';
	return true;
}

static void record_call(const char *operation, size_t argc,
		char *const argv[]) {
	if (call_log[0] == '\0') return;
	char record[MAX_RECORD_BYTES] = "";
	size_t used = 0;
	char header[128];
	(void)snprintf(header, sizeof(header), "%ld\t%s\t%zu",
		(long)getpid(), operation, argc);
	if (!append_text(record, &used, header)) return;
	for (size_t index = 0; index < argc; ++index) {
		if (!append_text(record, &used, "\t") ||
				!append_hex(record, &used, argv[index])) return;
	}
	if (!append_text(record, &used, "\n")) return;
	int descriptor = open(call_log, O_WRONLY | O_CREAT | O_APPEND, 0600);
	if (descriptor < 0) return;
	ssize_t written = write(descriptor, record, used);
	(void)written;
	(void)close(descriptor);
}

static size_t argument_count(char *const argv[]) {
	size_t count = 0;
	if (argv != NULL)
		while (count < MAX_ARGUMENTS && argv[count] != NULL) ++count;
	return count;
}

int system(const char *command) {
	char *arguments[] = {(char *)command, NULL};
	record_call("system", 1, arguments);
	if (next_system == NULL) {
		errno = ENOSYS;
		return -1;
	}
	return next_system(command);
}

int execvp(const char *file, char *const argv[]) {
	record_call("execvp", argument_count(argv), argv);
	if (next_execvp == NULL) {
		errno = ENOSYS;
		return -1;
	}
	return next_execvp(file, argv);
}

static int variadic_exec(const char *operation, const char *path,
		const char *first, va_list values, bool search_path) {
	char *arguments[MAX_ARGUMENTS + 1];
	size_t count = 0;
	const char *value = first;
	while (value != NULL && count < MAX_ARGUMENTS) {
		arguments[count++] = (char *)value;
		value = va_arg(values, const char *);
	}
	if (value != NULL) {
		errno = E2BIG;
		return -1;
	}
	arguments[count] = NULL;
	record_call(operation, count, arguments);
	if (search_path) {
		if (next_execvp != NULL) return next_execvp(path, arguments);
	} else if (next_execv != NULL) {
		return next_execv(path, arguments);
	}
	errno = ENOSYS;
	return -1;
}

int execl(const char *path, const char *arg, ...) {
	va_list values;
	va_start(values, arg);
	int result = variadic_exec("execl", path, arg, values, false);
	va_end(values);
	return result;
}

int execlp(const char *file, const char *arg, ...) {
	va_list values;
	va_start(values, arg);
	int result = variadic_exec("execlp", file, arg, values, true);
	va_end(values);
	return result;
}
