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

enum client_mode {
	MODE_SURVIVOR,
	MODE_SERIALS,
	MODE_GEOMETRY,
	MODE_POSITIONER,
};

struct client {
	struct wl_display *display;
	struct wl_registry *registry;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct wl_seat *seat;
	struct wl_pointer *pointer;
	struct wl_surface *cursor_surface;
	struct xdg_wm_base *wm_base;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	enum client_mode mode;
	uint32_t button_serial;
	bool mapped;
	bool button_pressed;
	bool fuzz_sent;
	bool closed;
};

static void emit(const char *message) {
	puts(message);
	fflush(stdout);
}

static int disconnect_client(struct client *client, int status) {
	if (client->display != NULL) {
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
	} else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
		client->wm_base = wl_registry_bind(registry, name,
			&xdg_wm_base_interface, 1);
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

static void send_oversized_positioner(struct client *client) {
	struct wl_surface *popup_surface =
		wl_compositor_create_surface(client->compositor);
	struct xdg_surface *popup_xdg =
		xdg_wm_base_get_xdg_surface(client->wm_base, popup_surface);
	struct xdg_positioner *positioner =
		xdg_wm_base_create_positioner(client->wm_base);
	xdg_positioner_set_size(positioner, INT32_MAX, INT32_MAX);
	xdg_positioner_set_anchor_rect(positioner, INT32_MIN, INT32_MIN,
		INT32_MAX, INT32_MAX);
	xdg_positioner_set_anchor(positioner, XDG_POSITIONER_ANCHOR_BOTTOM_RIGHT);
	xdg_positioner_set_gravity(positioner,
		XDG_POSITIONER_GRAVITY_BOTTOM_RIGHT);
	(void)xdg_surface_get_popup(popup_xdg, client->xdg_surface, positioner);
	xdg_positioner_destroy(positioner);
	wl_surface_commit(popup_surface);
	emit("POSITIONER_SENT");
}

static enum client_mode parse_mode(const char *value) {
	if (strcmp(value, "survivor") == 0) return MODE_SURVIVOR;
	if (strcmp(value, "serials") == 0) return MODE_SERIALS;
	if (strcmp(value, "geometry") == 0) return MODE_GEOMETRY;
	if (strcmp(value, "positioner") == 0) return MODE_POSITIONER;
	fprintf(stderr, "unknown mode: %s\n", value);
	exit(2);
}

int main(int argc, char **argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: %s survivor|serials|geometry|positioner\n",
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
			client.seat == NULL || client.wm_base == NULL ||
			wl_display_roundtrip(client.display) < 0 ||
			client.pointer == NULL) {
		fprintf(stderr, "protocol fuzz client: required globals unavailable\n");
		return disconnect_client(&client, 1);
	}
	client.cursor_surface = wl_compositor_create_surface(client.compositor);
	if (client.cursor_surface == NULL) {
		fprintf(stderr, "protocol fuzz client: cursor surface setup failed\n");
		return disconnect_client(&client, 1);
	}
	const char *titles[] = {
		[MODE_SURVIVOR] = "m9-protocol-survivor",
		[MODE_SERIALS] = "m9-protocol-serials",
		[MODE_GEOMETRY] = "m9-protocol-geometry",
		[MODE_POSITIONER] = "m9-protocol-positioner",
	};
	if (!create_toplevel(&client, titles[client.mode])) {
		fprintf(stderr, "protocol fuzz client: toplevel setup failed\n");
		return disconnect_client(&client, 1);
	}
	while (!client.mapped && wl_display_dispatch(client.display) >= 0) {}
	if (!client.mapped) return disconnect_client(&client, 1);
	if (client.mode == MODE_GEOMETRY) send_oversized_geometry(&client);
	if (client.mode == MODE_POSITIONER) send_oversized_positioner(&client);
	if (client.mode == MODE_GEOMETRY || client.mode == MODE_POSITIONER) {
		if (wl_display_roundtrip(client.display) < 0) {
			emit("DISCONNECTED");
			return disconnect_client(&client,
				client.mode == MODE_POSITIONER ? 0 : 1);
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
