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

enum { CHILD_COUNT = 3 };

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_atom_t wm_colormap_windows;
	xcb_window_t top;
	xcb_window_t children[CHILD_COUNT];
	xcb_window_t invalid_window;
	xcb_colormap_t top_colormap;
	xcb_colormap_t child_colormaps[CHILD_COUNT];
	bool running;
};

static void fail(const char *message) {
	fprintf(stderr, "m8 colormap client: %s\n", message);
	exit(EXIT_FAILURE);
}

static xcb_atom_t intern_atom(xcb_connection_t *connection, const char *name) {
	xcb_generic_error_t *error = NULL;
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(connection,
		xcb_intern_atom(connection, false, (uint16_t)strlen(name), name), &error);
	if (error != NULL) {
		free(error);
		fail("could not intern an atom");
	}
	if (reply == NULL) fail("atom reply was empty");
	xcb_atom_t atom = reply->atom;
	free(reply);
	return atom;
}

static void check_request(struct client *client, xcb_void_cookie_t cookie,
		const char *operation) {
	xcb_generic_error_t *error = xcb_request_check(client->connection, cookie);
	if (error == NULL) return;
	fprintf(stderr,
		"m8 colormap client: %s failed: X error %u request %u.%u\n",
		operation, error->error_code, error->major_code, error->minor_code);
	free(error);
	exit(EXIT_FAILURE);
}

static void set_string(struct client *client, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	check_request(client, xcb_change_property_checked(client->connection,
		XCB_PROP_MODE_REPLACE, window, property, XCB_ATOM_STRING, 8,
		(uint32_t)strlen(value), value), "set string property");
}

static void set_class(struct client *client, const char *instance,
		const char *class_name) {
	char value[128];
	size_t instance_length = strlen(instance) + 1;
	size_t class_length = strlen(class_name) + 1;
	if (instance_length + class_length > sizeof(value))
		fail("WM_CLASS fixture is too long");
	memcpy(value, instance, instance_length);
	memcpy(value + instance_length, class_name, class_length);
	check_request(client, xcb_change_property_checked(client->connection,
		XCB_PROP_MODE_REPLACE, client->top, XCB_ATOM_WM_CLASS,
		XCB_ATOM_STRING, 8, (uint32_t)(instance_length + class_length), value),
		"set WM_CLASS");
}

static xcb_colormap_t create_colormap(struct client *client) {
	xcb_colormap_t colormap = xcb_generate_id(client->connection);
	check_request(client, xcb_create_colormap_checked(client->connection,
		XCB_COLORMAP_ALLOC_NONE, colormap, client->screen->root,
		client->screen->root_visual), "create private colormap");
	return colormap;
}

static xcb_window_t create_window(struct client *client, xcb_window_t parent,
		xcb_colormap_t colormap, int16_t x, int16_t y,
		uint16_t width, uint16_t height) {
	xcb_window_t window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		client->screen->black_pixel,
		XCB_EVENT_MASK_EXPOSURE | XCB_EVENT_MASK_STRUCTURE_NOTIFY |
			XCB_EVENT_MASK_COLOR_MAP_CHANGE,
		colormap,
	};
	check_request(client, xcb_create_window_checked(client->connection,
		XCB_COPY_FROM_PARENT, window, parent, x, y, width, height, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK | XCB_CW_COLORMAP, values),
		"create colormap window");
	return window;
}

