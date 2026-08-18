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
#include <time.h>
#include <unistd.h>
#include <xcb/xcb.h>

enum pending_request {
	PENDING_NONE,
	PENDING_CLIPBOARD_DATA,
	PENDING_PRIMARY_DATA,
	PENDING_CLIPBOARD_TARGETS,
	PENDING_PRIMARY_TARGETS,
};

struct client {
	xcb_connection_t *connection;
	xcb_screen_t *screen;
	xcb_window_t window;
	xcb_atom_t clipboard;
	xcb_atom_t primary;
	xcb_atom_t targets;
	xcb_atom_t utf8;
	xcb_atom_t text;
	xcb_atom_t result_property;
	xcb_atom_t cut_buffer0;
	enum pending_request pending;
	bool pending_hex;
	bool owns_clipboard;
	bool owns_primary;
	bool running;
	uint32_t repaint;
	unsigned clipboard_targets_served;
	unsigned primary_targets_served;
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

static const char *selection_name(struct client *client, xcb_atom_t selection) {
	return selection == client->clipboard ? "CLIPBOARD" : "PRIMARY";
}

static const char *selection_payload(struct client *client,
	xcb_atom_t selection) {
	(void)client;
	return selection == client->clipboard ? "x11-clipboard" : "x11-primary";
}

static void print_hex(const void *value, size_t length) {
	const unsigned char *bytes = value;
	for (size_t i = 0; i < length; ++i) printf("%02x", bytes[i]);
}

static void send_selection_notify(struct client *client,
	const xcb_selection_request_event_t *request, xcb_atom_t property) {
	xcb_selection_notify_event_t notify = {
		.response_type = XCB_SELECTION_NOTIFY,
		.time = request->time,
		.requestor = request->requestor,
		.selection = request->selection,
		.target = request->target,
		.property = property,
	};
	xcb_send_event(client->connection, false, request->requestor,
		XCB_EVENT_MASK_NO_EVENT, (const char *)&notify);
	xcb_flush(client->connection);
}

static void handle_selection_request(struct client *client,
	const xcb_selection_request_event_t *request) {
	xcb_atom_t property = request->property == XCB_ATOM_NONE ?
		request->target : request->property;
	bool owns = request->selection == client->clipboard ?
		client->owns_clipboard : client->owns_primary;
	if (!owns) {
		send_selection_notify(client, request, XCB_ATOM_NONE);
		return;
	}
	if (request->target == client->targets) {
		if (request->selection == client->clipboard)
			client->clipboard_targets_served++;
		else
			client->primary_targets_served++;
		xcb_atom_t values[] = {client->targets, client->utf8, client->text};
		xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
			request->requestor, property, XCB_ATOM_ATOM, 32,
			(uint32_t)(sizeof(values) / sizeof(values[0])), values);
	} else if (request->target == client->utf8 ||
			request->target == client->text) {
		const char *payload = selection_payload(client, request->selection);
		xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
			request->requestor, property, request->target, 8,
			(uint32_t)strlen(payload), payload);
	} else {
		send_selection_notify(client, request, XCB_ATOM_NONE);
		return;
	}
	send_selection_notify(client, request, property);
}

