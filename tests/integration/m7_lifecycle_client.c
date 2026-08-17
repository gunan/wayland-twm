/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <xcb/xcb.h>

#define WINDOW_COUNT 256U

struct client_window {
	xcb_window_t window;
	bool live;
};

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_atom_t wm_icon_name;
	struct client_window windows[WINDOW_COUNT];
};

static xcb_atom_t atom(struct client *client, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(client->connection, false,
		(uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(client->connection,
		cookie, NULL);
	if (reply == NULL) return XCB_ATOM_NONE;
	xcb_atom_t result = reply->atom;
	free(reply);
	return result;
}

static bool checked(struct client *client, xcb_void_cookie_t cookie) {
	xcb_generic_error_t *error = xcb_request_check(client->connection, cookie);
	if (error == NULL) return true;
	free(error);
	return false;
}

static bool roundtrip(struct client *client) {
	xcb_get_input_focus_cookie_t cookie = xcb_get_input_focus(client->connection);
	xcb_get_input_focus_reply_t *reply = xcb_get_input_focus_reply(
		client->connection, cookie, NULL);
	if (reply == NULL) return false;
	free(reply);
	return xcb_connection_has_error(client->connection) == 0;
}

static void set_text(struct client *client, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		property, XCB_ATOM_STRING, 8, (uint32_t)strlen(value), value);
}

static bool create_window(struct client *client, unsigned int index,
		const char *title) {
	if (index >= WINDOW_COUNT || client->windows[index].live) return false;
	xcb_window_t window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		UINT32_C(0x00203040) + index * UINT32_C(0x00010101),
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_EXPOSURE,
	};
	if (!checked(client, xcb_create_window_checked(client->connection,
			XCB_COPY_FROM_PARENT, window, client->screen->root,
			(int16_t)(16 + index % 32), (int16_t)(16 + index / 32),
			64, 40, 0, XCB_WINDOW_CLASS_INPUT_OUTPUT,
			client->screen->root_visual,
			XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values))) return false;
	set_text(client, window, XCB_ATOM_WM_NAME, title);
	set_text(client, window, client->wm_icon_name, title);
	static const char wm_class[] = "m7-churn\0M7Churn\0";
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8, sizeof(wm_class) - 1, wm_class);
	xcb_map_window(client->connection, window);
	client->windows[index].window = window;
	client->windows[index].live = true;
	return roundtrip(client);
}

static bool rename_window(struct client *client, unsigned int index,
		const char *title) {
	if (index >= WINDOW_COUNT || !client->windows[index].live) return false;
	set_text(client, client->windows[index].window, XCB_ATOM_WM_NAME, title);
	set_text(client, client->windows[index].window, client->wm_icon_name, title);
	xcb_flush(client->connection);
	return roundtrip(client);
}

static bool destroy_window(struct client *client, unsigned int index) {
	if (index >= WINDOW_COUNT || !client->windows[index].live) return false;
	if (!checked(client, xcb_destroy_window_checked(client->connection,
			client->windows[index].window))) return false;
	client->windows[index].window = XCB_WINDOW_NONE;
	client->windows[index].live = false;
	xcb_flush(client->connection);
	return roundtrip(client);
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (client->connection == NULL ||
			xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int index = 0; index < screen_number; ++index) xcb_screen_next(&screens);
	client->screen = screens.data;
	if (client->screen == NULL) return false;
	client->wm_icon_name = atom(client, "WM_ICON_NAME");
	if (client->wm_icon_name == XCB_ATOM_NONE) return false;
	for (unsigned int index = 0; index < WINDOW_COUNT; ++index) {
		char title[32];
		(void)snprintf(title, sizeof(title), "M7-%03u-g000", index);
		if (!create_window(client, index, title)) return false;
	}
	return true;
}

static bool handle_command(struct client *client, const char *line) {
	unsigned int index;
	char title[64];
	if (sscanf(line, "RENAME %u %63s", &index, title) == 2) {
		if (!rename_window(client, index, title)) return false;
		printf("OK RENAME %u %s\n", index, title);
		return true;
	}
	if (sscanf(line, "DESTROY %u", &index) == 1) {
		if (!destroy_window(client, index)) return false;
		printf("OK DESTROY %u\n", index);
		return true;
	}
	if (sscanf(line, "RECREATE %u %63s", &index, title) == 2) {
		if (!create_window(client, index, title)) return false;
		printf("OK RECREATE %u %s\n", index, title);
		return true;
	}
	if (strcmp(line, "QUIT") == 0) {
		puts("OK QUIT");
		return false;
	}
	fprintf(stderr, "m7 lifecycle client: invalid command: %s\n", line);
	exit(EXIT_FAILURE);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	if (!initialize(&client)) {
		fprintf(stderr, "m7 lifecycle client: initialization failed\n");
		if (client.connection != NULL) xcb_disconnect(client.connection);
		return EXIT_FAILURE;
	}
	printf("READY %u\n", WINDOW_COUNT);
	char line[160];
	while (fgets(line, sizeof(line), stdin) != NULL) {
		line[strcspn(line, "\r\n")] = '\0';
		if (!handle_command(&client, line)) break;
	}
	for (unsigned int index = 0; index < WINDOW_COUNT; ++index)
		if (client.windows[index].live)
			xcb_destroy_window(client.connection, client.windows[index].window);
	xcb_flush(client.connection);
	xcb_disconnect(client.connection);
	return EXIT_SUCCESS;
}
