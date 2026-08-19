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

#define FIXED_REPAINT_COLOR UINT32_C(0x007030a0)

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_window_t window;
	xcb_atom_t wm_protocols;
	xcb_atom_t wm_delete_window;
	char title[128];
	const char *instance;
	const char *class_name;
	unsigned close_count;
	unsigned cycle;
	bool animate;
	bool alternate;
	bool desired_mapped;
	bool running;
};

static xcb_atom_t intern_atom(xcb_connection_t *connection, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(connection, false,
		(uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(connection, cookie,
		NULL);
	if (reply == NULL) return XCB_ATOM_NONE;
	xcb_atom_t atom = reply->atom;
	free(reply);
	return atom;
}

static void set_string(struct client *client, xcb_atom_t property,
		const char *value) {
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
		client->window, property, XCB_ATOM_STRING, 8,
		(uint32_t)strlen(value), value);
}

static bool set_class(struct client *client) {
	char value[192];
	size_t instance_length = strlen(client->instance) + 1;
	size_t class_length = strlen(client->class_name) + 1;
	if (instance_length + class_length > sizeof(value)) return false;
	memcpy(value, client->instance, instance_length);
	memcpy(value + instance_length, client->class_name, class_length);
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
		client->window, XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8,
		(uint32_t)(instance_length + class_length), value);
	return true;
}

static bool roundtrip(struct client *client) {
	xcb_get_input_focus_cookie_t cookie =
		xcb_get_input_focus(client->connection);
	xcb_get_input_focus_reply_t *reply =
		xcb_get_input_focus_reply(client->connection, cookie, NULL);
	if (reply == NULL) return false;
	free(reply);
	return xcb_connection_has_error(client->connection) == 0;
}

static bool repaint(struct client *client) {
	if (!client->desired_mapped) return false;
	uint32_t color = FIXED_REPAINT_COLOR;
	if (client->animate) {
		color = client->alternate ?
			UINT32_C(0x00b05070) : FIXED_REPAINT_COLOR;
		client->alternate = !client->alternate;
	}
	xcb_change_window_attributes(client->connection, client->window,
		XCB_CW_BACK_PIXEL, &color);
	xcb_clear_area(client->connection, false, client->window, 0, 0, 0, 0);
	return true;
}

static bool map_client(struct client *client) {
	client->desired_mapped = true;
	xcb_map_window(client->connection, client->window);
	(void)repaint(client);
	xcb_flush(client->connection);
	return roundtrip(client);
}

static bool unmap_client(struct client *client) {
	client->desired_mapped = false;
	xcb_unmap_window(client->connection, client->window);
	xcb_flush(client->connection);
	return roundtrip(client);
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (client->connection == NULL ||
			xcb_connection_has_error(client->connection) != 0) return false;
	xcb_screen_iterator_t screens =
		xcb_setup_roots_iterator(xcb_get_setup(client->connection));
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	if (client->screen == NULL) return false;
	client->wm_protocols = intern_atom(client->connection, "WM_PROTOCOLS");
	client->wm_delete_window = intern_atom(client->connection,
		"WM_DELETE_WINDOW");
	if (client->wm_protocols == XCB_ATOM_NONE ||
			client->wm_delete_window == XCB_ATOM_NONE) return false;

	client->window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		UINT32_C(0x007030a0),
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_EXPOSURE |
			XCB_EVENT_MASK_FOCUS_CHANGE | XCB_EVENT_MASK_KEY_PRESS |
			XCB_EVENT_MASK_KEY_RELEASE,
	};
	xcb_void_cookie_t cookie = xcb_create_window_checked(client->connection,
		XCB_COPY_FROM_PARENT, client->window, client->screen->root,
		80, 80, 180, 120, 0, XCB_WINDOW_CLASS_INPUT_OUTPUT,
		client->screen->root_visual, XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK,
		values);
	xcb_generic_error_t *error = xcb_request_check(client->connection, cookie);
	if (error != NULL) {
		free(error);
		return false;
	}
	set_string(client, XCB_ATOM_WM_NAME, client->title);
	if (!set_class(client)) return false;
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
		client->window, client->wm_protocols, XCB_ATOM_ATOM, 32, 1,
		&client->wm_delete_window);
	return map_client(client);
}