static void print_selection_data(struct client *client,
	const xcb_selection_notify_event_t *notify) {
	const char *name = selection_name(client, notify->selection);
	if (notify->property == XCB_ATOM_NONE) {
		printf("ERROR %s conversion\n", name);
		client->pending = PENDING_NONE;
		client->pending_hex = false;
		fflush(stdout);
		return;
	}
	xcb_get_property_cookie_t cookie = xcb_get_property(client->connection, true,
		notify->requestor, notify->property, XCB_GET_PROPERTY_TYPE_ANY, 0, 4096);
	xcb_get_property_reply_t *reply =
		xcb_get_property_reply(client->connection, cookie, NULL);
	if (reply == NULL) {
		printf("ERROR %s property\n", name);
		client->pending = PENDING_NONE;
		client->pending_hex = false;
		fflush(stdout);
		return;
	}
	if (client->pending == PENDING_CLIPBOARD_TARGETS ||
			client->pending == PENDING_PRIMARY_TARGETS) {
		bool has_utf8 = false;
		bool has_text = false;
		if (reply->type == XCB_ATOM_ATOM && reply->format == 32) {
			const xcb_atom_t *values = xcb_get_property_value(reply);
			for (uint32_t i = 0; i < reply->value_len; ++i) {
				if (values[i] == client->utf8) has_utf8 = true;
				if (values[i] == client->text) has_text = true;
			}
		}
		printf("TARGETS %s utf8=%d text=%d\n", name, has_utf8, has_text);
	} else if (reply->format == 8 && client->pending_hex) {
		int length = xcb_get_property_value_length(reply);
		printf("DATAHEX %s len=%d hex=", name, length);
		print_hex(xcb_get_property_value(reply), (size_t)length);
		putchar('\n');
	} else if (reply->format == 8) {
		int length = xcb_get_property_value_length(reply);
		printf("DATA %s %.*s\n", name, length,
			(const char *)xcb_get_property_value(reply));
	} else {
		printf("ERROR %s format\n", name);
	}
	free(reply);
	client->pending = PENDING_NONE;
	client->pending_hex = false;
	fflush(stdout);
}

static void handle_x_event(struct client *client, xcb_generic_event_t *event) {
	uint8_t type = event->response_type & UINT8_C(0x7f);
	if (type == XCB_SELECTION_REQUEST) {
		handle_selection_request(client,
			(const xcb_selection_request_event_t *)event);
	} else if (type == XCB_SELECTION_NOTIFY) {
		print_selection_data(client,
			(const xcb_selection_notify_event_t *)event);
	} else if (type == XCB_SELECTION_CLEAR) {
		const xcb_selection_clear_event_t *clear =
			(const xcb_selection_clear_event_t *)event;
		if (clear->selection == client->clipboard) client->owns_clipboard = false;
		if (clear->selection == client->primary) client->owns_primary = false;
	}
}

static bool input_focus_is_window(struct client *client) {
	xcb_get_input_focus_cookie_t cookie = xcb_get_input_focus(client->connection);
	xcb_get_input_focus_reply_t *reply =
		xcb_get_input_focus_reply(client->connection, cookie, NULL);
	bool focused = reply != NULL && reply->focus == client->window;
	free(reply);
	return focused;
}

static bool wait_for_input_focus(struct client *client) {
	struct timespec deadline;
	if (clock_gettime(CLOCK_MONOTONIC, &deadline) < 0) return false;
	deadline.tv_sec += 10;
	for (;;) {
		xcb_generic_event_t *event;
		while ((event = xcb_poll_for_event(client->connection)) != NULL) {
			handle_x_event(client, event);
			free(event);
		}
		if (input_focus_is_window(client)) return true;
		struct timespec now;
		if (clock_gettime(CLOCK_MONOTONIC, &now) < 0) return false;
		int64_t remaining = (int64_t)(deadline.tv_sec - now.tv_sec) * 1000 +
			(deadline.tv_nsec - now.tv_nsec) / 1000000;
		if (remaining <= 0) return false;
		struct pollfd descriptor = {
			.fd = xcb_get_file_descriptor(client->connection),
			.events = POLLIN,
		};
		int result;
		do result = poll(&descriptor, 1, (int)remaining);
		while (result < 0 && errno == EINTR);
		if (result <= 0 || (descriptor.revents & (POLLERR | POLLHUP)) != 0)
			return false;
	}
}

static void own_selection(struct client *client, xcb_atom_t selection) {
	xcb_set_selection_owner(client->connection, client->window, selection,
		XCB_TIME_CURRENT_TIME);
	xcb_flush(client->connection);
	xcb_get_selection_owner_cookie_t cookie =
		xcb_get_selection_owner(client->connection, selection);
	xcb_get_selection_owner_reply_t *reply =
		xcb_get_selection_owner_reply(client->connection, cookie, NULL);
	bool owned = reply != NULL && reply->owner == client->window;
	free(reply);
	if (selection == client->clipboard) client->owns_clipboard = owned;
	else client->owns_primary = owned;
	printf("OWN %s %d\n", selection_name(client, selection), owned);
}