static void set_colormap_windows(struct client *client,
		const xcb_window_t *windows, size_t count) {
	check_request(client, xcb_change_property_checked(client->connection,
		XCB_PROP_MODE_REPLACE, client->top, client->wm_colormap_windows,
		XCB_ATOM_WINDOW, 32, (uint32_t)count, windows),
		"set WM_COLORMAP_WINDOWS");
	xcb_flush(client->connection);
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (client->connection == NULL ||
			xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	if (client->screen == NULL) return false;
	client->wm_colormap_windows = intern_atom(client->connection,
		"WM_COLORMAP_WINDOWS");
	client->top_colormap = create_colormap(client);
	client->invalid_window = xcb_generate_id(client->connection);
	for (size_t i = 0; i < CHILD_COUNT; ++i)
		client->child_colormaps[i] = create_colormap(client);
	client->top = create_window(client, client->screen->root,
		client->top_colormap, 120, 100, 240, 160);
	set_string(client, client->top, XCB_ATOM_WM_NAME, "wtwm-colormap-x11");
	set_class(client, "wtwm-colormap", "WtwmColormap");
	for (size_t i = 0; i < CHILD_COUNT; ++i) {
		client->children[i] = create_window(client, client->top,
			client->child_colormaps[i], (int16_t)(10 + i * 60), 20, 50, 50);
		check_request(client, xcb_map_window_checked(client->connection,
			client->children[i]), "map colormap child");
	}
	/* Omit the top-level deliberately: reference twm inserts it at the front. */
	set_colormap_windows(client, client->children, CHILD_COUNT);
	check_request(client, xcb_map_window_checked(client->connection, client->top),
		"map colormap top-level");
	xcb_flush(client->connection);
	return xcb_connection_has_error(client->connection) == 0;
}

static xcb_colormap_t named_colormap(const struct client *client,
		const char *name) {
	if (strcmp(name, "top") == 0) return client->top_colormap;
	if (strcmp(name, "one") == 0) return client->child_colormaps[0];
	if (strcmp(name, "two") == 0) return client->child_colormaps[1];
	if (strcmp(name, "three") == 0) return client->child_colormaps[2];
	return XCB_COLORMAP_NONE;
}

static xcb_list_installed_colormaps_reply_t *installed_colormaps(
		struct client *client) {
	xcb_generic_error_t *error = NULL;
	xcb_list_installed_colormaps_reply_t *reply =
		xcb_list_installed_colormaps_reply(client->connection,
			xcb_list_installed_colormaps(client->connection,
				client->screen->root), &error);
	if (error != NULL) {
		free(error);
		fail("could not list installed colormaps");
	}
	if (reply == NULL) fail("installed-colormap reply was empty");
	return reply;
}

static bool expect_colormap(struct client *client, const char *name) {
	xcb_colormap_t expected = named_colormap(client, name);
	if (expected == XCB_COLORMAP_NONE) return false;
	xcb_list_installed_colormaps_reply_t *reply = installed_colormaps(client);
	int count = xcb_list_installed_colormaps_cmaps_length(reply);
	xcb_colormap_t *maps = xcb_list_installed_colormaps_cmaps(reply);
	bool found = false;
	for (int i = 0; i < count; ++i)
		if (maps[i] == expected) found = true;
	bool exact = client->screen->max_installed_maps != 1 ||
		(count == 1 && maps[0] == expected);
	if (!found || !exact) {
		fprintf(stderr,
			"m8 colormap client: expected %s colormap 0x%08" PRIx32
			" among %d installed maps (screen maximum %u)\n",
			name, expected, count, client->screen->max_installed_maps);
		free(reply);
		return false;
	}
	printf("OK EXPECT %s count=%d\n", name, count);
	free(reply);
	return true;
}

static void print_snapshot(struct client *client, const char *label) {
	xcb_list_installed_colormaps_reply_t *reply = installed_colormaps(client);
	int count = xcb_list_installed_colormaps_cmaps_length(reply);
	xcb_colormap_t *maps = xcb_list_installed_colormaps_cmaps(reply);
	printf("OK SNAPSHOT %s", label);
	for (int i = 0; i < count; ++i) printf(" 0x%08" PRIx32, maps[i]);
	putchar('\n');
	free(reply);
}

static bool print_property(struct client *client, const char *label) {
	xcb_generic_error_t *error = NULL;
	xcb_get_property_reply_t *reply = xcb_get_property_reply(client->connection,
		xcb_get_property(client->connection, false, client->top,
			client->wm_colormap_windows, XCB_ATOM_WINDOW, 0, 64), &error);
	if (error != NULL) free(error);
	if (reply == NULL || reply->type != XCB_ATOM_WINDOW ||
			reply->format != 32 || reply->bytes_after != 0) {
		free(reply);
		return false;
	}
	int count = xcb_get_property_value_length(reply) /
		(int)sizeof(xcb_window_t);
	xcb_window_t *windows = xcb_get_property_value(reply);
	printf("OK PROPERTY %s", label);
	for (int i = 0; i < count; ++i) printf(" 0x%08" PRIx32, windows[i]);
	putchar('\n');
	free(reply);
	return true;
}

static bool ping(struct client *client) {
	xcb_generic_error_t *error = NULL;
	xcb_get_geometry_reply_t *reply = xcb_get_geometry_reply(client->connection,
		xcb_get_geometry(client->connection, client->top), &error);
	if (error != NULL) free(error);
	if (reply == NULL) return false;
	free(reply);
	puts("OK PONG");
	return xcb_connection_has_error(client->connection) == 0;
}

static bool handle_command(struct client *client, char *command) {
	char argument[64];
	if (sscanf(command, "EXPECT %63s", argument) == 1)
		return expect_colormap(client, argument);
	if (sscanf(command, "SNAPSHOT %63s", argument) == 1) {
		print_snapshot(client, argument);
		return true;
	}
	if (sscanf(command, "PROPERTY %63s", argument) == 1)
		return print_property(client, argument);
	if (strcmp(command, "MUTATE") == 0) {
		xcb_window_t replacement[] = {
			client->invalid_window, client->children[2], client->children[1],
		};
		set_colormap_windows(client, replacement,
			sizeof(replacement) / sizeof(replacement[0]));
		puts("OK MUTATED three two");
		return true;
	}
	if (strcmp(command, "PING") == 0) return ping(client);
	if (strcmp(command, "EXIT") == 0) {
		puts("OK EXIT");
		client->running = false;
		return true;
	}
	fprintf(stderr, "m8 colormap client: unknown command %s\n", command);
	return false;
}

static void drain_events(struct client *client) {
	xcb_generic_event_t *event;
	while ((event = xcb_poll_for_event(client->connection)) != NULL) {
		if ((event->response_type & UINT8_C(0x7f)) == XCB_EXPOSE) {
			xcb_expose_event_t *expose = (xcb_expose_event_t *)event;
			if (expose->count == 0)
				xcb_clear_area(client->connection, false, expose->window,
					0, 0, 0, 0);
		}
		free(event);
	}
	xcb_flush(client->connection);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {.running = true};
	if (!initialize(&client)) fail("initialization failed");
	printf("OK READY wtwm-colormap-x11 max=%u top=0x%08" PRIx32
		" one=0x%08" PRIx32 " two=0x%08" PRIx32
		" three=0x%08" PRIx32 "\n",
		client.screen->max_installed_maps, client.top_colormap,
		client.child_colormaps[0], client.child_colormaps[1],
		client.child_colormaps[2]);

	while (client.running) {
		drain_events(&client);
		struct pollfd descriptors[] = {
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, 100);
		while (result < 0 && errno == EINTR);
		if (result < 0 ||
				(descriptors[0].revents & (POLLERR | POLLHUP)) != 0) break;
		if ((descriptors[0].revents & POLLIN) != 0) drain_events(&client);
		if ((descriptors[1].revents & (POLLIN | POLLHUP)) != 0) {
			char command[128];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (!handle_command(&client, command)) break;
		}
		if (xcb_connection_has_error(client.connection) != 0) break;
	}

	if (client.connection != NULL) {
		xcb_destroy_window(client.connection, client.top);
		xcb_free_colormap(client.connection, client.top_colormap);
		for (size_t i = 0; i < CHILD_COUNT; ++i)
			xcb_free_colormap(client.connection, client.child_colormaps[i]);
		xcb_flush(client.connection);
		xcb_disconnect(client.connection);
	}
	return client.running ? EXIT_FAILURE : EXIT_SUCCESS;
}
