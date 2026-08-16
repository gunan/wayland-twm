/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "primary-selection-unstable-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>

#define MIME_UTF8 "text/plain;charset=utf-8"
#define MIME_TEXT "text/plain"

struct client;

struct clipboard_offer {
	struct wl_data_offer *proxy;
	bool utf8;
	bool text;
};

struct primary_offer {
	struct zwp_primary_selection_offer_v1 *proxy;
	bool utf8;
	bool text;
};

struct clipboard_source {
	struct client *client;
	struct wl_data_source *proxy;
	const char *payload;
};

struct primary_source {
	struct client *client;
	struct zwp_primary_selection_source_v1 *proxy;
	const char *payload;
};

struct client {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct wl_seat *seat;
	struct wl_keyboard *keyboard;
	struct wl_data_device_manager *data_manager;
	struct wl_data_device *data_device;
	struct zwp_primary_selection_device_manager_v1 *primary_manager;
	struct zwp_primary_selection_device_v1 *primary_device;
	struct xdg_wm_base *wm_base;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	struct clipboard_offer *clipboard_offer;
	struct primary_offer *primary_offer;
	struct clipboard_source *clipboard_source;
	struct primary_source *primary_source;
	uint32_t serial;
	unsigned clipboard_cancellations;
	unsigned primary_cancellations;
	bool mapped;
	bool running;
};

static void write_all(int fd, const char *payload) {
	size_t length = strlen(payload);
	size_t offset = 0;
	while (offset < length) {
		ssize_t written = write(fd, payload + offset, length - offset);
		if (written > 0) {
			offset += (size_t)written;
			continue;
		}
		if (written < 0 && errno == EINTR) continue;
		break;
	}
}

static void destroy_clipboard_offer(struct clipboard_offer **offer_ptr) {
	struct clipboard_offer *offer = *offer_ptr;
	if (offer == NULL) return;
	wl_data_offer_destroy(offer->proxy);
	free(offer);
	*offer_ptr = NULL;
}

static void destroy_primary_offer(struct primary_offer **offer_ptr) {
	struct primary_offer *offer = *offer_ptr;
	if (offer == NULL) return;
	zwp_primary_selection_offer_v1_destroy(offer->proxy);
	free(offer);
	*offer_ptr = NULL;
}

static void clipboard_offer_mime(void *data, struct wl_data_offer *proxy,
	const char *mime_type) {
	(void)proxy;
	struct clipboard_offer *offer = data;
	if (strcmp(mime_type, MIME_UTF8) == 0) offer->utf8 = true;
	if (strcmp(mime_type, MIME_TEXT) == 0) offer->text = true;
}

static void clipboard_offer_source_actions(void *data,
	struct wl_data_offer *proxy, uint32_t actions) {
	(void)data;
	(void)proxy;
	(void)actions;
}

static void clipboard_offer_action(void *data, struct wl_data_offer *proxy,
	uint32_t action) {
	(void)data;
	(void)proxy;
	(void)action;
}

static const struct wl_data_offer_listener clipboard_offer_listener = {
	.offer = clipboard_offer_mime,
	.source_actions = clipboard_offer_source_actions,
	.action = clipboard_offer_action,
};

static void data_offer(void *data, struct wl_data_device *device,
	struct wl_data_offer *proxy) {
	(void)data;
	(void)device;
	struct clipboard_offer *offer = calloc(1, sizeof(*offer));
	if (offer == NULL) {
		wl_data_offer_destroy(proxy);
		return;
	}
	offer->proxy = proxy;
	wl_data_offer_add_listener(proxy, &clipboard_offer_listener, offer);
}

static void data_enter(void *data, struct wl_data_device *device,
	uint32_t serial, struct wl_surface *surface, wl_fixed_t x, wl_fixed_t y,
	struct wl_data_offer *offer) {
	(void)data;
	(void)device;
	(void)serial;
	(void)surface;
	(void)x;
	(void)y;
	(void)offer;
}

