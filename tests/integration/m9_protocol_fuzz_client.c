/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "xdg-shell-client-protocol.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>

#define WTWM_PROTOCOL_BOUNDARY 65535

enum client_mode {
	MODE_SURVIVOR,
	MODE_SERIALS,
	MODE_GEOMETRY,
	MODE_DRAG,
	MODE_POSITIONER_SIZE,
	MODE_POSITIONER_ANCHOR,
	MODE_POSITIONER_PARENT,
	MODE_POSITIONER_OFFSET,
	MODE_POSITIONER_GEOMETRY,
};

struct client {
	struct wl_display *display;
	struct wl_registry *registry;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct wl_seat *seat;
	struct wl_pointer *pointer;
	struct wl_data_device_manager *data_manager;
	struct wl_data_device *data_device;
	struct wl_data_offer *drag_offer;
	struct wl_data_source *drag_sources[4];
	size_t drag_source_count;
	struct wl_surface *cursor_surface;
	struct xdg_wm_base *wm_base;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	struct wl_surface *popup_surface;
	struct xdg_surface *popup_xdg_surface;
	struct xdg_popup *popup;
	enum client_mode mode;
	uint32_t button_serial;
	bool mapped;
	bool button_pressed;
	bool drag_requested;
	bool fuzz_sent;
	bool closed;
};

static void emit(const char *message) {
	puts(message);
	fflush(stdout);
}

static int disconnect_client(struct client *client, int status) {
	if (client->display != NULL) {
		if (client->popup != NULL) xdg_popup_destroy(client->popup);
		if (client->popup_xdg_surface != NULL)
			xdg_surface_destroy(client->popup_xdg_surface);
		if (client->popup_surface != NULL)
			wl_surface_destroy(client->popup_surface);
		if (client->toplevel != NULL) xdg_toplevel_destroy(client->toplevel);
		if (client->xdg_surface != NULL)
			xdg_surface_destroy(client->xdg_surface);
		if (client->surface != NULL) wl_surface_destroy(client->surface);
		if (client->buffer != NULL) wl_buffer_destroy(client->buffer);
		if (client->cursor_surface != NULL)
			wl_surface_destroy(client->cursor_surface);
		if (client->pointer != NULL) wl_pointer_destroy(client->pointer);
		for (size_t i = 0; i < client->drag_source_count; ++i)
			wl_data_source_destroy(client->drag_sources[i]);
		if (client->drag_offer != NULL) wl_data_offer_destroy(client->drag_offer);
		if (client->data_device != NULL)
			wl_data_device_destroy(client->data_device);
		if (client->data_manager != NULL)
			wl_data_device_manager_destroy(client->data_manager);
		if (client->seat != NULL) wl_seat_destroy(client->seat);
		if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
		if (client->shm != NULL) wl_shm_destroy(client->shm);
		if (client->compositor != NULL)
			wl_compositor_destroy(client->compositor);
		if (client->registry != NULL) wl_registry_destroy(client->registry);
		wl_display_disconnect(client->display);
		client->display = NULL;
	}
	return status;
}