static void handle_event(struct client *client, xcb_generic_event_t *event) {
	uint8_t type = event->response_type & UINT8_C(0x7f);
	if (type == XCB_EXPOSE) {
		const xcb_expose_event_t *expose = (const xcb_expose_event_t *)event;
		if (expose->window == client->window && expose->count == 0 &&
				repaint(client)) xcb_flush(client->connection);
		return;
	}
	if (type != XCB_CLIENT_MESSAGE) return;
	const xcb_client_message_event_t *message =
		(const xcb_client_message_event_t *)event;
	if (message->window != client->window ||
			message->type != client->wm_protocols ||
			message->format != 32 ||
			message->data.data32[0] != client->wm_delete_window) return;
	client->close_count++;
	printf("EVENT DELETE %u\n", client->close_count);
}

static void drain_events(struct client *client) {
	xcb_generic_event_t *event;
	while ((event = xcb_poll_for_event(client->connection)) != NULL) {
		handle_event(client, event);
		free(event);
	}
}

static bool handle_command(struct client *client, char *command) {
	char title[128];
	unsigned cycle;
	if (sscanf(command, "TITLE %127s", title) == 1) {
		if (!client->desired_mapped) return false;
		strcpy(client->title, title);
		set_string(client, XCB_ATOM_WM_NAME, client->title);
		xcb_flush(client->connection);
		if (!roundtrip(client)) return false;
		printf("OK TITLE %s\n", client->title);
		return true;
	}
	if (sscanf(command, "UNMAP %u", &cycle) == 1) {
		if (!client->desired_mapped || cycle != client->cycle + 1 ||
				!unmap_client(client)) return false;
		client->cycle = cycle;
		printf("OK UNMAPPED %u\n", cycle);
		return true;
	}
	if (sscanf(command, "REMAP %u", &cycle) == 1) {
		if (client->desired_mapped || cycle != client->cycle ||
				!map_client(client)) return false;
		printf("OK REMAPPED %u\n", cycle);
		return true;
	}
	if (strcmp(command, "REPORT") == 0) {
		if (!roundtrip(client)) return false;
		printf("OK REPORT close=%u mapped=%d cycle=%u\n",
			client->close_count, client->desired_mapped, client->cycle);
		return true;
	}
	if (strcmp(command, "FREEZE") == 0) {
		if (!client->desired_mapped) return false;
		client->animate = false;
		if (!repaint(client)) return false;
		xcb_flush(client->connection);
		if (!roundtrip(client)) return false;
		puts("OK FROZEN 0x007030a0");
		return true;
	}
	if (strcmp(command, "CRASH") == 0) {
		puts("OK CRASH");
		abort();
	}
	if (strcmp(command, "HANG") == 0) {
		puts("OK HANG");
		for (;;) pause();
	}
	if (strcmp(command, "EXIT") == 0) {
		client->desired_mapped = false;
		puts("OK EXIT");
		client->running = false;
		return true;
	}
	fprintf(stderr, "unknown stress X11 command: %s\n", command);
	return false;
}

int main(int argc, char **argv) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	if (argc != 4) {
		fprintf(stderr, "usage: %s TITLE INSTANCE CLASS\n", argv[0]);
		return EXIT_FAILURE;
	}
	struct client client = {
		.instance = argv[2],
		.class_name = argv[3],
		.animate = true,
		.running = true,
	};
	(void)snprintf(client.title, sizeof(client.title), "%s", argv[1]);
	if (!initialize(&client)) {
		fprintf(stderr, "stress X11 client: initialization failed\n");
		if (client.connection != NULL) xcb_disconnect(client.connection);
		return EXIT_FAILURE;
	}
	printf("OK READY %s %" PRIu32 "\n", client.title, client.window);

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
		if (client.animate && repaint(&client)) xcb_flush(client.connection);
		if (xcb_connection_has_error(client.connection) != 0) break;
	}

	if (xcb_connection_has_error(client.connection) == 0) {
		xcb_destroy_window(client.connection, client.window);
		xcb_flush(client.connection);
	}
	xcb_disconnect(client.connection);
	return client.running ? EXIT_FAILURE : EXIT_SUCCESS;
}