static void data_leave(void *data, struct wl_data_device *device) {
	(void)data;
	(void)device;
}

static void data_motion(void *data, struct wl_data_device *device,
	uint32_t time, wl_fixed_t x, wl_fixed_t y) {
	(void)data;
	(void)device;
	(void)time;
	(void)x;
	(void)y;
}

static void data_drop(void *data, struct wl_data_device *device) {
	(void)data;
	(void)device;
}

static void data_selection(void *data, struct wl_data_device *device,
	struct wl_data_offer *proxy) {
	(void)device;
	struct client *client = data;
	destroy_clipboard_offer(&client->clipboard_offer);
	if (proxy != NULL) {
		client->clipboard_offer = wl_proxy_get_user_data((struct wl_proxy *)proxy);
	}
}

static const struct wl_data_device_listener data_device_listener = {
	.data_offer = data_offer,
	.enter = data_enter,
	.leave = data_leave,
	.motion = data_motion,
	.drop = data_drop,
	.selection = data_selection,
};

static void primary_offer_mime(void *data,
	struct zwp_primary_selection_offer_v1 *proxy, const char *mime_type) {
	(void)proxy;
	struct primary_offer *offer = data;
	if (strcmp(mime_type, MIME_UTF8) == 0) offer->utf8 = true;
	if (strcmp(mime_type, MIME_TEXT) == 0) offer->text = true;
}

static const struct zwp_primary_selection_offer_v1_listener primary_offer_listener = {
	.offer = primary_offer_mime,
};

static void primary_data_offer(void *data,
	struct zwp_primary_selection_device_v1 *device,
	struct zwp_primary_selection_offer_v1 *proxy) {
	(void)data;
	(void)device;
	struct primary_offer *offer = calloc(1, sizeof(*offer));
	if (offer == NULL) {
		zwp_primary_selection_offer_v1_destroy(proxy);
		return;
	}
	offer->proxy = proxy;
	zwp_primary_selection_offer_v1_add_listener(proxy,
		&primary_offer_listener, offer);
}

static void primary_selection(void *data,
	struct zwp_primary_selection_device_v1 *device,
	struct zwp_primary_selection_offer_v1 *proxy) {
	(void)device;
	struct client *client = data;
	destroy_primary_offer(&client->primary_offer);
	if (proxy != NULL) {
		client->primary_offer = wl_proxy_get_user_data((struct wl_proxy *)proxy);
	}
}

static const struct zwp_primary_selection_device_v1_listener primary_device_listener = {
	.data_offer = primary_data_offer,
	.selection = primary_selection,
};

static void clipboard_source_target(void *data, struct wl_data_source *source,
	const char *mime_type) {
	(void)data;
	(void)source;
	(void)mime_type;
}

static void clipboard_source_send(void *data, struct wl_data_source *source,
	const char *mime_type, int32_t fd) {
	(void)source;
	struct clipboard_source *selection = data;
	if (strcmp(mime_type, MIME_UTF8) == 0 || strcmp(mime_type, MIME_TEXT) == 0)
		write_all(fd, selection->payload);
	close(fd);
}

static void clipboard_source_cancelled(void *data,
	struct wl_data_source *source) {
	struct clipboard_source *selection = data;
	struct client *client = selection->client;
	if (client->clipboard_source == selection) client->clipboard_source = NULL;
	client->clipboard_cancellations++;
	wl_data_source_destroy(source);
	free(selection);
}

static void clipboard_source_drop(void *data, struct wl_data_source *source) {
	(void)data;
	(void)source;
}

static void clipboard_source_finished(void *data, struct wl_data_source *source) {
	(void)data;
	(void)source;
}

static void clipboard_source_action(void *data, struct wl_data_source *source,
	uint32_t action) {
	(void)data;
	(void)source;
	(void)action;
}

