/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xcb/xcb.h>

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_atom_t wm_normal_hints;
	xcb_atom_t wm_size_hints;
	xcb_atom_t wm_transient_for;
	xcb_window_t owner;
	xcb_window_t window;
	bool white;
};

static _Noreturn void fail(const char *message) {
	fprintf(stderr, "Xwayland geometry matrix client: %s\n", message);
	exit(EXIT_FAILURE);
}

static int parse_nonnegative(const char *text, const char *label, int maximum) {
	char *end = NULL;
	errno = 0;
	long value = strtol(text, &end, 10);
	if (errno != 0 || end == text || *end != '\0' || value < 0 || value > maximum) {
		fprintf(stderr, "Xwayland geometry matrix client: invalid %s: %s\n",
			label, text);
		exit(EXIT_FAILURE);
	}
	return (int)value;
}

static xcb_atom_t intern_atom(xcb_connection_t *connection, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(
		connection, false, (uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(connection, cookie, NULL);
	if (reply == NULL) fail("could not intern an ICCCM atom");
	xcb_atom_t atom = reply->atom;
	free(reply);
	return atom;
}

static void set_string(xcb_connection_t *connection, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	xcb_change_property(connection, XCB_PROP_MODE_REPLACE, window, property,
		XCB_ATOM_STRING, 8, (uint32_t)strlen(value), value);
}

static void set_class(xcb_connection_t *connection, xcb_window_t window,
		const char *instance) {
	static const char class_name[] = "WtwmGeometryMatrix";
	size_t instance_length = strlen(instance) + 1;
	size_t class_length = sizeof(class_name);
	char *value = malloc(instance_length + class_length);
	if (value == NULL) fail("out of memory");
	memcpy(value, instance, instance_length);
	memcpy(value + instance_length, class_name, class_length);
	xcb_change_property(connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8,
		(uint32_t)(instance_length + class_length), value);
	free(value);
}

static xcb_window_t create_window(struct client *client, int x, int y,
		int width, int height, int border_width) {
	xcb_window_t window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		client->screen->white_pixel,
		XCB_EVENT_MASK_EXPOSURE | XCB_EVENT_MASK_STRUCTURE_NOTIFY,
	};
	xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, window,
		client->screen->root, (int16_t)x, (int16_t)y,
		(uint16_t)width, (uint16_t)height, (uint16_t)border_width,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
	return window;
}

static void set_normal_hints(struct client *client, xcb_window_t window,
		int x, int y, int width, int height, const char *profile) {
	enum {
		US_POSITION = 1 << 0,
		US_SIZE = 1 << 1,
		P_MIN_SIZE = 1 << 4,
		P_MAX_SIZE = 1 << 5,
		P_RESIZE_INC = 1 << 6,
		P_ASPECT = 1 << 7,
		P_BASE_SIZE = 1 << 8,
	};
	uint32_t hints[18] = {0};
	hints[0] = US_POSITION | US_SIZE;
	hints[1] = (uint32_t)x;
	hints[2] = (uint32_t)y;
	hints[3] = (uint32_t)width;
	hints[4] = (uint32_t)height;
	if (strcmp(profile, "position-size") == 0) {
		/* The positioning flags are the intentionally minimal profile. */
	} else if (strcmp(profile, "min-max") == 0) {
		hints[0] |= P_MIN_SIZE | P_MAX_SIZE;
		hints[5] = 80;
		hints[6] = 60;
		hints[7] = 240;
		hints[8] = 180;
	} else if (strcmp(profile, "base-increment") == 0) {
		hints[0] |= P_BASE_SIZE | P_RESIZE_INC;
		hints[9] = 10;
		hints[10] = 7;
		hints[15] = 17;
		hints[16] = 11;
	} else if (strcmp(profile, "complete") == 0) {
		hints[0] |= P_MIN_SIZE | P_MAX_SIZE | P_BASE_SIZE |
			P_RESIZE_INC | P_ASPECT;
		hints[5] = 73;
		hints[6] = 52;
		hints[7] = 263;
		hints[8] = 187;
		hints[9] = 8;
		hints[10] = 6;
		hints[11] = 4;
		hints[12] = 3;
		hints[13] = 16;
		hints[14] = 9;
		hints[15] = 13;
		hints[16] = 9;
	} else {
		fail("unknown WM_NORMAL_HINTS profile");
	}
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		client->wm_normal_hints, client->wm_size_hints, 32, 18, hints);
}

