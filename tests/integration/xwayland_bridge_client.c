/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xcb/xcb.h>

struct atoms {
	xcb_atom_t wm_protocols;
	xcb_atom_t wm_delete_window;
	xcb_atom_t wm_transient_for;
	xcb_atom_t wm_normal_hints;
	xcb_atom_t wm_size_hints;
	xcb_atom_t wm_hints;
	xcb_atom_t wm_icon_name;
	xcb_atom_t net_wm_icon;
};

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	struct atoms atoms;
	xcb_window_t parent;
	xcb_window_t transient;
	xcb_window_t override_redirect;
	xcb_window_t icon_window;
	xcb_pixmap_t icon_pixmap;
	xcb_pixmap_t icon_mask;
	xcb_connection_t *stubborn_connection;
	xcb_window_t stubborn;
	bool stubborn_reported;
};

static xcb_atom_t intern_atom(xcb_connection_t *connection, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(
		connection, false, (uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(connection, cookie, NULL);
	if (reply == NULL) return XCB_ATOM_NONE;
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
		const char *instance, const char *class_name) {
	char value[256];
	size_t instance_length = strlen(instance) + 1;
	size_t class_length = strlen(class_name) + 1;
	if (instance_length + class_length > sizeof(value)) abort();
	memcpy(value, instance, instance_length);
	memcpy(value + instance_length, class_name, class_length);
	xcb_change_property(connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8,
		(uint32_t)(instance_length + class_length), value);
}

static void set_normal_hints(struct client *client, int min_width, int min_height,
		int max_width, int max_height, int base_width, int base_height,
		int width_inc, int height_inc) {
	enum {
		P_MIN_SIZE = 1 << 4,
		P_MAX_SIZE = 1 << 5,
		P_RESIZE_INC = 1 << 6,
		BASE_SIZE = 1 << 8,
		P_WIN_GRAVITY = 1 << 9,
	};
	uint32_t hints[18] = {0};
	hints[0] = P_MIN_SIZE | P_MAX_SIZE | P_RESIZE_INC | BASE_SIZE | P_WIN_GRAVITY;
	hints[5] = (uint32_t)min_width;
	hints[6] = (uint32_t)min_height;
	hints[7] = (uint32_t)max_width;
	hints[8] = (uint32_t)max_height;
	hints[9] = (uint32_t)width_inc;
	hints[10] = (uint32_t)height_inc;
	hints[15] = (uint32_t)base_width;
	hints[16] = (uint32_t)base_height;
	hints[17] = XCB_GRAVITY_NORTH_WEST;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->parent,
		client->atoms.wm_normal_hints, client->atoms.wm_size_hints,
		32, 18, hints);
}

static void set_wm_hints(struct client *client, bool urgent, bool input) {
	enum {
		INPUT_HINT = 1 << 0,
		ICON_PIXMAP_HINT = 1 << 2,
		ICON_WINDOW_HINT = 1 << 3,
		ICON_MASK_HINT = 1 << 5,
		URGENCY_HINT = 1 << 8,
	};
	uint32_t hints[9] = {0};
	hints[0] = INPUT_HINT | ICON_PIXMAP_HINT | ICON_WINDOW_HINT | ICON_MASK_HINT |
		(urgent ? URGENCY_HINT : 0);
	hints[1] = input;
	hints[3] = client->icon_pixmap;
	hints[4] = client->icon_window;
	hints[7] = client->icon_mask;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->parent,
		client->atoms.wm_hints, client->atoms.wm_hints, 32, 9, hints);
}

static void set_net_wm_icon(struct client *client, uint32_t width, uint32_t height,
		uint32_t seed) {
	size_t length = 2 + (size_t)width * height;
	uint32_t *icon = calloc(length, sizeof(*icon));
	if (icon == NULL) abort();
	icon[0] = width;
	icon[1] = height;
	for (size_t i = 2; i < length; ++i)
		icon[i] = UINT32_C(0xff000000) | (seed + (uint32_t)i * UINT32_C(0x010101));
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->parent,
		client->atoms.net_wm_icon, XCB_ATOM_CARDINAL, 32, (uint32_t)length, icon);
	free(icon);
}

static xcb_window_t create_window(xcb_connection_t *connection, xcb_screen_t *screen,
		int16_t x, int16_t y, uint16_t width, uint16_t height, bool override_redirect) {
	xcb_window_t window = xcb_generate_id(connection);
	uint32_t mask = XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK;
	uint32_t values[3] = {
		screen->white_pixel,
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_PROPERTY_CHANGE,
		0,
	};
	if (override_redirect) {
		mask |= XCB_CW_OVERRIDE_REDIRECT;
		/* XCB values follow ascending value-mask bit order. */
		uint32_t ordered[3] = {values[0], 1, values[1]};
		xcb_create_window(connection, XCB_COPY_FROM_PARENT, window, screen->root,
			x, y, width, height, 0, XCB_WINDOW_CLASS_INPUT_OUTPUT,
			screen->root_visual, mask, ordered);
	} else {
		xcb_create_window(connection, XCB_COPY_FROM_PARENT, window, screen->root,
			x, y, width, height, 0, XCB_WINDOW_CLASS_INPUT_OUTPUT,
			screen->root_visual, mask, values);
	}
	return window;
}