static const struct wl_data_source_listener clipboard_source_listener = {
	.target = clipboard_source_target,
	.send = clipboard_source_send,
	.cancelled = clipboard_source_cancelled,
	.dnd_drop_performed = clipboard_source_drop,
	.dnd_finished = clipboard_source_finished,
	.action = clipboard_source_action,
};

static void primary_source_send(void *data,
	struct zwp_primary_selection_source_v1 *source, const char *mime_type,
	int32_t fd) {
	(void)source;
	struct primary_source *selection = data;
	if (strcmp(mime_type, MIME_UTF8) == 0 || strcmp(mime_type, MIME_TEXT) == 0)
		write_all(fd, selection->payload);
	close(fd);
}

static void primary_source_cancelled(void *data,
	struct zwp_primary_selection_source_v1 *source) {
	struct primary_source *selection = data;
	struct client *client = selection->client;
	if (client->primary_source == selection) client->primary_source = NULL;
	client->primary_cancellations++;
	zwp_primary_selection_source_v1_destroy(source);
	free(selection);
}

static const struct zwp_primary_selection_source_v1_listener primary_source_listener = {
	.send = primary_source_send,
	.cancelled = primary_source_cancelled,
};

static void keyboard_keymap(void *data, struct wl_keyboard *keyboard,
	uint32_t format, int32_t fd, uint32_t size) {
	(void)data;
	(void)keyboard;
	(void)format;
	(void)size;
	close(fd);
}

static void keyboard_enter(void *data, struct wl_keyboard *keyboard,
	uint32_t serial, struct wl_surface *surface, struct wl_array *keys) {
	(void)keyboard;
	(void)surface;
	(void)keys;
	struct client *client = data;
	client->serial = serial;
}

static void keyboard_leave(void *data, struct wl_keyboard *keyboard,
	uint32_t serial, struct wl_surface *surface) {
	(void)data;
	(void)keyboard;
	(void)serial;
	(void)surface;
}

static void keyboard_key(void *data, struct wl_keyboard *keyboard,
	uint32_t serial, uint32_t time, uint32_t key, uint32_t state) {
	(void)keyboard;
	(void)time;
	(void)key;
	(void)state;
	struct client *client = data;
	client->serial = serial;
}

static void keyboard_modifiers(void *data, struct wl_keyboard *keyboard,
	uint32_t serial, uint32_t depressed, uint32_t latched, uint32_t locked,
	uint32_t group) {
	(void)data;
	(void)keyboard;
	(void)serial;
	(void)depressed;
	(void)latched;
	(void)locked;
	(void)group;
}

static void keyboard_repeat(void *data, struct wl_keyboard *keyboard,
	int32_t rate, int32_t delay) {
	(void)data;
	(void)keyboard;
	(void)rate;
	(void)delay;
}

static const struct wl_keyboard_listener keyboard_listener = {
	.keymap = keyboard_keymap,
	.enter = keyboard_enter,
	.leave = keyboard_leave,
	.key = keyboard_key,
	.modifiers = keyboard_modifiers,
	.repeat_info = keyboard_repeat,
};

static void seat_capabilities(void *data, struct wl_seat *seat,
	uint32_t capabilities) {
	struct client *client = data;
	if ((capabilities & WL_SEAT_CAPABILITY_KEYBOARD) != 0 &&
			client->keyboard == NULL) {
		client->keyboard = wl_seat_get_keyboard(seat);
		wl_keyboard_add_listener(client->keyboard, &keyboard_listener, client);
	}
}

static void seat_name(void *data, struct wl_seat *seat, const char *name) {
	(void)data;
	(void)seat;
	(void)name;
}

static const struct wl_seat_listener seat_listener = {
	.capabilities = seat_capabilities,
	.name = seat_name,
};

static void wm_base_ping(void *data, struct xdg_wm_base *wm_base,
	uint32_t serial) {
	(void)data;
	xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
	.ping = wm_base_ping,
};