static struct wl_buffer *create_buffer(struct client *client, int width,
		int height) {
	char name[] = "/wtwm-m9-protocol-XXXXXX";
	int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
	if (fd < 0) return NULL;
	shm_unlink(name);
	size_t stride = (size_t)width * 4;
	size_t size = stride * (size_t)height;
	if (size > INT32_MAX || ftruncate(fd, (off_t)size) < 0) {
		close(fd);
		return NULL;
	}
	uint32_t *pixels = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED,
		fd, 0);
	if (pixels == MAP_FAILED) {
		close(fd);
		return NULL;
	}
	for (size_t i = 0; i < size / sizeof(*pixels); ++i)
		pixels[i] = 0xff315b75u;
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(client->shm, fd,
		(int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width,
		height, (int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

static void wm_base_ping(void *data, struct xdg_wm_base *wm_base,
		uint32_t serial) {
	(void)data;
	xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
	.ping = wm_base_ping,
};

static void drag_source_target(void *data, struct wl_data_source *source,
		const char *mime_type) {
	(void)data;
	(void)source;
	(void)mime_type;
}

static void drag_source_send(void *data, struct wl_data_source *source,
		const char *mime_type, int32_t fd) {
	(void)data;
	(void)source;
	(void)mime_type;
	close(fd);
}

static void drag_source_cancelled(void *data, struct wl_data_source *source) {
	(void)data;
	(void)source;
}

static void drag_source_drop_performed(void *data,
		struct wl_data_source *source) {
	(void)data;
	(void)source;
}

static void drag_source_finished(void *data, struct wl_data_source *source) {
	(void)data;
	(void)source;
}

static void drag_source_action(void *data, struct wl_data_source *source,
		uint32_t action) {
	(void)data;
	(void)source;
	(void)action;
}

static const struct wl_data_source_listener drag_source_listener = {
	.target = drag_source_target,
	.send = drag_source_send,
	.cancelled = drag_source_cancelled,
	.dnd_drop_performed = drag_source_drop_performed,
	.dnd_finished = drag_source_finished,
	.action = drag_source_action,
};

static void drag_offer_mime(void *data, struct wl_data_offer *offer,
		const char *mime_type) {
	(void)data;
	(void)offer;
	(void)mime_type;
}

static void drag_offer_actions(void *data, struct wl_data_offer *offer,
		uint32_t actions) {
	(void)data;
	(void)offer;
	(void)actions;
}

static void drag_offer_action(void *data, struct wl_data_offer *offer,
		uint32_t action) {
	(void)data;
	(void)offer;
	(void)action;
}

static const struct wl_data_offer_listener drag_offer_listener = {
	.offer = drag_offer_mime,
	.source_actions = drag_offer_actions,
	.action = drag_offer_action,
};

static void data_device_offer(void *data, struct wl_data_device *device,
		struct wl_data_offer *offer) {
	(void)device;
	struct client *client = data;
	if (client->drag_offer != NULL) wl_data_offer_destroy(client->drag_offer);
	client->drag_offer = offer;
	wl_data_offer_add_listener(offer, &drag_offer_listener, client);
}

static void data_device_enter(void *data, struct wl_data_device *device,
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

static void data_device_leave(void *data, struct wl_data_device *device) {
	(void)data;
	(void)device;
}

static void data_device_motion(void *data, struct wl_data_device *device,
		uint32_t time, wl_fixed_t x, wl_fixed_t y) {
	(void)data;
	(void)device;
	(void)time;
	(void)x;
	(void)y;
}

static void data_device_drop(void *data, struct wl_data_device *device) {
	(void)data;
	(void)device;
}

static void data_device_selection(void *data, struct wl_data_device *device,
		struct wl_data_offer *offer) {
	(void)data;
	(void)device;
	(void)offer;
}

static const struct wl_data_device_listener data_device_listener = {
	.data_offer = data_device_offer,
	.enter = data_device_enter,
	.leave = data_device_leave,
	.motion = data_device_motion,
	.drop = data_device_drop,
	.selection = data_device_selection,
};

static struct wl_data_source *create_drag_source(struct client *client) {
	if (client->drag_source_count >=
			sizeof(client->drag_sources) / sizeof(client->drag_sources[0]))
		return NULL;
	struct wl_data_source *source =
		wl_data_device_manager_create_data_source(client->data_manager);
	if (source == NULL) return NULL;
	wl_data_source_add_listener(source, &drag_source_listener, client);
	wl_data_source_offer(source, "text/plain");
	client->drag_sources[client->drag_source_count++] = source;
	return source;
}

static void send_invalid_drag_fuzz(struct client *client, uint32_t stale) {
	const uint32_t serials[] = {0, stale, UINT32_MAX};
	for (size_t i = 0; i < sizeof(serials) / sizeof(serials[0]); ++i) {
		struct wl_data_source *source = create_drag_source(client);
		if (source == NULL) continue;
		wl_data_device_start_drag(client->data_device, source,
			client->surface, NULL, serials[i]);
	}
}

static void send_valid_drag(struct client *client, uint32_t serial) {
	struct wl_data_source *source = create_drag_source(client);
	if (source == NULL) return;
	wl_data_device_start_drag(client->data_device, source, client->surface,
		NULL, serial);
	(void)wl_display_flush(client->display);
	client->drag_requested = true;
	printf("DRAG_REQUESTED serial=%" PRIu32 "\n", serial);
	fflush(stdout);
}

static void send_serial_fuzz(struct client *client) {
	const uint32_t stale = client->button_serial;
	const uint32_t invalid = UINT32_MAX;
	const uint32_t serials[] = {0, stale, invalid};
	for (size_t i = 0; i < sizeof(serials) / sizeof(serials[0]); ++i) {
		xdg_toplevel_move(client->toplevel, client->seat, serials[i]);
		xdg_toplevel_resize(client->toplevel, client->seat, serials[i],
			XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM_RIGHT);
		xdg_toplevel_show_window_menu(client->toplevel, client->seat,
			serials[i], INT32_MIN, INT32_MAX);
		if (serials[i] != stale)
			wl_pointer_set_cursor(client->pointer, serials[i],
				client->cursor_surface, INT32_MIN, INT32_MAX);
	}
	send_invalid_drag_fuzz(client, stale);
	client->fuzz_sent = true;
	printf("FUZZ_SENT stale=%" PRIu32 "\n", stale);
	fflush(stdout);
}

static void pointer_enter(void *data, struct wl_pointer *pointer,
		uint32_t serial, struct wl_surface *surface, wl_fixed_t x,
		wl_fixed_t y) {
	(void)pointer;
	(void)x;
	(void)y;
	struct client *client = data;
	if (surface != client->surface) return;
	printf("POINTER_ENTER %" PRIu32 "\n", serial);
	fflush(stdout);
}

static void pointer_leave(void *data, struct wl_pointer *pointer,
		uint32_t serial, struct wl_surface *surface) {
	(void)data;
	(void)pointer;
	(void)serial;
	(void)surface;
}

static void pointer_motion(void *data, struct wl_pointer *pointer,
		uint32_t time, wl_fixed_t x, wl_fixed_t y) {
	(void)data;
	(void)pointer;
	(void)time;
	(void)x;
	(void)y;
}

static void pointer_button(void *data, struct wl_pointer *pointer,
		uint32_t serial, uint32_t time, uint32_t button, uint32_t state) {
	(void)pointer;
	(void)time;
	struct client *client = data;
	printf("POINTER_BUTTON %" PRIu32 " %" PRIu32 " %s\n", serial, button,
		state == WL_POINTER_BUTTON_STATE_PRESSED ? "press" : "release");
	fflush(stdout);
	if (client->mode == MODE_DRAG &&
			state == WL_POINTER_BUTTON_STATE_PRESSED &&
			!client->drag_requested) {
		send_valid_drag(client, serial);
		return;
	}
	if (client->mode != MODE_SERIALS) return;
	if (state == WL_POINTER_BUTTON_STATE_PRESSED) {
		client->button_serial = serial;
		client->button_pressed = true;
	} else if (client->button_pressed && !client->fuzz_sent) {
		client->button_pressed = false;
		send_serial_fuzz(client);
	}
}

static void pointer_axis(void *data, struct wl_pointer *pointer, uint32_t time,
		uint32_t axis, wl_fixed_t value) {
	(void)data;
	(void)pointer;
	(void)time;
	(void)axis;
	(void)value;
}

static void pointer_frame(void *data, struct wl_pointer *pointer) {
	(void)data;
	(void)pointer;
}

static void pointer_axis_source(void *data, struct wl_pointer *pointer,
		uint32_t source) {
	(void)data;
	(void)pointer;
	(void)source;
}

static void pointer_axis_stop(void *data, struct wl_pointer *pointer,
		uint32_t time, uint32_t axis) {
	(void)data;
	(void)pointer;
	(void)time;
	(void)axis;
}

static void pointer_axis_discrete(void *data, struct wl_pointer *pointer,
		uint32_t axis, int32_t discrete) {
	(void)data;
	(void)pointer;
	(void)axis;
	(void)discrete;
}

static const struct wl_pointer_listener pointer_listener = {
	.enter = pointer_enter,
	.leave = pointer_leave,
	.motion = pointer_motion,
	.button = pointer_button,
	.axis = pointer_axis,
	.frame = pointer_frame,
	.axis_source = pointer_axis_source,
	.axis_stop = pointer_axis_stop,
	.axis_discrete = pointer_axis_discrete,
};

static void seat_capabilities(void *data, struct wl_seat *seat,
		uint32_t capabilities) {
	struct client *client = data;
	if ((capabilities & WL_SEAT_CAPABILITY_POINTER) != 0 &&
			client->pointer == NULL) {
		client->pointer = wl_seat_get_pointer(seat);
		wl_pointer_add_listener(client->pointer, &pointer_listener, client);
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
	} else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
		client->wm_base = wl_registry_bind(registry, name,
			&xdg_wm_base_interface, version < 6 ? version : 6);
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

static void xdg_surface_configure(void *data, struct xdg_surface *surface,
		uint32_t serial) {
	struct client *client = data;
	xdg_surface_ack_configure(surface, serial);
	if (client->mapped) return;
	wl_surface_attach(client->surface, client->buffer, 0, 0);
	wl_surface_damage_buffer(client->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(client->surface);
	client->mapped = true;
	emit("MAPPED");
}

static const struct xdg_surface_listener xdg_surface_listener = {
	.configure = xdg_surface_configure,
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
	client->closed = true;
}

static void toplevel_configure_bounds(void *data,
		struct xdg_toplevel *toplevel, int32_t width, int32_t height) {
	(void)data;
	(void)toplevel;
	(void)width;
	(void)height;
}

static void toplevel_wm_capabilities(void *data,
		struct xdg_toplevel *toplevel, struct wl_array *capabilities) {
	(void)data;
	(void)toplevel;
	(void)capabilities;
}

static const struct xdg_toplevel_listener toplevel_listener = {
	.configure = toplevel_configure,
	.close = toplevel_close,
	.configure_bounds = toplevel_configure_bounds,
	.wm_capabilities = toplevel_wm_capabilities,
};

static bool create_toplevel(struct client *client, const char *title) {
	client->buffer = create_buffer(client, 240, 160);
	if (client->buffer == NULL) return false;
	client->surface = wl_compositor_create_surface(client->compositor);
	client->xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base,
		client->surface);
	xdg_surface_add_listener(client->xdg_surface, &xdg_surface_listener, client);
	client->toplevel = xdg_surface_get_toplevel(client->xdg_surface);
	xdg_toplevel_add_listener(client->toplevel, &toplevel_listener, client);
	xdg_toplevel_set_title(client->toplevel, title);
	xdg_toplevel_set_app_id(client->toplevel, "org.wtwm.ProtocolFuzz");
	wl_surface_commit(client->surface);
	return true;
}

static void send_oversized_geometry(struct client *client) {
	xdg_surface_set_window_geometry(client->xdg_surface, INT32_MIN, INT32_MIN,
		INT32_MAX, INT32_MAX);
	wl_surface_commit(client->surface);
	emit("GEOMETRY_SENT");
}

static void send_hostile_positioner(struct client *client) {
	client->popup_surface = wl_compositor_create_surface(client->compositor);
	client->popup_xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base,
		client->popup_surface);
	struct xdg_positioner *positioner =
		xdg_wm_base_create_positioner(client->wm_base);
	int size_width = 64, size_height = 48;
	int anchor_x = 0, anchor_y = 0, anchor_width = 100, anchor_height = 80;
	if (client->mode == MODE_POSITIONER_SIZE) {
		size_width = INT32_MAX;
		size_height = INT32_MAX;
	} else if (client->mode == MODE_POSITIONER_ANCHOR) {
		anchor_x = INT32_MIN;
		anchor_y = INT32_MAX;
		anchor_width = INT32_MAX;
		anchor_height = INT32_MAX;
	} else if (client->mode == MODE_POSITIONER_GEOMETRY) {
		size_width = WTWM_PROTOCOL_BOUNDARY;
		size_height = WTWM_PROTOCOL_BOUNDARY;
		anchor_x = WTWM_PROTOCOL_BOUNDARY;
		anchor_y = WTWM_PROTOCOL_BOUNDARY;
		anchor_width = WTWM_PROTOCOL_BOUNDARY;
		anchor_height = WTWM_PROTOCOL_BOUNDARY;
	}
	xdg_positioner_set_size(positioner, size_width, size_height);
	xdg_positioner_set_anchor_rect(positioner, anchor_x, anchor_y,
		anchor_width, anchor_height);
	xdg_positioner_set_anchor(positioner, XDG_POSITIONER_ANCHOR_BOTTOM_RIGHT);
	xdg_positioner_set_gravity(positioner,
		XDG_POSITIONER_GRAVITY_BOTTOM_RIGHT);
	if (client->mode == MODE_POSITIONER_PARENT)
		xdg_positioner_set_parent_size(positioner, INT32_MAX, INT32_MAX);
	if (client->mode == MODE_POSITIONER_OFFSET)
		xdg_positioner_set_offset(positioner, INT32_MIN, INT32_MAX);
	if (client->mode == MODE_POSITIONER_GEOMETRY)
		xdg_positioner_set_offset(positioner, WTWM_PROTOCOL_BOUNDARY,
			WTWM_PROTOCOL_BOUNDARY);
	client->popup = xdg_surface_get_popup(client->popup_xdg_surface,
		client->xdg_surface, positioner);
	xdg_positioner_destroy(positioner);
	wl_surface_commit(client->popup_surface);
	const char *fields[] = {
		[MODE_POSITIONER_SIZE] = "POSITIONER_SIZE_SENT",
		[MODE_POSITIONER_ANCHOR] = "POSITIONER_ANCHOR_SENT",
		[MODE_POSITIONER_PARENT] = "POSITIONER_PARENT_SENT",
		[MODE_POSITIONER_OFFSET] = "POSITIONER_OFFSET_SENT",
		[MODE_POSITIONER_GEOMETRY] = "POSITIONER_GEOMETRY_SENT",
	};
	emit(fields[client->mode]);
}

static enum client_mode parse_mode(const char *value) {
	if (strcmp(value, "survivor") == 0) return MODE_SURVIVOR;
	if (strcmp(value, "serials") == 0) return MODE_SERIALS;
	if (strcmp(value, "geometry") == 0) return MODE_GEOMETRY;
	if (strcmp(value, "drag") == 0) return MODE_DRAG;
	if (strcmp(value, "positioner-size") == 0) return MODE_POSITIONER_SIZE;
	if (strcmp(value, "positioner-anchor") == 0) return MODE_POSITIONER_ANCHOR;
	if (strcmp(value, "positioner-parent") == 0) return MODE_POSITIONER_PARENT;
	if (strcmp(value, "positioner-offset") == 0) return MODE_POSITIONER_OFFSET;
	if (strcmp(value, "positioner-geometry") == 0)
		return MODE_POSITIONER_GEOMETRY;
	fprintf(stderr, "unknown mode: %s\n", value);
	exit(2);
}

int main(int argc, char **argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: %s survivor|serials|geometry|drag|positioner-*\n",
			argv[0]);
		return 2;
	}
	struct client client = {.mode = parse_mode(argv[1])};
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "protocol fuzz client: connect failed: %s\n",
			strerror(errno));
		return 1;
	}
	client.registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(client.registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 ||
			client.compositor == NULL || client.shm == NULL ||
			client.seat == NULL || client.data_manager == NULL ||
			client.wm_base == NULL ||
			wl_display_roundtrip(client.display) < 0 ||
			client.pointer == NULL) {
		fprintf(stderr, "protocol fuzz client: required globals unavailable\n");
		return disconnect_client(&client, 1);
	}
	client.data_device = wl_data_device_manager_get_data_device(
		client.data_manager, client.seat);
	if (client.data_device == NULL) {
		fprintf(stderr, "protocol fuzz client: data device setup failed\n");
		return disconnect_client(&client, 1);
	}
	wl_data_device_add_listener(client.data_device, &data_device_listener,
		&client);
	client.cursor_surface = wl_compositor_create_surface(client.compositor);
	if (client.cursor_surface == NULL) {
		fprintf(stderr, "protocol fuzz client: cursor surface setup failed\n");
		return disconnect_client(&client, 1);
	}
	const char *titles[] = {
		[MODE_SURVIVOR] = "m9-protocol-survivor",
		[MODE_SERIALS] = "m9-protocol-serials",
		[MODE_GEOMETRY] = "m9-protocol-geometry",
		[MODE_DRAG] = "m9-protocol-drag",
		[MODE_POSITIONER_SIZE] = "m9-protocol-positioner-size",
		[MODE_POSITIONER_ANCHOR] = "m9-protocol-positioner-anchor",
		[MODE_POSITIONER_PARENT] = "m9-protocol-positioner-parent",
		[MODE_POSITIONER_OFFSET] = "m9-protocol-positioner-offset",
		[MODE_POSITIONER_GEOMETRY] = "m9-protocol-positioner-geometry",
	};
	if (!create_toplevel(&client, titles[client.mode])) {
		fprintf(stderr, "protocol fuzz client: toplevel setup failed\n");
		return disconnect_client(&client, 1);
	}
	while (!client.mapped && wl_display_dispatch(client.display) >= 0) {}
	if (!client.mapped) return disconnect_client(&client, 1);
	if (client.mode == MODE_GEOMETRY) send_oversized_geometry(&client);
	if (client.mode >= MODE_POSITIONER_SIZE) send_hostile_positioner(&client);
	if (client.mode == MODE_GEOMETRY || client.mode >= MODE_POSITIONER_SIZE) {
		if (wl_display_roundtrip(client.display) < 0) {
			emit("DISCONNECTED");
			return disconnect_client(&client,
				client.mode >= MODE_POSITIONER_SIZE ? 0 : 1);
		}
		emit("SURVIVED");
		return disconnect_client(&client, 0);
	}
	while (!client.closed &&
			(client.mode == MODE_SURVIVOR || !client.fuzz_sent) &&
			wl_display_dispatch(client.display) >= 0) {}
	if (client.mode == MODE_SERIALS && client.fuzz_sent) {
		if (wl_display_roundtrip(client.display) < 0)
			return disconnect_client(&client, 1);
		emit("SURVIVED");
	}
	return disconnect_client(&client, 0);
}
