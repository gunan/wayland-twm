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

enum role_index {
	ROLE_X11_A,
	ROLE_X11_B,
	ROLE_COUNT,
};

struct role {
	const char *name;
	const char *title;
	const char *instance;
	const char *class_name;
	xcb_window_t window;
	uint32_t primary_color;
	uint32_t alternate_color;
	bool paint_alternate;
	bool desired_mapped;
};

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	struct role roles[ROLE_COUNT];
	struct role *focus_role;
	char token[64];
	unsigned key_count[ROLE_COUNT];
	bool armed;
	bool running;
};

static size_t role_index(const struct client *client, const struct role *role) {
	return (size_t)(role - client->roles);
}

static struct role *role_for_window(struct client *client, xcb_window_t window) {
	for (size_t i = 0; i < ROLE_COUNT; ++i) {
		if (client->roles[i].window == window) return &client->roles[i];
	}
	return NULL;
}

static struct role *role_named(struct client *client, const char *name) {
	for (size_t i = 0; i < ROLE_COUNT; ++i) {
		if (strcmp(client->roles[i].name, name) == 0) return &client->roles[i];
	}
	return NULL;
}

static void set_string(struct client *client, xcb_window_t window,
		xcb_atom_t property, const char *value) {
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, window,
		property, XCB_ATOM_STRING, 8, (uint32_t)strlen(value), value);
}

static void set_class(struct client *client, struct role *role) {
	char value[128];
	size_t instance_length = strlen(role->instance) + 1;
	size_t class_length = strlen(role->class_name) + 1;
	if (instance_length + class_length > sizeof(value)) abort();
	memcpy(value, role->instance, instance_length);
	memcpy(value + instance_length, role->class_name, class_length);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, role->window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8,
		(uint32_t)(instance_length + class_length), value);
}

static bool repaint_role(struct client *client, struct role *role) {
	if (!role->desired_mapped) return false;
	uint32_t color = role->paint_alternate ?
		role->alternate_color : role->primary_color;
	role->paint_alternate = !role->paint_alternate;
	xcb_change_window_attributes(client->connection, role->window,
		XCB_CW_BACK_PIXEL, &color);
	xcb_clear_area(client->connection, false, role->window, 0, 0, 0, 0);
	return true;
}

static void map_role(struct client *client, struct role *role) {
	role->desired_mapped = true;
	xcb_map_window(client->connection, role->window);
	(void)repaint_role(client, role);
	xcb_flush(client->connection);
}

static void repaint_mapped_roles(struct client *client) {
	bool sent = false;
	for (size_t i = 0; i < ROLE_COUNT; ++i)
		sent |= repaint_role(client, &client->roles[i]);
	if (sent) xcb_flush(client->connection);
}

static void stop_repainting(struct client *client) {
	for (size_t i = 0; i < ROLE_COUNT; ++i)
		client->roles[i].desired_mapped = false;
}