static const char *owner_status(struct client *client, xcb_atom_t selection) {
	xcb_get_selection_owner_cookie_t cookie =
		xcb_get_selection_owner(client->connection, selection);
	xcb_get_selection_owner_reply_t *reply =
		xcb_get_selection_owner_reply(client->connection, cookie, NULL);
	const char *status = "none";
	if (reply != NULL && reply->owner != XCB_WINDOW_NONE)
		status = reply->owner == client->window ? "self" : "other";
	free(reply);
	return status;
}

static bool proxy_owners_ready(struct client *client) {
	xcb_get_selection_owner_cookie_t clipboard_cookie =
		xcb_get_selection_owner(client->connection, client->clipboard);
	xcb_get_selection_owner_cookie_t primary_cookie =
		xcb_get_selection_owner(client->connection, client->primary);
	xcb_get_selection_owner_reply_t *clipboard =
		xcb_get_selection_owner_reply(client->connection, clipboard_cookie, NULL);
	xcb_get_selection_owner_reply_t *primary =
		xcb_get_selection_owner_reply(client->connection, primary_cookie, NULL);
	bool ready = clipboard != NULL && primary != NULL &&
		clipboard->owner != XCB_WINDOW_NONE && clipboard->owner != client->window &&
		primary->owner != XCB_WINDOW_NONE && primary->owner != client->window;
	free(clipboard);
	free(primary);
	return ready;
}

static bool wait_for_bridge_ready(struct client *client) {
	struct timespec deadline;
	if (clock_gettime(CLOCK_MONOTONIC, &deadline) < 0) return false;
	deadline.tv_sec += 10;
	for (;;) {
		xcb_generic_event_t *event;
		while ((event = xcb_poll_for_event(client->connection)) != NULL) {
			handle_x_event(client, event);
			free(event);
		}
		if (xcb_connection_has_error(client->connection)) return false;
		if (input_focus_is_window(client) && proxy_owners_ready(client)) return true;
		struct timespec now;
		if (clock_gettime(CLOCK_MONOTONIC, &now) < 0) return false;
		int64_t remaining = (int64_t)(deadline.tv_sec - now.tv_sec) * 1000 +
			(deadline.tv_nsec - now.tv_nsec) / 1000000;
		if (remaining <= 0) return false;
		struct pollfd descriptor = {
			.fd = xcb_get_file_descriptor(client->connection),
			.events = POLLIN,
		};
		int timeout = remaining < 10 ? (int)remaining : 10;
		int result;
		do result = poll(&descriptor, 1, timeout);
		while (result < 0 && errno == EINTR);
		if (result < 0 || (descriptor.revents & (POLLERR | POLLHUP)) != 0)
			return false;
	}
}

static void request_selection(struct client *client, xcb_atom_t selection,
	bool request_targets, bool hex) {
	if (client->pending != PENDING_NONE) {
		printf("ERROR pending\n");
		return;
	}
	client->pending_hex = hex;
	if (selection == client->clipboard) {
		client->pending = request_targets ? PENDING_CLIPBOARD_TARGETS :
			PENDING_CLIPBOARD_DATA;
	} else {
		client->pending = request_targets ? PENDING_PRIMARY_TARGETS :
			PENDING_PRIMARY_DATA;
	}
	xcb_convert_selection(client->connection, client->window, selection,
		request_targets ? client->targets : client->utf8,
		client->result_property, XCB_TIME_CURRENT_TIME);
	xcb_flush(client->connection);
}

static int hex_value(char character) {
	if (character >= '0' && character <= '9') return character - '0';
	if (character >= 'a' && character <= 'f') return character - 'a' + 10;
	if (character >= 'A' && character <= 'F') return character - 'A' + 10;
	return -1;
}

static bool decode_hex(const char *text, unsigned char *bytes,
	size_t capacity, size_t *length_out) {
	size_t length = strlen(text);
	if ((length & 1) != 0 || length / 2 > capacity) return false;
	for (size_t i = 0; i < length / 2; ++i) {
		int high = hex_value(text[i * 2]);
		int low = hex_value(text[i * 2 + 1]);
		if (high < 0 || low < 0) return false;
		bytes[i] = (unsigned char)((high << 4) | low);
	}
	*length_out = length / 2;
	return true;
}

