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

enum { US_POSITION = 1u << 0, INPUT_HINT = 1u << 0 };

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_atom_t wm_hints;
	xcb_atom_t wm_normal_hints;
	xcb_atom_t wm_size_hints;
	xcb_atom_t wm_protocols;
	xcb_atom_t wm_take_focus;
	xcb_atom_t wm_transient_for;
	xcb_window_t first;
	xcb_window_t second;
	unsigned take_focus_first;
	unsigned take_focus_second;
};

static xcb_atom_t atom(struct client *client, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(client->connection, false,
		(uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply =
		xcb_intern_atom_reply(client->connection, cookie, NULL);
	if (reply == NULL) return XCB_ATOM_NONE;
	xcb_atom_t value = reply->atom;
	free(reply);
	return value;
}

static void set_string(struct client *client, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		property, XCB_ATOM_STRING, 8, (uint32_t)strlen(value), value);
}

static void set_class(struct client *client, xcb_window_t window,
		const char *instance) {
	static const char class_name[] = "WtwmFocusStack";
	char value[96];
	size_t first = strlen(instance) + 1;
	size_t second = sizeof(class_name);
	if (first + second > sizeof(value)) abort();
	memcpy(value, instance, first);
	memcpy(value + first, class_name, second);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8,
		(uint32_t)(first + second), value);
}

static xcb_window_t create_window(struct client *client, const char *title,
		int16_t x, int16_t y, bool input) {
	xcb_window_t window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		client->screen->white_pixel,
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_FOCUS_CHANGE,
	};
	xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, window,
		client->screen->root, x, y, 220, 150, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
	set_string(client, window, XCB_ATOM_WM_NAME, title);
	set_class(client, window, title);
	uint32_t normal[18] = {0};
	normal[0] = US_POSITION;
	normal[1] = (uint32_t)x;
	normal[2] = (uint32_t)y;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		client->wm_normal_hints, client->wm_size_hints, 32, 18, normal);
	uint32_t hints[9] = {0};
	hints[0] = INPUT_HINT;
	hints[1] = input ? 1u : 0u;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		client->wm_hints, client->wm_hints, 32, 9, hints);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		client->wm_protocols, XCB_ATOM_ATOM, 32, 1, &client->wm_take_focus);
	return window;
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t iterator = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int index = 0; index < screen_number; ++index) xcb_screen_next(&iterator);
	client->screen = iterator.data;
	if (client->screen == NULL) return false;
	client->wm_hints = atom(client, "WM_HINTS");
	client->wm_normal_hints = atom(client, "WM_NORMAL_HINTS");
	client->wm_size_hints = atom(client, "WM_SIZE_HINTS");
	client->wm_protocols = atom(client, "WM_PROTOCOLS");
	client->wm_take_focus = atom(client, "WM_TAKE_FOCUS");
	client->wm_transient_for = atom(client, "WM_TRANSIENT_FOR");
	client->first = create_window(client, "focus-a", 80, 80, true);
	client->second = create_window(client, "focus-b", 150, 120, false);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
		client->second, client->wm_transient_for, XCB_ATOM_WINDOW, 32, 1,
		&client->first);
	xcb_map_window(client->connection, client->first);
	xcb_map_window(client->connection, client->second);
	xcb_flush(client->connection);
	return true;
}

static void drain_x_events(struct client *client) {
	xcb_generic_event_t *event;
	while ((event = xcb_poll_for_event(client->connection)) != NULL) {
		if ((event->response_type & ~UINT8_C(0x80)) == XCB_CLIENT_MESSAGE) {
			xcb_client_message_event_t *message = (xcb_client_message_event_t *)event;
			if (message->type == client->wm_protocols &&
					message->data.data32[0] == client->wm_take_focus) {
				if (message->window == client->first) ++client->take_focus_first;
				if (message->window == client->second) ++client->take_focus_second;
			}
		}
		free(event);
	}
}

static const char *input_focus_name(struct client *client) {
	xcb_get_input_focus_cookie_t cookie = xcb_get_input_focus(client->connection);
	xcb_get_input_focus_reply_t *reply =
		xcb_get_input_focus_reply(client->connection, cookie, NULL);
	if (reply == NULL) return "error";
	xcb_window_t focus = reply->focus;
	free(reply);
	if (focus == client->first) return "a";
	if (focus == client->second) return "b";
	if (focus == XCB_INPUT_FOCUS_POINTER_ROOT) return "root";
	return "other";
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	if (!initialize(&client)) return 1;
	puts("READY");
	for (;;) {
		struct pollfd descriptors[2] = {
			{.fd = STDIN_FILENO, .events = POLLIN},
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
		};
		if (poll(descriptors, 2, 100) < 0) return 1;
		drain_x_events(&client);
		if ((descriptors[0].revents & POLLIN) == 0) continue;
		char command[32];
		if (fgets(command, sizeof(command), stdin) == NULL) break;
		command[strcspn(command, "\r\n")] = '\0';
		if (strcmp(command, "STATUS") == 0) {
			printf("STATUS %u %u %s\n", client.take_focus_first,
				client.take_focus_second, input_focus_name(&client));
		} else if (strcmp(command, "CLEAR_HINTS_A") == 0) {
			xcb_delete_property(client.connection, client.first, client.wm_hints);
			xcb_flush(client.connection);
			puts("HINTS_A_CLEARED");
		} else if (strcmp(command, "EXIT") == 0) {
			break;
		} else {
			abort();
		}
	}
	xcb_disconnect(client.connection);
	return 0;
}