static void map_and_damage_window(xcb_connection_t *connection,
		xcb_window_t window) {
	xcb_map_window(connection, window);
	/* Painting the background creates redirected pixmap damage for Xwayland. */
	xcb_clear_area(connection, false, window, 0, 0, 0, 0);
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection) != 0) return false;
	const xcb_setup_t *setup = xcb_get_setup(client->connection);
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(setup);
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	client->atoms = (struct atoms){
		.wm_protocols = intern_atom(client->connection, "WM_PROTOCOLS"),
		.wm_delete_window = intern_atom(client->connection, "WM_DELETE_WINDOW"),
		.wm_transient_for = intern_atom(client->connection, "WM_TRANSIENT_FOR"),
		.wm_normal_hints = intern_atom(client->connection, "WM_NORMAL_HINTS"),
		.wm_size_hints = intern_atom(client->connection, "WM_SIZE_HINTS"),
		.wm_hints = intern_atom(client->connection, "WM_HINTS"),
		.wm_icon_name = intern_atom(client->connection, "WM_ICON_NAME"),
		.net_wm_icon = intern_atom(client->connection, "_NET_WM_ICON"),
	};
	client->icon_pixmap = xcb_generate_id(client->connection);
	xcb_create_pixmap(client->connection, 1, client->icon_pixmap,
		client->screen->root, 16, 16);
	client->icon_mask = xcb_generate_id(client->connection);
	xcb_create_pixmap(client->connection, 1, client->icon_mask,
		client->screen->root, 16, 16);
	client->icon_window = create_window(client->connection, client->screen,
		0, 0, 16, 16, false);
	client->parent = create_window(client->connection, client->screen,
		40, 50, 220, 150, false);
	set_string(client->connection, client->parent, XCB_ATOM_WM_NAME,
		"xwm-parent-initial");
	set_string(client->connection, client->parent, client->atoms.wm_icon_name,
		"xwm-icon-initial");
	set_class(client->connection, client->parent, "xwm-instance-initial",
		"XwmClassInitial");
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->parent,
		client->atoms.wm_protocols, XCB_ATOM_ATOM, 32, 1,
		&client->atoms.wm_delete_window);
	set_normal_hints(client, 80, 60, 320, 240, 40, 30, 20, 10);
	set_wm_hints(client, true, false);
	set_net_wm_icon(client, 2, 2, UINT32_C(0x10));
	/* This request is deliberately sent before the X window has a wl_surface. */
	uint32_t initial_geometry[] = {44, 55, 221, 151};
	xcb_configure_window(client->connection, client->parent,
		XCB_CONFIG_WINDOW_X | XCB_CONFIG_WINDOW_Y |
		XCB_CONFIG_WINDOW_WIDTH | XCB_CONFIG_WINDOW_HEIGHT, initial_geometry);

	client->transient = create_window(client->connection, client->screen,
		90, 100, 140, 90, false);
	set_string(client->connection, client->transient, XCB_ATOM_WM_NAME,
		"xwm-transient");
	set_class(client->connection, client->transient, "xwm-transient-instance",
		"XwmTransientClass");
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->transient,
		client->atoms.wm_transient_for, XCB_ATOM_WINDOW, 32, 1, &client->parent);

	client->override_redirect = create_window(client->connection, client->screen,
		300, 20, 100, 50, true);
	set_string(client->connection, client->override_redirect, XCB_ATOM_WM_NAME,
		"xwm-override-redirect");
	map_and_damage_window(client->connection, client->parent);
	map_and_damage_window(client->connection, client->transient);
	map_and_damage_window(client->connection, client->override_redirect);
	xcb_flush(client->connection);
	return true;
}

static void update_metadata(struct client *client) {
	set_string(client->connection, client->parent, XCB_ATOM_WM_NAME,
		"xwm-parent-updated");
	set_string(client->connection, client->parent, client->atoms.wm_icon_name,
		"xwm-icon-updated");
	set_class(client->connection, client->parent, "xwm-instance-updated",
		"XwmClassUpdated");
	set_normal_hints(client, 100, 70, 300, 220, 50, 40, 25, 15);
	set_wm_hints(client, false, true);
	set_net_wm_icon(client, 3, 2, UINT32_C(0x20));
	xcb_flush(client->connection);
	puts("UPDATED");
}

static void create_stubborn(struct client *client) {
	int screen_number = 0;
	client->stubborn_connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->stubborn_connection) != 0) abort();
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(client->stubborn_connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->stubborn = create_window(client->stubborn_connection, screens.data,
		420, 260, 150, 100, false);
	set_string(client->stubborn_connection, client->stubborn, XCB_ATOM_WM_NAME,
		"xwm-stubborn");
	set_class(client->stubborn_connection, client->stubborn,
		"xwm-stubborn-instance", "XwmStubbornClass");
	map_and_damage_window(client->stubborn_connection, client->stubborn);
	xcb_flush(client->stubborn_connection);
	puts("STUBBORN_MAPPED");
}