static bool initialize_role(struct client *client, enum role_index index,
		const char *name, const char *title, const char *instance,
		const char *class_name, uint32_t primary_color,
		uint32_t alternate_color) {
	struct role *role = &client->roles[index];
	*role = (struct role){
		.name = name,
		.title = title,
		.instance = instance,
		.class_name = class_name,
		.primary_color = primary_color,
		.alternate_color = alternate_color,
		.window = xcb_generate_id(client->connection),
	};
	uint32_t values[] = {
		primary_color,
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_EXPOSURE |
			XCB_EVENT_MASK_FOCUS_CHANGE | XCB_EVENT_MASK_KEY_PRESS |
			XCB_EVENT_MASK_KEY_RELEASE,
	};
	xcb_void_cookie_t cookie = xcb_create_window_checked(client->connection,
		XCB_COPY_FROM_PARENT, role->window, client->screen->root,
		80 + (int16_t)index * 40, 80 + (int16_t)index * 40, 180, 120, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
	xcb_generic_error_t *error = xcb_request_check(client->connection, cookie);
	if (error != NULL) {
		free(error);
		return false;
	}
	set_string(client, role->window, XCB_ATOM_WM_NAME, role->title);
	set_class(client, role);
	map_role(client, role);
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
	if (client->screen == NULL) return false;
	return initialize_role(client, ROLE_X11_A, "x11-a", "wtwm-mixed-x11-a",
			"wtwm-mixed-x11-a", "WtwmMixedX11A",
			UINT32_C(0x0060a040), UINT32_C(0x0060c060)) &&
		initialize_role(client, ROLE_X11_B, "x11-b", "wtwm-mixed-x11-b",
			"wtwm-mixed-x11-b", "WtwmMixedX11B",
			UINT32_C(0x00a04080), UINT32_C(0x00c060a0));
}

static void handle_event(struct client *client, xcb_generic_event_t *event) {
	uint8_t type = event->response_type & UINT8_C(0x7f);
	if (type == XCB_EXPOSE) {
		const xcb_expose_event_t *expose = (const xcb_expose_event_t *)event;
		struct role *role = role_for_window(client, expose->window);
		if (role != NULL && expose->count == 0 && repaint_role(client, role))
			xcb_flush(client->connection);
		return;
	}
	if (type == XCB_FOCUS_IN) {
		const xcb_focus_in_event_t *focus = (const xcb_focus_in_event_t *)event;
		client->focus_role = role_for_window(client, focus->event);
		if (client->armed && client->focus_role != NULL)
			printf("EVENT ENTER %s %s\n", client->token,
				client->focus_role->name);
		return;
	}
	if (type == XCB_FOCUS_OUT) {
		const xcb_focus_out_event_t *focus = (const xcb_focus_out_event_t *)event;
		struct role *role = role_for_window(client, focus->event);
		if (client->armed && role != NULL)
			printf("EVENT LEAVE %s %s\n", client->token, role->name);
		if (client->focus_role == role) client->focus_role = NULL;
		return;
	}
	if (type == XCB_KEY_PRESS || type == XCB_KEY_RELEASE) {
		const xcb_key_press_event_t *key = (const xcb_key_press_event_t *)event;
		struct role *role = role_for_window(client, key->event);
		if (!client->armed || role == NULL) return;
		client->key_count[role_index(client, role)]++;
		uint32_t evdev_key = key->detail >= 8 ? key->detail - 8 : key->detail;
		printf("EVENT KEY %s %s %" PRIu32 " %s\n", client->token,
			role->name, evdev_key,
			type == XCB_KEY_PRESS ? "press" : "release");
	}
}

static void drain_events(struct client *client) {
	xcb_generic_event_t *event;
	while ((event = xcb_poll_for_event(client->connection)) != NULL) {
		handle_event(client, event);
		free(event);
	}
}

static bool roundtrip(struct client *client, xcb_window_t *focus_window) {
	xcb_get_input_focus_cookie_t cookie = xcb_get_input_focus(client->connection);
	xcb_get_input_focus_reply_t *reply =
		xcb_get_input_focus_reply(client->connection, cookie, NULL);
	if (reply == NULL) return false;
	if (focus_window != NULL) *focus_window = reply->focus;
	free(reply);
	drain_events(client);
	return xcb_connection_has_error(client->connection) == 0;
}

static bool handle_command(struct client *client, char *command) {
	char name[64];
	if (sscanf(command, "ARM %63s", name) == 1) {
		if (!roundtrip(client, NULL)) return false;
		strcpy(client->token, name);
		memset(client->key_count, 0, sizeof(client->key_count));
		client->armed = true;
		printf("OK ARMED %s\n", client->token);
		return true;
	}
	if (sscanf(command, "REPORT %63s", name) == 1) {
		xcb_window_t focus_window = XCB_WINDOW_NONE;
		if (strcmp(name, client->token) != 0 ||
				!roundtrip(client, &focus_window)) return false;
		struct role *focus = role_for_window(client, focus_window);
		printf("OK REPORT %s x11-a=%u x11-b=%u focus=%s\n", client->token,
			client->key_count[ROLE_X11_A], client->key_count[ROLE_X11_B],
			focus != NULL ? focus->name : "none");
		return true;
	}
	if (sscanf(command, "UNMAP %63s", name) == 1) {
		struct role *role = role_named(client, name);
		if (role == NULL || !role->desired_mapped) return false;
		role->desired_mapped = false;
		xcb_unmap_window(client->connection, role->window);
		xcb_flush(client->connection);
		printf("OK UNMAPPED %s\n", role->name);
		return true;
	}
	if (sscanf(command, "REMAP %63s", name) == 1) {
		struct role *role = role_named(client, name);
		if (role == NULL || role->desired_mapped) return false;
		map_role(client, role);
		printf("OK REMAPPED %s\n", role->name);
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		stop_repainting(client);
		puts("OK EXIT");
		client->running = false;
		return true;
	}
	fprintf(stderr, "unknown mixed X11 command: %s\n", command);
	return false;
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {.running = true};
	if (!initialize(&client)) {
		fprintf(stderr, "mixed X11 client: initialization failed\n");
		if (client.connection != NULL) xcb_disconnect(client.connection);
		return EXIT_FAILURE;
	}
	puts("OK READY x11-a x11-b");

	char command[128];
	while (client.running) {
		drain_events(&client);
		struct pollfd descriptors[] = {
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, 100);
		while (result < 0 && errno == EINTR);
		if (result < 0) break;
		if ((descriptors[0].revents & (POLLIN | POLLERR | POLLHUP)) != 0)
			drain_events(&client);
		if ((descriptors[1].revents & (POLLIN | POLLHUP)) != 0) {
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (!handle_command(&client, command)) break;
		}
		repaint_mapped_roles(&client);
		if (xcb_connection_has_error(client.connection) != 0) break;
	}

	for (size_t i = 0; i < ROLE_COUNT; ++i)
		xcb_destroy_window(client.connection, client.roles[i].window);
	xcb_flush(client.connection);
	xcb_disconnect(client.connection);
	return client.running ? EXIT_FAILURE : EXIT_SUCCESS;
}
