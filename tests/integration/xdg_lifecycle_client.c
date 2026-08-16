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
	struct xdg_popup *popup;
	struct wl_buffer *buffer;
	bool attach_on_configure;
	bool mapped;
	bool popup_done;
};

struct client {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct role_surface toplevel_surface;
	struct xdg_toplevel *toplevel;
	struct role_surface popup;
	struct role_surface nested_popup;
	unsigned map_generation;
	const char *title;
	const char *app_id;
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
	struct role_surface *role = data;
	role->popup_done = true;
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
	char name[] = "/wtwm-lifecycle-XXXXXX";
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
	struct role_surface *role = &client->toplevel_surface;
	if (client->map_generation > 0) {
		xdg_toplevel_set_title(client->toplevel, client->title);
		xdg_toplevel_set_app_id(client->toplevel, client->app_id);
	}
	role->attach_on_configure = true;
	role->mapped = false;
	wl_surface_commit(role->surface);
	if (!wait_until_mapped(role)) return false;
	client->map_generation++;
	printf("MAPPED %u\n", client->map_generation);
	return true;
}

static void destroy_role_surface(struct role_surface *role) {
	if (role->popup != NULL) xdg_popup_destroy(role->popup);
	if (role->xdg_surface != NULL) xdg_surface_destroy(role->xdg_surface);
	if (role->surface != NULL) wl_surface_destroy(role->surface);
	if (role->buffer != NULL) wl_buffer_destroy(role->buffer);
	struct client *client = role->client;
	*role = (struct role_surface){.client = client};
}

static void destroy_popups(struct client *client) {
	destroy_role_surface(&client->nested_popup);
	destroy_role_surface(&client->popup);
}

static bool create_popup(struct client *client, struct role_surface *role,
	struct xdg_surface *parent, int width, int height, int anchor_x, int anchor_y,
	uint32_t color) {
	*role = (struct role_surface){.client = client};
	role->buffer = create_buffer(client, width, height, color);
	role->surface = wl_compositor_create_surface(client->compositor);
	if (role->buffer == NULL || role->surface == NULL) return false;
	role->xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base, role->surface);
	if (role->xdg_surface == NULL) return false;
	xdg_surface_add_listener(role->xdg_surface, &xdg_surface_listener, role);
	struct xdg_positioner *positioner = xdg_wm_base_create_positioner(client->wm_base);
	if (positioner == NULL) return false;
	xdg_positioner_set_size(positioner, width, height);
	xdg_positioner_set_anchor_rect(positioner, anchor_x, anchor_y, 1, 1);
	xdg_positioner_set_anchor(positioner, XDG_POSITIONER_ANCHOR_BOTTOM_RIGHT);
	xdg_positioner_set_gravity(positioner, XDG_POSITIONER_GRAVITY_BOTTOM_RIGHT);
	xdg_positioner_set_constraint_adjustment(positioner,
		XDG_POSITIONER_CONSTRAINT_ADJUSTMENT_SLIDE_X |
		XDG_POSITIONER_CONSTRAINT_ADJUSTMENT_SLIDE_Y);
	role->popup = xdg_surface_get_popup(role->xdg_surface, parent, positioner);
	xdg_positioner_destroy(positioner);
	if (role->popup == NULL) return false;
	xdg_popup_add_listener(role->popup, &popup_listener, role);
	role->attach_on_configure = true;
	wl_surface_commit(role->surface);
	return wait_until_mapped(role);
}

static bool create_popups(struct client *client) {
	if (!create_popup(client, &client->popup, client->toplevel_surface.xdg_surface,
			200, 120, 220, 140, 0x0060a0d0))
		return false;
	if (!create_popup(client, &client->nested_popup, client->popup.xdg_surface,
			240, 160, 190, 110, 0x00d09050))
		return false;
	printf("POPUPS_MAPPED\n");
	return true;
}

