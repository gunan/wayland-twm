/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "xdg-shell-client-protocol.h"

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>

struct client {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	bool configured;
	bool closed;
};

static void wm_base_ping(void *data, struct xdg_wm_base *wm_base, uint32_t serial) {
	(void)data;
	xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
	.ping = wm_base_ping,
};

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
	const char *interface, uint32_t version) {
	struct client *client = data;
	if (strcmp(interface, wl_compositor_interface.name) == 0) {
		client->compositor = wl_registry_bind(registry, name,
			&wl_compositor_interface, version < 5 ? version : 5);
	} else if (strcmp(interface, wl_shm_interface.name) == 0) {
		client->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
		client->wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
		xdg_wm_base_add_listener(client->wm_base, &wm_base_listener, client);
	}
}

static void registry_global_remove(void *data, struct wl_registry *registry, uint32_t name) {
	(void)data;
	(void)registry;
	(void)name;
}

static const struct wl_registry_listener registry_listener = {
	.global = registry_global,
	.global_remove = registry_global_remove,
};

static void xdg_surface_configure(void *data, struct xdg_surface *surface, uint32_t serial) {
	struct client *client = data;
	xdg_surface_ack_configure(surface, serial);
	if (!client->configured) {
		wl_surface_attach(client->surface, client->buffer, 0, 0);
		wl_surface_damage_buffer(client->surface, 0, 0, INT32_MAX, INT32_MAX);
		wl_surface_commit(client->surface);
		client->configured = true;
		printf("MAPPED\n");
		fflush(stdout);
	}
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

static void toplevel_configure_bounds(void *data, struct xdg_toplevel *toplevel,
	int32_t width, int32_t height) {
	(void)data;
	(void)toplevel;
	(void)width;
	(void)height;
}

static void toplevel_wm_capabilities(void *data, struct xdg_toplevel *toplevel,
	struct wl_array *capabilities) {
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

static struct wl_buffer *create_buffer(struct client *client, int width, int height) {
	char name[] = "/wtwm-client-XXXXXX";
	int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
	if (fd < 0) return NULL;
	shm_unlink(name);
	size_t stride = (size_t)width * 4;
	size_t size = stride * (size_t)height;
	if (ftruncate(fd, (off_t)size) < 0) {
		close(fd);
		return NULL;
	}
	uint32_t *pixels = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (pixels == MAP_FAILED) {
		close(fd);
		return NULL;
	}
	for (int y = 0; y < height; ++y) {
		for (int x = 0; x < width; ++x) {
			uint32_t r = (uint32_t)(32 + x % 160);
			uint32_t g = (uint32_t)(64 + y % 128);
			pixels[(size_t)y * (size_t)width + (size_t)x] = (r << 16) | (g << 8) | 0xb0;
		}
	}
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(client->shm, fd, (int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height,
		(int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

int main(int argc, char **argv) {
	const char *title = argc > 1 ? argv[1] : "wtwm-test-client";
	struct client client = {0};
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "wayland test client: connect failed: %s\n", strerror(errno));
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||
		client.shm == NULL || client.wm_base == NULL) {
		fprintf(stderr, "wayland test client: required globals are unavailable\n");
		return 1;
	}
	client.buffer = create_buffer(&client, 240, 160);
	if (client.buffer == NULL) {
		fprintf(stderr, "wayland test client: unable to create buffer\n");
		return 1;
	}
	client.surface = wl_compositor_create_surface(client.compositor);
	client.xdg_surface = xdg_wm_base_get_xdg_surface(client.wm_base, client.surface);
	xdg_surface_add_listener(client.xdg_surface, &xdg_surface_listener, &client);
	client.toplevel = xdg_surface_get_toplevel(client.xdg_surface);
	xdg_toplevel_add_listener(client.toplevel, &toplevel_listener, &client);
	xdg_toplevel_set_title(client.toplevel, title);
	xdg_toplevel_set_app_id(client.toplevel, "org.wtwm.TestClient");
	wl_surface_commit(client.surface);
	while (!client.closed && wl_display_dispatch(client.display) >= 0) {}
	xdg_toplevel_destroy(client.toplevel);
	xdg_surface_destroy(client.xdg_surface);
	wl_surface_destroy(client.surface);
	wl_buffer_destroy(client.buffer);
	xdg_wm_base_destroy(client.wm_base);
	wl_shm_destroy(client.shm);
	wl_compositor_destroy(client.compositor);
	wl_registry_destroy(registry);
	wl_display_disconnect(client.display);
	return 0;
}