static void registry_global(void *data, struct wl_registry *registry,
	uint32_t name, const char *interface, uint32_t version) {
	struct client *client = data;
	if (strcmp(interface, wl_compositor_interface.name) == 0) {
		client->compositor = wl_registry_bind(registry, name,
			&wl_compositor_interface, version < 5 ? version : 5);
	} else if (strcmp(interface, wl_shm_interface.name) == 0) {
		client->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (strcmp(interface, wl_seat_interface.name) == 0) {
		client->seat = wl_registry_bind(registry, name, &wl_seat_interface,
			version < 7 ? version : 7);
		wl_seat_add_listener(client->seat, &seat_listener, client);
	} else if (strcmp(interface, wl_data_device_manager_interface.name) == 0) {
		client->data_manager = wl_registry_bind(registry, name,
			&wl_data_device_manager_interface, version < 3 ? version : 3);
	} else if (strcmp(interface,
			zwp_primary_selection_device_manager_v1_interface.name) == 0) {
		client->primary_manager = wl_registry_bind(registry, name,
			&zwp_primary_selection_device_manager_v1_interface, 1);
	} else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
		client->wm_base = wl_registry_bind(registry, name,
			&xdg_wm_base_interface, version < 3 ? version : 3);
		xdg_wm_base_add_listener(client->wm_base, &wm_base_listener, client);
	}
}

static void registry_global_remove(void *data, struct wl_registry *registry,
	uint32_t name) {
	(void)data;
	(void)registry;
	(void)name;
}

static const struct wl_registry_listener registry_listener = {
	.global = registry_global,
	.global_remove = registry_global_remove,
};

