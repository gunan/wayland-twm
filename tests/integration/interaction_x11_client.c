/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

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
	xcb_window_t primary;
	xcb_window_t secondary;
};

static xcb_atom_t intern_atom(xcb_connection_t *connection, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(connection, false,
		(uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(connection, cookie, NULL);
	if (reply == NULL) return XCB_ATOM_NONE;
	xcb_atom_t atom = reply->atom;
	free(reply);
	return atom;
}

static void set_string(struct client *client, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		property, XCB_ATOM_STRING, 8, (uint32_t)strlen(value), value);
}

static void set_class(struct client *client, xcb_window_t window,
		const char *instance, const char *class_name) {
	char value[128];
	size_t first = strlen(instance) + 1;
	size_t second = strlen(class_name) + 1;
	if (first + second > sizeof(value)) abort();
	memcpy(value, instance, first);
	memcpy(value + first, class_name, second);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8, (uint32_t)(first + second), value);
}

static void set_size_hints(struct client *client, xcb_window_t window) {
	enum {
		US_POSITION = 1 << 0,
		P_MIN_SIZE = 1 << 4,
		P_MAX_SIZE = 1 << 5,
		P_RESIZE_INC = 1 << 6,
		P_ASPECT = 1 << 7,
		P_BASE_SIZE = 1 << 8,
		P_WIN_GRAVITY = 1 << 9,
	};
	uint32_t hints[18] = {0};
	hints[0] = US_POSITION | P_MIN_SIZE | P_MAX_SIZE | P_RESIZE_INC | P_ASPECT |
		P_BASE_SIZE | P_WIN_GRAVITY;
	hints[1] = 100;
	hints[2] = 100;
	hints[5] = 80;
	hints[6] = 60;
	hints[7] = 360;
	hints[8] = 260;
	hints[9] = 20;
	hints[10] = 10;
	hints[11] = 4;
	hints[12] = 3;
	hints[13] = 16;
	hints[14] = 9;
	hints[15] = 40;
	hints[16] = 30;
	hints[17] = XCB_GRAVITY_NORTH_WEST;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		client->wm_normal_hints, client->wm_size_hints, 32, 18, hints);
}

static void set_position_hints(struct client *client, xcb_window_t window,
		int x, int y) {
	enum { US_POSITION = 1 << 0 };
	uint32_t hints[18] = {0};
	hints[0] = US_POSITION;
	hints[1] = (uint32_t)x;
	hints[2] = (uint32_t)y;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		client->wm_normal_hints, client->wm_size_hints, 32, 18, hints);
}

static xcb_window_t create_window(struct client *client, int16_t x, int16_t y,
		uint16_t width, uint16_t height, const char *title,
		const char *instance) {
	xcb_window_t window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		client->screen->black_pixel,
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_EXPOSURE,
	};
	xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, window,
		client->screen->root, x, y, width, height, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
	set_string(client, window, XCB_ATOM_WM_NAME, title);
	set_class(client, window, instance, "WtwmInteraction");
	return window;
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t iterator = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&iterator);
	client->screen = iterator.data;
	client->wm_normal_hints = intern_atom(client->connection, "WM_NORMAL_HINTS");
	client->wm_size_hints = intern_atom(client->connection, "WM_SIZE_HINTS");
	client->secondary = create_window(client, 330, 180, 170, 110,
		"interaction-secondary", "interaction-secondary");
	client->primary = create_window(client, 100, 100, 180, 120,
		"interaction-primary", "interaction-primary");
	set_position_hints(client, client->secondary, 330, 180);
	set_size_hints(client, client->primary);
	xcb_map_window(client->connection, client->secondary);
	xcb_map_window(client->connection, client->primary);
	xcb_flush(client->connection);
	return true;
}

static void repaint(struct client *client, xcb_window_t window) {
	xcb_clear_area(client->connection, false, window, 0, 0, 0, 0);
	xcb_flush(client->connection);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	if (!initialize(&client)) return 1;
	puts("READY");
	bool running = true;
	while (running) {
		struct pollfd descriptors[2] = {
			{.fd = STDIN_FILENO, .events = POLLIN},
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
		};
		if (poll(descriptors, 2, 100) < 0) return 1;
		if ((descriptors[0].revents & POLLIN) != 0) {
			char command[32];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (strcmp(command, "EXIT") == 0) running = false;
			else abort();
		}
		xcb_generic_event_t *event;
		while ((event = xcb_poll_for_event(client.connection)) != NULL) {
			if ((event->response_type & ~UINT8_C(0x80)) == XCB_EXPOSE) {
				xcb_expose_event_t *expose = (xcb_expose_event_t *)event;
				repaint(&client, expose->window);
			}
			free(event);
		}
	}
	xcb_disconnect(client.connection);
	return 0;
}
