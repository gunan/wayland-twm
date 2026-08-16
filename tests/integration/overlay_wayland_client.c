/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "xdg-shell-client-protocol.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>

struct client;

struct role_surface {
	struct client *client;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct wl_buffer *buffer;
	bool attach_on_configure;
	bool mapped;
};

struct client {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct role_surface toplevel_surface;
	struct xdg_toplevel *toplevel;
	struct role_surface popup_surface;
	struct xdg_popup *popup;
	bool closed;
	bool popup_done;
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

static void role_surface_configure(void *data, struct xdg_surface *surface,
		uint32_t serial) {
	struct role_surface *role = data;
	xdg_surface_ack_configure(surface, serial);
	if (!role->attach_on_configure) return;
	wl_surface_attach(role->surface, role->buffer, 0, 0);
	wl_surface_damage_buffer(role->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(role->surface);
	role->attach_on_configure = false;
	role->mapped = true;
}

static const struct xdg_surface_listener xdg_surface_listener = {
	.configure = role_surface_configure,
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

static void popup_configure(void *data, struct xdg_popup *popup,
		int32_t x, int32_t y, int32_t width, int32_t height) {
	(void)data;
	(void)popup;
	(void)x;
	(void)y;
	(void)width;
	(void)height;
}

static void popup_done(void *data, struct xdg_popup *popup) {
	(void)popup;
	struct client *client = data;
	client->popup_done = true;
}

static void popup_repositioned(void *data, struct xdg_popup *popup,
		uint32_t token) {
	(void)data;
	(void)popup;
	(void)token;
}

static const struct xdg_popup_listener popup_listener = {
	.configure = popup_configure,
	.popup_done = popup_done,
	.repositioned = popup_repositioned,
};

static struct wl_buffer *create_buffer(struct client *client, int width, int height,
		uint32_t color) {
	char name[] = "/wtwm-overlay-XXXXXX";
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
	for (size_t i = 0; i < size / sizeof(*pixels); ++i) pixels[i] = color;
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(client->shm, fd, (int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height,
		(int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

static bool wait_until_mapped(struct role_surface *role) {
	while (!role->mapped && !role->client->closed) {
		if (wl_display_dispatch(role->client->display) < 0) return false;
	}
	return role->mapped && wl_display_roundtrip(role->client->display) >= 0;
}

static bool map_toplevel(struct client *client) {
	xdg_toplevel_set_title(client->toplevel, "overlay-native");
	xdg_toplevel_set_app_id(client->toplevel, "org.wtwm.OverlayNative");
	client->toplevel_surface.attach_on_configure = true;
	client->toplevel_surface.mapped = false;
	wl_surface_commit(client->toplevel_surface.surface);
	return wait_until_mapped(&client->toplevel_surface);
}

static void destroy_popup(struct client *client) {
	if (client->popup != NULL) xdg_popup_destroy(client->popup);
	if (client->popup_surface.xdg_surface != NULL)
		xdg_surface_destroy(client->popup_surface.xdg_surface);
	if (client->popup_surface.surface != NULL)
		wl_surface_destroy(client->popup_surface.surface);
	if (client->popup_surface.buffer != NULL)
		wl_buffer_destroy(client->popup_surface.buffer);
	client->popup = NULL;
	client->popup_surface = (struct role_surface){.client = client};
}

static bool map_popup(struct client *client) {
	if (client->popup != NULL) return false;
	struct role_surface *role = &client->popup_surface;
	*role = (struct role_surface){.client = client};
	role->buffer = create_buffer(client, 260, 200, UINT32_C(0x0000cc44));
	role->surface = wl_compositor_create_surface(client->compositor);
	if (role->buffer == NULL || role->surface == NULL) return false;
	role->xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base, role->surface);
	if (role->xdg_surface == NULL) return false;
	xdg_surface_add_listener(role->xdg_surface, &xdg_surface_listener, role);
	struct xdg_positioner *positioner = xdg_wm_base_create_positioner(client->wm_base);
	if (positioner == NULL) return false;
	xdg_positioner_set_size(positioner, 260, 200);
	xdg_positioner_set_anchor_rect(positioner, 80, 70, 1, 1);
	xdg_positioner_set_anchor(positioner, XDG_POSITIONER_ANCHOR_TOP_LEFT);
	xdg_positioner_set_gravity(positioner, XDG_POSITIONER_GRAVITY_BOTTOM_RIGHT);
	client->popup = xdg_surface_get_popup(role->xdg_surface,
		client->toplevel_surface.xdg_surface, positioner);
	xdg_positioner_destroy(positioner);
	if (client->popup == NULL) return false;
	xdg_popup_add_listener(client->popup, &popup_listener, client);
	client->popup_done = false;
	role->attach_on_configure = true;
	wl_surface_commit(role->surface);
	return wait_until_mapped(role);
}

static bool unmap_toplevel(struct client *client) {
	wl_surface_attach(client->toplevel_surface.surface, NULL, 0, 0);
	wl_surface_commit(client->toplevel_surface.surface);
	client->toplevel_surface.mapped = false;
	return wl_display_roundtrip(client->display) >= 0;
}

static bool handle_command(struct client *client, const char *command, bool *done) {
	if (strcmp(command, "MAP_POPUP") == 0) {
		if (!map_popup(client)) return false;
		puts("POPUP_MAPPED");
		return true;
	}
	if (strcmp(command, "DESTROY_POPUP") == 0) {
		destroy_popup(client);
		if (wl_display_roundtrip(client->display) < 0) return false;
		puts("POPUP_DESTROYED");
		return true;
	}
	if (strcmp(command, "UNMAP_TOPLEVEL") == 0) {
		if (!unmap_toplevel(client)) return false;
		puts("TOPLEVEL_UNMAPPED");
		return true;
	}
	if (strcmp(command, "DROP_DISMISSED_POPUP") == 0) {
		if (!client->popup_done) return false;
		destroy_popup(client);
		if (wl_display_roundtrip(client->display) < 0) return false;
		puts("DISMISSED_POPUP_DROPPED");
		return true;
	}
	if (strcmp(command, "REMAP_TOPLEVEL") == 0) {
		if (!map_toplevel(client)) return false;
		puts("TOPLEVEL_REMAPPED");
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		*done = true;
		puts("EXITING");
		return true;
	}
	fprintf(stderr, "unknown overlay Wayland command: %s\n", command);
	return false;
}

static void finish_client(struct client *client) {
	destroy_popup(client);
	if (client->toplevel != NULL) xdg_toplevel_destroy(client->toplevel);
	if (client->toplevel_surface.xdg_surface != NULL)
		xdg_surface_destroy(client->toplevel_surface.xdg_surface);
	if (client->toplevel_surface.surface != NULL)
		wl_surface_destroy(client->toplevel_surface.surface);
	if (client->toplevel_surface.buffer != NULL)
		wl_buffer_destroy(client->toplevel_surface.buffer);
	if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
	if (client->shm != NULL) wl_shm_destroy(client->shm);
	if (client->compositor != NULL) wl_compositor_destroy(client->compositor);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	client.toplevel_surface.client = &client;
	client.popup_surface.client = &client;
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "overlay Wayland client: connect failed: %s\n", strerror(errno));
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||
			client.shm == NULL || client.wm_base == NULL) return 1;
	client.toplevel_surface.buffer = create_buffer(
		&client, 320, 240, UINT32_C(0x00204080));
	client.toplevel_surface.surface = wl_compositor_create_surface(client.compositor);
	if (client.toplevel_surface.buffer == NULL ||
			client.toplevel_surface.surface == NULL) return 1;
	client.toplevel_surface.xdg_surface = xdg_wm_base_get_xdg_surface(
		client.wm_base, client.toplevel_surface.surface);
	xdg_surface_add_listener(client.toplevel_surface.xdg_surface,
		&xdg_surface_listener, &client.toplevel_surface);
	client.toplevel = xdg_surface_get_toplevel(client.toplevel_surface.xdg_surface);
	xdg_toplevel_add_listener(client.toplevel, &toplevel_listener, &client);
	if (!map_toplevel(&client)) return 1;
	puts("READY");

	bool done = false;
	char command[128];
	while (!done && !client.closed) {
		if (wl_display_dispatch_pending(client.display) < 0 ||
				wl_display_flush(client.display) < 0) break;
		struct pollfd descriptors[] = {
			{.fd = wl_display_get_fd(client.display), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		if (poll(descriptors, 2, -1) < 0) {
			if (errno == EINTR) continue;
			break;
		}
		if ((descriptors[0].revents & (POLLIN | POLLERR | POLLHUP)) != 0 &&
				wl_display_dispatch(client.display) < 0) break;
		if ((descriptors[1].revents & (POLLIN | POLLHUP)) != 0) {
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (!handle_command(&client, command, &done)) break;
		}
	}
	finish_client(&client);
	wl_registry_destroy(registry);
	wl_display_disconnect(client.display);
	return done ? 0 : 1;
}