static void set_cut_buffer(struct client *client, const char *hex) {
	unsigned char bytes[4096];
	size_t length = 0;
	if (!decode_hex(hex, bytes, sizeof(bytes), &length)) {
		printf("ERROR CUTBUFFER hex\n");
		return;
	}
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE,
		client->screen->root, client->cut_buffer0, XCB_ATOM_STRING, 8,
		(uint32_t)length, bytes);
	xcb_flush(client->connection);
	printf("CUTBUFFER SET len=%zu\n", length);
}

static void get_cut_buffer(struct client *client) {
	xcb_get_property_cookie_t cookie = xcb_get_property(client->connection,
		false, client->screen->root, client->cut_buffer0,
		XCB_GET_PROPERTY_TYPE_ANY, 0, 4096);
	xcb_get_property_reply_t *reply =
		xcb_get_property_reply(client->connection, cookie, NULL);
	if (reply == NULL) {
		printf("ERROR CUTBUFFER property\n");
		return;
	}
	int length = xcb_get_property_value_length(reply);
	const char *type = reply->type == XCB_ATOM_STRING ? "STRING" :
		(reply->type == XCB_ATOM_NONE ? "NONE" : "OTHER");
	printf("CUTBUFFER type=%s format=%u len=%d hex=", type, reply->format,
		length);
	print_hex(xcb_get_property_value(reply), (size_t)length);
	putchar('\n');
	free(reply);
}

static void handle_command(struct client *client, char *command) {
	command[strcspn(command, "\r\n")] = '\0';
	if (strcmp(command, "OWN CLIPBOARD") == 0) {
		own_selection(client, client->clipboard);
	} else if (strcmp(command, "OWN PRIMARY") == 0) {
		own_selection(client, client->primary);
	} else if (strcmp(command, "GET CLIPBOARD") == 0) {
		request_selection(client, client->clipboard, false, false);
	} else if (strcmp(command, "GET PRIMARY") == 0) {
		request_selection(client, client->primary, false, false);
	} else if (strcmp(command, "GETHEX CLIPBOARD") == 0) {
		request_selection(client, client->clipboard, false, true);
	} else if (strcmp(command, "GETHEX PRIMARY") == 0) {
		request_selection(client, client->primary, false, true);
	} else if (strcmp(command, "TARGETS CLIPBOARD") == 0) {
		request_selection(client, client->clipboard, true, false);
	} else if (strcmp(command, "TARGETS PRIMARY") == 0) {
		request_selection(client, client->primary, true, false);
	} else if (strncmp(command, "SET CUTBUFFER ", 14) == 0) {
		set_cut_buffer(client, command + 14);
	} else if (strcmp(command, "GET CUTBUFFER") == 0) {
		get_cut_buffer(client);
	} else if (strcmp(command, "STATUS") == 0) {
		const char *clipboard = owner_status(client, client->clipboard);
		const char *primary = owner_status(client, client->primary);
		printf("STATUS clipboard=%s primary=%s\n", clipboard, primary);
	} else if (strcmp(command, "WAIT FOCUS") == 0) {
		printf(wait_for_input_focus(client) ? "FOCUS 1\n" : "ERROR FOCUS timeout\n");
	} else if (strcmp(command, "WAIT BRIDGE") == 0) {
		if (wait_for_bridge_ready(client))
			printf("BRIDGE focus=1 clipboard=other primary=other\n");
		else
			printf("ERROR BRIDGE timeout\n");
	} else if (strcmp(command, "SERVED") == 0) {
		printf("SERVED clipboard=%u primary=%u\n",
			client->clipboard_targets_served, client->primary_targets_served);
	} else if (strcmp(command, "EXIT") == 0) {
		printf("EXITING\n");
		client->running = false;
	} else {
		printf("ERROR command\n");
	}
	fflush(stdout);
}

