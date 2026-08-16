/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <xcb/xcb.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum {
	HINT_US_POSITION = 1u << 0,
	HINT_P_POSITION = 1u << 2,
};

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_atom_t wm_normal_hints;
	xcb_atom_t wm_size_hints;
	xcb_atom_t wm_transient_for;
	xcb_window_t remap;
};

static void die(const char *message) {
	fprintf(stderr, "%s\n", message);
	exit(1);
}

static xcb_atom_t atom(struct client *client, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(client->connection, false,
		(uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply =
		xcb_intern_atom_reply(client->connection, cookie, NULL);
	if (reply == NULL) die("could not intern atom");
	xcb_atom_t value = reply->atom;
	free(reply);
	return value;
}

static xcb_window_t create_window(struct client *client, const char *title,
		int16_t x, int16_t y, uint16_t width, uint16_t height, uint32_t flags) {
	xcb_window_t window = xcb_generate_id(client->connection);
	uint32_t values[] = {client->screen->black_pixel,
		XCB_EVENT_MASK_STRUCTURE_NOTIFY};
	xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, window,
		client->screen->root, x, y, width, height, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_NAME, XCB_ATOM_STRING, 8, (uint32_t)strlen(title), title);
	char class_value[128];
	int used = snprintf(class_value, sizeof(class_value), "%s%cPlacement%c",
		title, '\0', '\0');
	if (used < 0 || (size_t)used + 1 > sizeof(class_value)) die("class too long");
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8, (uint32_t)used + 1, class_value);
	if (flags != 0) {
		uint32_t hints[18] = {0};
		hints[0] = flags;
		hints[1] = (uint32_t)x;
		hints[2] = (uint32_t)y;
		hints[3] = width;
		hints[4] = height;
		xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
			client->wm_normal_hints, client->wm_size_hints, 32, 18, hints);
	}
	return window;
}

static void map(struct client *client, xcb_window_t window) {
	xcb_map_window(client->connection, window);
}

static void create_scenario(struct client *client, const char *scenario) {
	if (strcmp(scenario, "us") == 0) {
		map(client, create_window(client, "placement-us", 11, 13, 100, 80,
			HINT_US_POSITION));
	} else if (strcmp(scenario, "p") == 0) {
		map(client, create_window(client, "placement-p-zero", 0, 0, 100, 80,
			HINT_P_POSITION));
		map(client, create_window(client, "placement-p-nonzero", 40, 50, 100, 80,
			HINT_P_POSITION));
	} else if (strcmp(scenario, "nohint") == 0) {
		map(client, create_window(client, "placement-nohint", 90, 70, 100, 80, 0));
	} else if (strcmp(scenario, "transient") == 0) {
		xcb_window_t owner = create_window(client, "placement-owner", 10, 12,
			100, 80, HINT_US_POSITION);
		xcb_window_t transient = create_window(client, "placement-transient",
			77, 88, 90, 60, 0);
		xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, transient,
			client->wm_transient_for, XCB_ATOM_WINDOW, 32, 1, &owner);
		map(client, owner);
		map(client, transient);
	} else if (strcmp(scenario, "random") == 0 ||
			strcmp(scenario, "edge") == 0) {
		map(client, create_window(client, "placement-random-1", 0, 0, 100, 80, 0));
		map(client, create_window(client, "placement-random-2", 0, 0, 100, 80, 0));
		if (strcmp(scenario, "random") == 0)
			map(client, create_window(client, "placement-random-3", 0, 0,
				100, 80, 0));
		else
			map(client, create_window(client, "placement-random-oversized", 0, 0,
				200, 180, 0));
	} else if (strcmp(scenario, "max") == 0) {
		map(client, create_window(client, "placement-max", 10, 12, 900, 700,
			HINT_US_POSITION));
	} else if (strcmp(scenario, "defaultmax") == 0) {
		map(client, create_window(client, "placement-default-max", 10, 12,
			40000, 40000, HINT_US_POSITION));
	} else if (strcmp(scenario, "remap") == 0) {
		client->remap = create_window(client, "placement-remap", 66, 77,
			100, 80, HINT_US_POSITION);
		map(client, client->remap);
	} else {
		die("unknown scenario");
	}
	xcb_flush(client->connection);
}

int main(int argc, char **argv) {
	if (argc != 2) die("usage: xwayland-placement-client SCENARIO");
	int screen_index = 0;
	struct client client = {0};
	client.connection = xcb_connect(NULL, &screen_index);
	if (xcb_connection_has_error(client.connection)) die("could not connect to X11");
	const xcb_setup_t *setup = xcb_get_setup(client.connection);
	xcb_screen_iterator_t iterator = xcb_setup_roots_iterator(setup);
	for (int index = 0; index < screen_index; ++index) xcb_screen_next(&iterator);
	client.screen = iterator.data;
	if (client.screen == NULL) die("missing X11 screen");
	client.wm_normal_hints = atom(&client, "WM_NORMAL_HINTS");
	client.wm_size_hints = atom(&client, "WM_SIZE_HINTS");
	client.wm_transient_for = atom(&client, "WM_TRANSIENT_FOR");
	create_scenario(&client, argv[1]);
	puts("READY");
	fflush(stdout);
	char command[64];
	while (fgets(command, sizeof(command), stdin) != NULL) {
		if (strcmp(command, "REMAP\n") == 0 && client.remap != XCB_WINDOW_NONE) {
			xcb_unmap_window(client.connection, client.remap);
			xcb_flush(client.connection);
			struct timespec delay = {.tv_sec = 0, .tv_nsec = 100000000};
			(void)nanosleep(&delay, NULL);
			xcb_map_window(client.connection, client.remap);
			xcb_flush(client.connection);
			puts("REMAPPED");
			fflush(stdout);
		} else if (strcmp(command, "QUIT\n") == 0) {
			break;
		}
	}
	xcb_disconnect(client.connection);
	return 0;
}