static bool handle_command(struct client *client, const char *command) {
	if (strcmp(command, "UPDATE") == 0) update_metadata(client);
	else if (strcmp(command, "TRUNCATE_ICON") == 0) {
		set_net_wm_icon(client, 257, 257, UINT32_C(0x30));
		xcb_flush(client->connection);
		puts("TRUNCATED_ICON_SET");
	} else if (strcmp(command, "RESTORE_ICON") == 0) {
		set_net_wm_icon(client, 3, 2, UINT32_C(0x20));
		xcb_flush(client->connection);
		puts("ICON_RESTORED");
	} else if (strcmp(command, "CLEAR_TRANSIENT") == 0) {
		xcb_delete_property(client->connection, client->transient,
			client->atoms.wm_transient_for);
		xcb_flush(client->connection);
		puts("TRANSIENT_CLEARED");
	} else if (strcmp(command, "RESTORE_TRANSIENT") == 0) {
		xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
			client->transient, client->atoms.wm_transient_for,
			XCB_ATOM_WINDOW, 32, 1, &client->parent);
		xcb_flush(client->connection);
		puts("TRANSIENT_RESTORED");
	} else if (strcmp(command, "CONFIGURE") == 0) {
		uint32_t values[] = {120, 100, 277, 199};
		xcb_configure_window(client->connection, client->parent,
			XCB_CONFIG_WINDOW_X | XCB_CONFIG_WINDOW_Y |
			XCB_CONFIG_WINDOW_WIDTH | XCB_CONFIG_WINDOW_HEIGHT, values);
		xcb_flush(client->connection);
		puts("CONFIGURE_REQUESTED");
	} else if (strcmp(command, "RESTACK") == 0) {
		uint32_t values[] = {client->parent, XCB_STACK_MODE_ABOVE};
		xcb_configure_window(client->connection, client->transient,
			XCB_CONFIG_WINDOW_SIBLING | XCB_CONFIG_WINDOW_STACK_MODE, values);
		xcb_flush(client->connection);
		puts("RESTACK_REQUESTED");
	} else if (strcmp(command, "UNMAP_OR") == 0) {
		xcb_unmap_window(client->connection, client->override_redirect);
		xcb_flush(client->connection);
		puts("OR_UNMAPPED");
	} else if (strcmp(command, "REMAP_OR") == 0) {
		map_and_damage_window(client->connection, client->override_redirect);
		xcb_flush(client->connection);
		puts("OR_REMAPPED");
	} else if (strcmp(command, "UNMAP_PARENT") == 0) {
		xcb_unmap_window(client->connection, client->parent);
		xcb_flush(client->connection);
		puts("PARENT_UNMAPPED");
	} else if (strcmp(command, "REMAP_PARENT") == 0) {
		map_and_damage_window(client->connection, client->parent);
		xcb_flush(client->connection);
		puts("PARENT_REMAPPED");
	} else if (strcmp(command, "CREATE_STUBBORN") == 0) create_stubborn(client);
	else if (strcmp(command, "EXIT") == 0) return false;
	else abort();
	return true;
}

static void handle_events(struct client *client) {
	xcb_generic_event_t *event;
	while ((event = xcb_poll_for_event(client->connection)) != NULL) {
		if ((event->response_type & ~0x80) == XCB_CLIENT_MESSAGE) {
			xcb_client_message_event_t *message = (xcb_client_message_event_t *)event;
			if (message->type == client->atoms.wm_protocols &&
					message->data.data32[0] == client->atoms.wm_delete_window) {
				printf("DELETE_RECEIVED %" PRIu32 "\n", message->window);
				xcb_destroy_window(client->connection, message->window);
				xcb_flush(client->connection);
			}
		}
		free(event);
	}
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	if (!initialize(&client)) return 1;
	puts("READY");
	bool running = true;
	while (running) {
		struct pollfd descriptors[3] = {
			{.fd = STDIN_FILENO, .events = POLLIN},
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
			{.fd = client.stubborn_connection != NULL ?
				xcb_get_file_descriptor(client.stubborn_connection) : -1, .events = POLLIN},
		};
		if (poll(descriptors, 3, 100) < 0) return 1;
		if (descriptors[0].revents & POLLIN) {
			char command[128];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			running = handle_command(&client, command);
		}
		handle_events(&client);
		if (client.stubborn_connection != NULL) {
			xcb_generic_event_t *event;
			while ((event = xcb_poll_for_event(client.stubborn_connection)) != NULL)
				free(event);
		}
		if (client.stubborn_connection != NULL && !client.stubborn_reported &&
				xcb_connection_has_error(client.stubborn_connection) != 0) {
			client.stubborn_reported = true;
			puts("STUBBORN_KILLED");
		}
	}
	if (client.stubborn_connection != NULL) xcb_disconnect(client.stubborn_connection);
	xcb_disconnect(client.connection);
	return 0;
}
