/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
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
	xcb_window_t window;
	bool desired_mapped;
	bool paint_white;
};

static void set_string(xcb_connection_t *connection, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	xcb_change_property(connection, XCB_PROP_MODE_REPLACE, window, property,
		XCB_ATOM_STRING, 8, (uint32_t)strlen(value), value);
}

static bool synchronize(struct client *client) {
	xcb_get_geometry_cookie_t cookie = xcb_get_geometry(client->connection, client->window);
	xcb_get_geometry_reply_t *reply =
		xcb_get_geometry_reply(client->connection, cookie, NULL);
	if (reply == NULL) return false;
	free(reply);
	return xcb_connection_has_error(client->connection) == 0;
}

static bool repaint(struct client *client) {
	if (!client->desired_mapped) return false;
	uint32_t pixel = client->paint_white ?
		client->screen->white_pixel : client->screen->black_pixel;
	client->paint_white = !client->paint_white;
	xcb_change_window_attributes(client->connection, client->window,
		XCB_CW_BACK_PIXEL, &pixel);
	xcb_clear_area(client->connection, false, client->window, 0, 0, 0, 0);
	return true;
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	client->window = xcb_generate_id(client->connection);
	uint32_t mask = XCB_CW_BACK_PIXEL | XCB_CW_OVERRIDE_REDIRECT |
		XCB_CW_EVENT_MASK;
	uint32_t values[] = {
		client->screen->white_pixel,
		1,
		XCB_EVENT_MASK_STRUCTURE_NOTIFY,
	};
	xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, client->window,
		client->screen->root, 140, 150, 220, 160, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		mask, values);
	set_string(client->connection, client->window, XCB_ATOM_WM_NAME,
		"overlay-override-redirect");
	xcb_flush(client->connection);
	return synchronize(client);
}

static bool map_window(struct client *client) {
	client->desired_mapped = true;
	xcb_map_window(client->connection, client->window);
	repaint(client);
	xcb_flush(client->connection);
	return synchronize(client);
}

static bool unmap_window(struct client *client) {
	client->desired_mapped = false;
	xcb_unmap_window(client->connection, client->window);
	xcb_flush(client->connection);
	return synchronize(client);
}

static bool handle_command(struct client *client, const char *command, bool *done) {
	if (strcmp(command, "MAP") == 0) {
		if (!map_window(client)) return false;
		puts("MAPPED");
		return true;
	}
	if (strcmp(command, "UNMAP") == 0) {
		if (!unmap_window(client)) return false;
		puts("UNMAPPED");
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		*done = true;
		puts("EXITING");
		return true;
	}
	fprintf(stderr, "unknown overlay X11 command: %s\n", command);
	return false;
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	if (!initialize(&client)) {
		fprintf(stderr, "overlay X11 client: initialization failed\n");
		return 1;
	}
	printf("READY %" PRIu32 "\n", client.window);
	bool done = false;
	char command[128];
	while (!done) {
		struct pollfd descriptors[] = {
			{.fd = STDIN_FILENO, .events = POLLIN},
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
		};
		if (poll(descriptors, 2, 20) < 0) {
			if (errno == EINTR) continue;
			break;
		}
		xcb_generic_event_t *event;
		while ((event = xcb_poll_for_event(client.connection)) != NULL) {
			if ((event->response_type & ~UINT8_C(0x80)) == XCB_MAP_NOTIFY)
				repaint(&client);
			free(event);
		}
		if ((descriptors[0].revents & (POLLIN | POLLHUP)) != 0) {
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (!handle_command(&client, command, &done)) break;
		}
		if (repaint(&client)) xcb_flush(client.connection);
	}
	if (client.desired_mapped) xcb_unmap_window(client.connection, client.window);
	xcb_destroy_window(client.connection, client.window);
	xcb_flush(client.connection);
	xcb_disconnect(client.connection);
	return done ? 0 : 1;
}