static void surface_configure(void *data, struct xdg_surface *surface,
	uint32_t serial) {
	struct client *client = data;
	xdg_surface_ack_configure(surface, serial);
	if (client->mapped) return;
	wl_surface_attach(client->surface, client->buffer, 0, 0);
	wl_surface_damage_buffer(client->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(client->surface);
	client->mapped = true;
}

static const struct xdg_surface_listener xdg_surface_listener = {
	.configure = surface_configure,
};

static void toplevel_configure(void *data, struct xdg_toplevel *toplevel,
	int32_t width, int32_t height, struct wl_array *states) {
	(void)data;
	(void)toplevel;
	(void)width;
	(void)height;
	(void)states;
}

static void toplevel_close(void *data, struct xdg_toplevel *toplevel) {
	(void)toplevel;
	struct client *client = data;
	client->running = false;
}

static void toplevel_bounds(void *data, struct xdg_toplevel *toplevel,
	int32_t width, int32_t height) {
	(void)data;
	(void)toplevel;
	(void)width;
	(void)height;
}

static void toplevel_capabilities(void *data, struct xdg_toplevel *toplevel,
	struct wl_array *capabilities) {
	(void)data;
	(void)toplevel;
	(void)capabilities;
}

static const struct xdg_toplevel_listener toplevel_listener = {
	.configure = toplevel_configure,
	.close = toplevel_close,
	.configure_bounds = toplevel_bounds,
	.wm_capabilities = toplevel_capabilities,
};

static struct wl_buffer *create_buffer(struct client *client) {
	char name[] = "/wtwm-selection-XXXXXX";
	int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
	if (fd < 0) return NULL;
	shm_unlink(name);
	const int width = 180;
	const int height = 100;
	const size_t stride = (size_t)width * 4;
	const size_t size = stride * (size_t)height;
	if (ftruncate(fd, (off_t)size) < 0) {
		close(fd);
		return NULL;
	}
	uint32_t *pixels = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (pixels == MAP_FAILED) {
		close(fd);
		return NULL;
	}
	for (size_t i = 0; i < size / sizeof(*pixels); ++i) pixels[i] = 0x004080c0;
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(client->shm, fd, (int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height,
		(int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

static bool dispatch_with_timeout(struct client *client, int timeout_ms) {
	if (wl_display_dispatch_pending(client->display) < 0) return false;
	if (wl_display_flush(client->display) < 0 && errno != EAGAIN) return false;
	struct pollfd descriptor = {
		.fd = wl_display_get_fd(client->display),
		.events = POLLIN,
	};
	int result;
	do result = poll(&descriptor, 1, timeout_ms); while (result < 0 && errno == EINTR);
	if (result <= 0 || (descriptor.revents & (POLLERR | POLLHUP)) != 0) return false;
	return wl_display_dispatch(client->display) >= 0;
}

static bool wait_for_offer_state(struct client *client, bool present) {
	for (unsigned i = 0; i < 100; ++i) {
		bool clipboard = client->clipboard_offer != NULL;
		bool primary = client->primary_offer != NULL;
		if (clipboard == present && primary == present) return true;
		if (!dispatch_with_timeout(client, 100)) return false;
	}
	return false;
}

static void set_clipboard(struct client *client, const char *payload) {
	struct clipboard_source *source = calloc(1, sizeof(*source));
	if (source == NULL) {
		printf("ERROR allocation\n");
		return;
	}
	source->client = client;
	source->payload = payload;
	source->proxy = wl_data_device_manager_create_data_source(client->data_manager);
	if (source->proxy == NULL) {
		free(source);
		printf("ERROR source\n");
		return;
	}
	wl_data_source_add_listener(source->proxy, &clipboard_source_listener, source);
	wl_data_source_offer(source->proxy, MIME_UTF8);
	wl_data_source_offer(source->proxy, MIME_TEXT);
	client->clipboard_source = source;
	wl_data_device_set_selection(client->data_device, source->proxy, client->serial);
	wl_display_flush(client->display);
	printf("SET CLIPBOARD %s\n", payload);
}

static void set_primary(struct client *client, const char *payload) {
	struct primary_source *source = calloc(1, sizeof(*source));
	if (source == NULL) {
		printf("ERROR allocation\n");
		return;
	}
	source->client = client;
	source->payload = payload;
	source->proxy = zwp_primary_selection_device_manager_v1_create_source(
		client->primary_manager);
	if (source->proxy == NULL) {
		free(source);
		printf("ERROR source\n");
		return;
	}
	zwp_primary_selection_source_v1_add_listener(source->proxy,
		&primary_source_listener, source);
	zwp_primary_selection_source_v1_offer(source->proxy, MIME_UTF8);
	zwp_primary_selection_source_v1_offer(source->proxy, MIME_TEXT);
	client->primary_source = source;
	zwp_primary_selection_device_v1_set_selection(client->primary_device,
		source->proxy, client->serial);
	wl_display_flush(client->display);
	printf("SET PRIMARY %s\n", payload);
}

static bool read_transfer(struct client *client, int fd, char *buffer,
	size_t buffer_size) {
	size_t used = 0;
	bool complete = false;
	while (!complete) {
		struct pollfd descriptors[2] = {
			{.fd = fd, .events = POLLIN},
			{.fd = wl_display_get_fd(client->display), .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, 10000); while (result < 0 && errno == EINTR);
		if (result <= 0) return false;
		if ((descriptors[1].revents & POLLIN) != 0 &&
				wl_display_dispatch(client->display) < 0) return false;
		if ((descriptors[0].revents & (POLLIN | POLLHUP)) != 0) {
			char chunk[256];
			ssize_t length = read(fd, chunk, sizeof(chunk));
			if (length < 0 && errno == EINTR) continue;
			if (length < 0) return false;
			if (length == 0) {
				complete = true;
			} else if (used + (size_t)length < buffer_size) {
				memcpy(buffer + used, chunk, (size_t)length);
				used += (size_t)length;
			} else {
				return false;
			}
		}
	}
	buffer[used] = '\0';
	return true;
}

static void receive_clipboard(struct client *client) {
	if (client->clipboard_offer == NULL || !client->clipboard_offer->utf8) {
		printf("ERROR CLIPBOARD offer\n");
		return;
	}
	int descriptors[2];
	if (pipe(descriptors) < 0) {
		printf("ERROR pipe\n");
		return;
	}
	wl_data_offer_receive(client->clipboard_offer->proxy, MIME_UTF8,
		descriptors[1]);
	close(descriptors[1]);
	wl_display_flush(client->display);
	char payload[1024];
	bool ok = read_transfer(client, descriptors[0], payload, sizeof(payload));
	close(descriptors[0]);
	if (ok) printf("DATA CLIPBOARD %s\n", payload);
	else printf("ERROR CLIPBOARD transfer\n");
}

static void receive_primary(struct client *client) {
	if (client->primary_offer == NULL || !client->primary_offer->utf8) {
		printf("ERROR PRIMARY offer\n");
		return;
	}
	int descriptors[2];
	if (pipe(descriptors) < 0) {
		printf("ERROR pipe\n");
		return;
	}
	zwp_primary_selection_offer_v1_receive(client->primary_offer->proxy,
		MIME_UTF8, descriptors[1]);
	close(descriptors[1]);
	wl_display_flush(client->display);
	char payload[1024];
	bool ok = read_transfer(client, descriptors[0], payload, sizeof(payload));
	close(descriptors[0]);
	if (ok) printf("DATA PRIMARY %s\n", payload);
	else printf("ERROR PRIMARY transfer\n");
}

static void handle_command(struct client *client, char *command) {
	command[strcspn(command, "\r\n")] = '\0';
	if (strcmp(command, "SERIAL") == 0) {
		(void)wl_display_roundtrip(client->display);
		printf("SERIAL %" PRIu32 "\n", client->serial);
	} else if (strcmp(command, "SET CLIPBOARD ONE") == 0) {
		set_clipboard(client, "native-clipboard-one");
	} else if (strcmp(command, "SET CLIPBOARD TWO") == 0) {
		set_clipboard(client, "native-clipboard-two");
	} else if (strcmp(command, "SET PRIMARY") == 0) {
		set_primary(client, "native-primary");
	} else if (strcmp(command, "WAIT OFFERS") == 0) {
		bool ok = wait_for_offer_state(client, true);
		printf("OFFERS clipboard=%d primary=%d utf8=%d/%d\n",
			client->clipboard_offer != NULL, client->primary_offer != NULL,
			client->clipboard_offer != NULL && client->clipboard_offer->utf8,
			client->primary_offer != NULL && client->primary_offer->utf8);
		if (!ok) client->running = false;
	} else if (strcmp(command, "WAIT CLEAR") == 0) {
		bool ok = wait_for_offer_state(client, false);
		printf("CLEAR clipboard=%d primary=%d\n",
			client->clipboard_offer == NULL, client->primary_offer == NULL);
		if (!ok) client->running = false;
	} else if (strcmp(command, "GET CLIPBOARD") == 0) {
		receive_clipboard(client);
	} else if (strcmp(command, "GET PRIMARY") == 0) {
		receive_primary(client);
	} else if (strcmp(command, "CANCELS") == 0) {
		(void)wl_display_roundtrip(client->display);
		printf("CANCELS clipboard=%u primary=%u\n",
			client->clipboard_cancellations, client->primary_cancellations);
	} else if (strcmp(command, "EXIT") == 0) {
		printf("EXITING\n");
		client->running = false;
	} else {
		printf("ERROR command\n");
	}
	fflush(stdout);
}

static bool initialize(struct client *client) {
	client->display = wl_display_connect(NULL);
	if (client->display == NULL) return false;
	struct wl_registry *registry = wl_display_get_registry(client->display);
	wl_registry_add_listener(registry, &registry_listener, client);
	if (wl_display_roundtrip(client->display) < 0 ||
			client->compositor == NULL || client->shm == NULL ||
			client->seat == NULL || client->data_manager == NULL ||
			client->primary_manager == NULL || client->wm_base == NULL) return false;
	client->data_device = wl_data_device_manager_get_data_device(
		client->data_manager, client->seat);
	wl_data_device_add_listener(client->data_device, &data_device_listener, client);
	client->primary_device = zwp_primary_selection_device_manager_v1_get_device(
		client->primary_manager, client->seat);
	zwp_primary_selection_device_v1_add_listener(client->primary_device,
		&primary_device_listener, client);
	client->buffer = create_buffer(client);
	client->surface = wl_compositor_create_surface(client->compositor);
	if (client->buffer == NULL || client->surface == NULL) return false;
	client->xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base,
		client->surface);
	if (client->xdg_surface == NULL) return false;
	client->toplevel = xdg_surface_get_toplevel(client->xdg_surface);
	if (client->toplevel == NULL) return false;
	xdg_surface_add_listener(client->xdg_surface, &xdg_surface_listener, client);
	xdg_toplevel_add_listener(client->toplevel, &toplevel_listener, client);
	xdg_toplevel_set_title(client->toplevel, "wtwm-selection-wayland");
	xdg_toplevel_set_app_id(client->toplevel, "org.wtwm.Selection");
	wl_surface_commit(client->surface);
	while ((!client->mapped || client->serial == 0) &&
			dispatch_with_timeout(client, 10000)) {
	}
	wl_registry_destroy(registry);
	return client->mapped && client->serial != 0;
}

static void finish(struct client *client) {
	destroy_clipboard_offer(&client->clipboard_offer);
	destroy_primary_offer(&client->primary_offer);
	if (client->clipboard_source != NULL) {
		struct clipboard_source *source = client->clipboard_source;
		client->clipboard_source = NULL;
		wl_data_source_destroy(source->proxy);
		free(source);
	}
	if (client->primary_source != NULL) {
		struct primary_source *source = client->primary_source;
		client->primary_source = NULL;
		zwp_primary_selection_source_v1_destroy(source->proxy);
		free(source);
	}
	if (client->toplevel != NULL) xdg_toplevel_destroy(client->toplevel);
	if (client->xdg_surface != NULL) xdg_surface_destroy(client->xdg_surface);
	if (client->surface != NULL) wl_surface_destroy(client->surface);
	if (client->buffer != NULL) wl_buffer_destroy(client->buffer);
	if (client->data_device != NULL) wl_data_device_release(client->data_device);
	if (client->primary_device != NULL)
		zwp_primary_selection_device_v1_destroy(client->primary_device);
	if (client->keyboard != NULL) wl_keyboard_release(client->keyboard);
	if (client->primary_manager != NULL)
		zwp_primary_selection_device_manager_v1_destroy(client->primary_manager);
	if (client->data_manager != NULL)
		wl_data_device_manager_destroy(client->data_manager);
	if (client->seat != NULL) wl_seat_release(client->seat);
	if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
	if (client->shm != NULL) wl_shm_destroy(client->shm);
	if (client->compositor != NULL) wl_compositor_destroy(client->compositor);
	if (client->display != NULL) wl_display_disconnect(client->display);
}

int main(void) {
	struct client client = {.running = true};
	if (!initialize(&client)) {
		fprintf(stderr, "failed to initialize selection Wayland client\n");
		finish(&client);
		return EXIT_FAILURE;
	}
	printf("READY\n");
	fflush(stdout);
	while (client.running) {
		if (wl_display_dispatch_pending(client.display) < 0) break;
		if (wl_display_flush(client.display) < 0 && errno != EAGAIN) break;
		struct pollfd descriptors[2] = {
			{.fd = wl_display_get_fd(client.display), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, -1); while (result < 0 && errno == EINTR);
		if (result < 0) break;
		if ((descriptors[0].revents & POLLIN) != 0 &&
				wl_display_dispatch(client.display) < 0) break;
		if ((descriptors[1].revents & POLLIN) != 0) {
			char command[128];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			handle_command(&client, command);
		}
	}
	finish(&client);
	return EXIT_SUCCESS;
}
