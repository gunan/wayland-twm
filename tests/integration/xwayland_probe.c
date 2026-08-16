/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xcb/xcb.h>

static int expect_unavailable(const char *display) {
	if (setenv("DISPLAY", display, true) < 0) {
		fprintf(stderr, "setenv: %s\n", strerror(errno));
		return 2;
	}
	int screen = 0;
	xcb_connection_t *connection = xcb_connect(NULL, &screen);
	int error = xcb_connection_has_error(connection);
	xcb_disconnect(connection);
	if (error == 0) {
		fprintf(stderr, "unexpectedly connected to retired DISPLAY=%s\n", display);
		return 1;
	}
	return 0;
}

static bool record(const char *path, const char *event, const char *display,
		pid_t pid, int screen) {
	FILE *stream = fopen(path, "a");
	if (stream == NULL) return false;
	bool ok = fprintf(stream, "%s %s %ld %d\n", event, display, (long)pid, screen) > 0;
	if (fclose(stream) != 0) ok = false;
	return ok;
}

int main(int argc, char **argv) {
	if (argc == 3 && strcmp(argv[1], "--expect-unavailable") == 0)
		return expect_unavailable(argv[2]);
	if (argc == 3 && strcmp(argv[1], "--record-display") == 0) {
		const char *display = getenv("DISPLAY");
		if (display == NULL || display[0] == '\0') return 1;
		return record(argv[2], "INHERITED", display, getpid(), -1) ? 0 : 1;
	}
	if (argc != 2) {
		fprintf(stderr, "usage: %s MARKER | --expect-unavailable DISPLAY | "
			"--record-display MARKER\n", argv[0]);
		return 2;
	}

	const char *display = getenv("DISPLAY");
	if (display == NULL || display[0] == '\0') {
		fprintf(stderr, "startup probe did not inherit DISPLAY\n");
		return 1;
	}
	int screen = 0;
	xcb_connection_t *connection = xcb_connect(NULL, &screen);
	if (xcb_connection_has_error(connection) != 0) {
		fprintf(stderr, "failed to connect to inherited DISPLAY=%s\n", display);
		xcb_disconnect(connection);
		return 1;
	}

	xcb_get_input_focus_cookie_t cookie = xcb_get_input_focus(connection);
	xcb_generic_error_t *error = NULL;
	xcb_get_input_focus_reply_t *reply =
		xcb_get_input_focus_reply(connection, cookie, &error);
	if (reply == NULL || error != NULL) {
		fprintf(stderr, "X11 round trip failed on DISPLAY=%s\n", display);
		free(error);
		free(reply);
		xcb_disconnect(connection);
		return 1;
	}
	free(reply);

	if (!record(argv[1], "CONNECTED", display, getpid(), screen)) {
		fprintf(stderr, "failed to record Xwayland connection: %s\n", strerror(errno));
		xcb_disconnect(connection);
		return 1;
	}

	for (;;) {
		xcb_generic_event_t *event = xcb_wait_for_event(connection);
		if (event == NULL) break;
		free(event);
	}
	if (!record(argv[1], "DISCONNECTED", display, getpid(), screen)) {
		fprintf(stderr, "failed to record Xwayland shutdown: %s\n", strerror(errno));
		xcb_disconnect(connection);
		return 1;
	}
	xcb_disconnect(connection);
	return 0;
}