static bool unmap_toplevel(struct client *client) {
	struct role_surface *role = &client->toplevel_surface;
	wl_surface_attach(role->surface, NULL, 0, 0);
	wl_surface_commit(role->surface);
	role->mapped = false;
	if (wl_display_roundtrip(client->display) < 0) return false;
	printf("UNMAPPED\n");
	return true;
}

static bool handle_command(struct client *client, const char *command, bool *done) {
	if (strcmp(command, "METADATA") == 0) {
		client->title = "wtwm-lifecycle-updated";
		client->app_id = "org.wtwm.LifecycleUpdated";
		xdg_toplevel_set_title(client->toplevel, client->title);
		xdg_toplevel_set_app_id(client->toplevel, client->app_id);
		if (wl_display_roundtrip(client->display) < 0) return false;
		printf("METADATA_UPDATED\n");
		return true;
	}
	if (strcmp(command, "UNMAP") == 0) return unmap_toplevel(client);
	if (strcmp(command, "REMAP") == 0) return map_toplevel(client);
	if (strcmp(command, "CREATE_POPUPS") == 0) return create_popups(client);
	if (strcmp(command, "DESTROY_POPUPS") == 0) {
		destroy_popups(client);
		if (wl_display_roundtrip(client->display) < 0) return false;
		printf("POPUPS_DESTROYED\n");
		return true;
	}
	if (strcmp(command, "DROP_DISMISSED_POPUPS") == 0) {
		if (!client->popup.popup_done || !client->nested_popup.popup_done) return false;
		destroy_popups(client);
		if (wl_display_roundtrip(client->display) < 0) return false;
		printf("DISMISSED_POPUPS_DROPPED\n");
		return true;
	}
	if (strcmp(command, "DESTROY_TOPLEVEL") == 0) {
		xdg_toplevel_destroy(client->toplevel);
		client->toplevel = NULL;
		destroy_role_surface(&client->toplevel_surface);
		if (wl_display_roundtrip(client->display) < 0) return false;
		printf("TOPLEVEL_DESTROYED\n");
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		*done = true;
		return true;
	}
	fprintf(stderr, "unknown lifecycle command: %s\n", command);
	return false;
}

static void finish_client(struct client *client) {
	destroy_popups(client);
	if (client->toplevel != NULL) xdg_toplevel_destroy(client->toplevel);
	destroy_role_surface(&client->toplevel_surface);
	if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
	if (client->shm != NULL) wl_shm_destroy(client->shm);
	if (client->compositor != NULL) wl_compositor_destroy(client->compositor);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	client.toplevel_surface.client = &client;
	client.popup.client = &client;
	client.nested_popup.client = &client;
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "xdg lifecycle client: connect failed: %s\n", strerror(errno));
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||
		client.shm == NULL || client.wm_base == NULL) {
		fprintf(stderr, "xdg lifecycle client: required globals are unavailable\n");
		return 1;
	}
	client.toplevel_surface.buffer = create_buffer(&client, 240, 160, 0x003080b0);
	client.toplevel_surface.surface = wl_compositor_create_surface(client.compositor);
	if (client.toplevel_surface.buffer == NULL ||
		client.toplevel_surface.surface == NULL) return 1;
	client.toplevel_surface.xdg_surface = xdg_wm_base_get_xdg_surface(
		client.wm_base, client.toplevel_surface.surface);
	xdg_surface_add_listener(client.toplevel_surface.xdg_surface,
		&xdg_surface_listener, &client.toplevel_surface);
	client.toplevel = xdg_surface_get_toplevel(client.toplevel_surface.xdg_surface);
	xdg_toplevel_add_listener(client.toplevel, &toplevel_listener, &client);
	client.title = "wtwm-lifecycle-initial";
	client.app_id = "org.wtwm.LifecycleInitial";
	xdg_toplevel_set_title(client.toplevel, client.title);
	xdg_toplevel_set_app_id(client.toplevel, client.app_id);
	if (!map_toplevel(&client)) return 1;

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
