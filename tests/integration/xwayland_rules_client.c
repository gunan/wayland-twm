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

enum rule_window_index {
	RULE_TITLE,
	RULE_INSTANCE,
	RULE_CLASS,
	RULE_CASE,
	RULE_AUTO_RAISE,
	RULE_START_ICONIFIED,
	RULE_PLAIN,
	RULE_COLLISION,
	RULE_WINDOW_COUNT,
};

struct repaint_target {
	xcb_window_t window;
	uint32_t black_pixel;
	uint32_t white_pixel;
	bool paint_white;
	bool desired_mapped;
};

struct rule_window {
	xcb_window_t window;
	struct repaint_target repaint;
};

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	struct rule_window windows[RULE_WINDOW_COUNT];
};

struct window_spec {
	const char *title;
	const char *instance;
	const char *class_name;
	int16_t x;
	int16_t y;
};

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

static bool repaint_target_window(xcb_connection_t *connection,
		struct repaint_target *target) {
	if (!target->desired_mapped) return false;
	uint32_t pixel = target->paint_white ? target->white_pixel : target->black_pixel;
	target->paint_white = !target->paint_white;
	xcb_change_window_attributes(connection, target->window,
		XCB_CW_BACK_PIXEL, &pixel);
	xcb_clear_area(connection, false, target->window, 0, 0, 0, 0);
	return true;
}

static void map_and_damage_window(struct client *client, struct rule_window *window) {
	window->repaint.window = window->window;
	window->repaint.black_pixel = client->screen->black_pixel;
	window->repaint.white_pixel = client->screen->white_pixel;
	window->repaint.desired_mapped = true;
	xcb_map_window(client->connection, window->window);
	repaint_target_window(client->connection, &window->repaint);
}

static bool initialize(struct client *client) {
	static const struct window_spec specs[RULE_WINDOW_COUNT] = {
		[RULE_TITLE] = {"RuleTitle", "plain-name", "PlainNameClass", 20, 20},
		[RULE_INSTANCE] = {"Instance Window", "rule-instance", "InstanceClass", 220, 20},
		[RULE_CLASS] = {"Class Window", "plain-class", "RuleClass", 420, 20},
		[RULE_CASE] = {"case-sensitive", "case-instance", "CaseClass", 620, 20},
		[RULE_AUTO_RAISE] = {"Auto Window", "auto-instance", "AutoClass", 20, 220},
		[RULE_START_ICONIFIED] = {"Start Window", "start-instance", "StartClass", 220, 220},
		[RULE_PLAIN] = {"Plain Window", "plain-instance", "PlainClass", 420, 220},
		[RULE_COLLISION] = {"Collision Window", "collision-instance", "CollisionClass", 620, 220},
	};
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(client->connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	if (client->screen == NULL) return false;
	for (size_t i = 0; i < RULE_WINDOW_COUNT; ++i) {
		struct rule_window *window = &client->windows[i];
		window->window = xcb_generate_id(client->connection);
		uint32_t mask = XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK;
		uint32_t values[] = {
			client->screen->white_pixel,
			XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_PROPERTY_CHANGE,
		};
		xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, window->window,
			client->screen->root, specs[i].x, specs[i].y, 160, 100, 0,
			XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
			mask, values);
		set_string(client->connection, window->window, XCB_ATOM_WM_NAME,
			specs[i].title);
		set_class(client->connection, window->window, specs[i].instance,
			specs[i].class_name);
		map_and_damage_window(client, window);
	}
	xcb_flush(client->connection);
	return true;
}

static bool handle_command(struct client *client, const char *command) {
	struct rule_window *plain = &client->windows[RULE_PLAIN];
	struct rule_window *auto_raise = &client->windows[RULE_AUTO_RAISE];
	struct rule_window *start = &client->windows[RULE_START_ICONIFIED];
	if (strcmp(command, "UPDATE_PLAIN_TITLE") == 0) {
		set_string(client->connection, plain->window, XCB_ATOM_WM_NAME, "RuleTitle");
		xcb_flush(client->connection);
		puts("PLAIN_TITLE_UPDATED");
	} else if (strcmp(command, "UPDATE_PLAIN_CLASS") == 0) {
		set_string(client->connection, plain->window, XCB_ATOM_WM_NAME, "Plain Window");
		set_class(client->connection, plain->window, "plain-instance", "RuleClass");
		xcb_flush(client->connection);
		puts("PLAIN_CLASS_UPDATED");
	} else if (strcmp(command, "RESET_PLAIN") == 0) {
		set_string(client->connection, plain->window, XCB_ATOM_WM_NAME, "Plain Window");
		set_class(client->connection, plain->window, "plain-instance", "PlainClass");
		xcb_flush(client->connection);
		puts("PLAIN_RESET");
	} else if (strcmp(command, "UPDATE_AUTO_CLASS") == 0) {
		set_class(client->connection, auto_raise->window,
			"auto-instance-updated", "AutoClassUpdated");
		xcb_flush(client->connection);
		puts("AUTO_CLASS_UPDATED");
	} else if (strcmp(command, "UNMAP_AUTO") == 0) {
		auto_raise->repaint.desired_mapped = false;
		xcb_unmap_window(client->connection, auto_raise->window);
		xcb_flush(client->connection);
		puts("AUTO_UNMAPPED");
	} else if (strcmp(command, "REMAP_AUTO") == 0) {
		map_and_damage_window(client, auto_raise);
		xcb_flush(client->connection);
		puts("AUTO_REMAPPED");
	} else if (strcmp(command, "UNMAP_START") == 0) {
		start->repaint.desired_mapped = false;
		xcb_unmap_window(client->connection, start->window);
		xcb_flush(client->connection);
		puts("START_UNMAPPED");
	} else if (strcmp(command, "REMAP_START") == 0) {
		map_and_damage_window(client, start);
		xcb_flush(client->connection);
		puts("START_REMAPPED");
	} else if (strcmp(command, "EXIT") == 0) {
		return false;
	} else {
		abort();
	}
	return true;
}

static void handle_events(struct client *client) {
	xcb_generic_event_t *event;
	while ((event = xcb_poll_for_event(client->connection)) != NULL) {
		if ((event->response_type & ~UINT8_C(0x80)) == XCB_MAP_NOTIFY) {
			xcb_map_notify_event_t *map = (xcb_map_notify_event_t *)event;
			for (size_t i = 0; i < RULE_WINDOW_COUNT; ++i) {
				struct repaint_target *target = &client->windows[i].repaint;
				if (target->window == map->window)
					repaint_target_window(client->connection, target);
			}
		}
		free(event);
	}
}

static void repaint_windows(struct client *client) {
	bool sent = false;
	for (size_t i = 0; i < RULE_WINDOW_COUNT; ++i)
		sent |= repaint_target_window(client->connection,
			&client->windows[i].repaint);
	if (sent) xcb_flush(client->connection);
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
		if (descriptors[0].revents & POLLIN) {
			char command[128];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			running = handle_command(&client, command);
		}
		handle_events(&client);
		repaint_windows(&client);
	}
	xcb_disconnect(client.connection);
	return 0;
}