static bool initialize(struct client *client) {
	int screen_number = 0;
	client->connection = xcb_connect(NULL, &screen_number);
	if (xcb_connection_has_error(client->connection)) return false;
	const xcb_setup_t *setup = xcb_get_setup(client->connection);
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(setup);
	for (int i = 0; i < screen_number; ++i) xcb_screen_next(&screens);
	client->screen = screens.data;
	if (client->screen == NULL) return false;
	client->clipboard = atom(client, "CLIPBOARD");
	client->primary = XCB_ATOM_PRIMARY;
	client->targets = atom(client, "TARGETS");
	client->utf8 = atom(client, "UTF8_STRING");
	client->text = atom(client, "TEXT");
	client->cut_buffer0 = atom(client, "CUT_BUFFER0");
	client->result_property = atom(client, "_WTWM_SELECTION_RESULT");
	if (client->clipboard == XCB_ATOM_NONE || client->targets == XCB_ATOM_NONE ||
			client->utf8 == XCB_ATOM_NONE || client->text == XCB_ATOM_NONE ||
			client->result_property == XCB_ATOM_NONE ||
			client->cut_buffer0 == XCB_ATOM_NONE) return false;
	client->window = xcb_generate_id(client->connection);
	uint32_t values[] = {
		UINT32_C(0x806020),
		XCB_EVENT_MASK_STRUCTURE_NOTIFY | XCB_EVENT_MASK_PROPERTY_CHANGE |
			XCB_EVENT_MASK_FOCUS_CHANGE,
	};
	xcb_create_window(client->connection, XCB_COPY_FROM_PARENT, client->window,
		client->screen->root, 360, 80, 180, 100, 0,
		XCB_WINDOW_CLASS_INPUT_OUTPUT, client->screen->root_visual,
		XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
	const char title[] = "wtwm-selection-x11";
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->window,
		XCB_ATOM_WM_NAME, XCB_ATOM_STRING, 8, sizeof(title) - 1, title);
	const char wm_class[] = "wtwm-selection\0WtwmSelection\0";
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->window,
		XCB_ATOM_WM_CLASS, XCB_ATOM_STRING, 8, sizeof(wm_class) - 1, wm_class);
	xcb_atom_t wm_hints = atom(client, "WM_HINTS");
	uint32_t hints[9] = {1, 1};
	xcb_change_property(client->connection, XCB_PROP_MODE_REPLACE, client->window,
		wm_hints, wm_hints, 32, 9, hints);
	xcb_map_window(client->connection, client->window);
	xcb_flush(client->connection);
	return true;
}

static void repaint(struct client *client) {
	client->repaint++;
	uint32_t color = (client->repaint & 1) != 0 ?
		UINT32_C(0x806020) : UINT32_C(0x806040);
	xcb_change_window_attributes(client->connection, client->window,
		XCB_CW_BACK_PIXEL, &color);
	xcb_clear_area(client->connection, false, client->window, 0, 0, 180, 100);
	xcb_flush(client->connection);
}

int main(void) {
	struct client client = {.running = true};
	if (!initialize(&client)) {
		fprintf(stderr, "failed to initialize selection X11 client\n");
		if (client.connection != NULL) xcb_disconnect(client.connection);
		return EXIT_FAILURE;
	}
	printf("READY %" PRIu32 "\n", client.window);
	fflush(stdout);
	while (client.running && !xcb_connection_has_error(client.connection)) {
		struct pollfd descriptors[2] = {
			{.fd = xcb_get_file_descriptor(client.connection), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, 20); while (result < 0 && errno == EINTR);
		if (result < 0) break;
		xcb_generic_event_t *event;
		while ((event = xcb_poll_for_event(client.connection)) != NULL) {
			handle_x_event(&client, event);
			free(event);
		}
		if ((descriptors[1].revents & POLLIN) != 0) {
			char command[16384];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			handle_command(&client, command);
		}
		repaint(&client);
	}
	xcb_destroy_window(client.connection, client.window);
	xcb_flush(client.connection);
	xcb_disconnect(client.connection);
	return EXIT_SUCCESS;
}