static void paint(struct client *client, xcb_window_t window) {
	uint32_t pixel = client->white ? client->screen->white_pixel :
		client->screen->black_pixel;
	client->white = !client->white;
	xcb_change_window_attributes(client->connection, window, XCB_CW_BACK_PIXEL,
		&pixel);
	xcb_clear_area(client->connection, false, window, 0, 0, 0, 0);
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	client->wm_normal_hints = intern_atom(client->connection, "WM_NORMAL_HINTS");
	client->wm_size_hints = intern_atom(client->connection, "WM_SIZE_HINTS");
	client->wm_transient_for = intern_atom(client->connection, "WM_TRANSIENT_FOR");
	return client->screen != NULL;
}

static _Noreturn void usage(const char *program) {
	fprintf(stderr, "usage: %s CASE normal|transient BORDER WIDTH HEIGHT "
		"position-size|min-max|base-increment|complete\n", program);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv) {
	if (argc != 7) usage(argv[0]);
	const char *case_id = argv[1];
	bool transient;
	if (strcmp(argv[2], "normal") == 0) transient = false;
	else if (strcmp(argv[2], "transient") == 0) transient = true;
	else usage(argv[0]);
	int border = parse_nonnegative(argv[3], "border width", UINT16_MAX);
	int width = parse_nonnegative(argv[4], "width", UINT16_MAX);
	int height = parse_nonnegative(argv[5], "height", UINT16_MAX);
	if (width == 0 || height == 0) fail("window dimensions must be positive");

	struct client client = {0};
	if (!initialize(&client)) fail("could not connect to Xwayland");
	if (transient) {
		client.owner = create_window(&client, 36, 34, 180, 104, 0);
		set_string(client.connection, client.owner, XCB_ATOM_WM_NAME,
			"WTWM Geometry Matrix Owner");
		set_class(client.connection, client.owner, "geometry-matrix-owner");
		set_normal_hints(&client, client.owner, 36, 34, 180, 104,
			"position-size");
		xcb_map_window(client.connection, client.owner);
		paint(&client, client.owner);
	}
	client.window = create_window(&client, 160, 120, width, height, border);
	set_string(client.connection, client.window, XCB_ATOM_WM_NAME,
		"WTWM Geometry Matrix");
	set_class(client.connection, client.window, case_id);
	set_normal_hints(&client, client.window, 160, 120, width, height, argv[6]);
	if (transient) {
		xcb_change_property(client.connection, XCB_PROP_MODE_REPLACE, client.window,
			client.wm_transient_for, XCB_ATOM_WINDOW, 32, 1, &client.owner);
	}
	xcb_map_window(client.connection, client.window);
	paint(&client, client.window);
	xcb_flush(client.connection);
	printf("READY %u\n", client.window);
	fflush(stdout);

	struct pollfd input = {.fd = STDIN_FILENO, .events = POLLIN};
	for (;;) {
		int result = poll(&input, 1, 10);
		if (result < 0 && errno == EINTR) continue;
		if (result < 0 || (input.revents & (POLLHUP | POLLERR | POLLNVAL)) != 0)
			break;
		if ((input.revents & POLLIN) != 0) {
			char command[16];
			if (fgets(command, sizeof(command), stdin) == NULL ||
				strcmp(command, "QUIT\n") == 0) break;
		}
		paint(&client, client.window);
		if (client.owner != XCB_WINDOW_NONE) paint(&client, client.owner);
		xcb_flush(client.connection);
		if (xcb_connection_has_error(client.connection) != 0) break;
	}

	if (client.window != XCB_WINDOW_NONE)
		xcb_destroy_window(client.connection, client.window);
	if (client.owner != XCB_WINDOW_NONE)
		xcb_destroy_window(client.connection, client.owner);
	xcb_flush(client.connection);
	xcb_disconnect(client.connection);
	return EXIT_SUCCESS;
}
