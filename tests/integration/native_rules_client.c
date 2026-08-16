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

enum window_id {
	WINDOW_TITLE,
	WINDOW_APP_ID,
	WINDOW_TITLE_CASE,
	WINDOW_APP_ID_CASE,
	WINDOW_LITERAL_STAR,
	WINDOW_COLLISION,
	WINDOW_AUTO_RAISE,
	WINDOW_START_ICONIFIED,
	WINDOW_PLAIN,
	WINDOW_COUNT,
};

struct client;

struct window {
	struct client *client;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	const char *title;
	const char *app_id;
	bool attach_on_configure;
	bool mapped;
};

struct client {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct window windows[WINDOW_COUNT];
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

static void surface_configure(void *data, struct xdg_surface *surface,
	uint32_t serial) {
	struct window *window = data;
	xdg_surface_ack_configure(surface, serial);
	if (!window->attach_on_configure) return;
	wl_surface_attach(window->surface, window->buffer, 0, 0);
	wl_surface_damage_buffer(window->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(window->surface);
	window->attach_on_configure = false;
	window->mapped = true;
}

static const struct xdg_surface_listener surface_listener = {
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
	struct window *window = data;
	window->client->closed = true;
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

static struct wl_buffer *create_buffer(struct client *client, uint32_t color) {
	char name[] = "/wtwm-native-rules-XXXXXX";
	int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
	if (fd < 0) return NULL;
	shm_unlink(name);
	const int width = 160;
	const int height = 100;
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

static bool wait_until_mapped(struct window *window) {
	while (!window->mapped && !window->client->closed) {
		if (wl_display_dispatch(window->client->display) < 0) return false;
	}
	return window->mapped && wl_display_roundtrip(window->client->display) >= 0;
}

static void set_metadata(struct window *window, const char *title,
	const char *app_id) {
	window->title = title;
	window->app_id = app_id;
	xdg_toplevel_set_title(window->toplevel, title);
	xdg_toplevel_set_app_id(window->toplevel, app_id);
}

static bool map_window(struct window *window) {
	xdg_toplevel_set_title(window->toplevel, window->title);
	xdg_toplevel_set_app_id(window->toplevel, window->app_id);
	window->attach_on_configure = true;
	window->mapped = false;
	wl_surface_commit(window->surface);
	return wait_until_mapped(window);
}

static bool unmap_window(struct window *window) {
	wl_surface_attach(window->surface, NULL, 0, 0);
	wl_surface_commit(window->surface);
	window->mapped = false;
	return wl_display_roundtrip(window->client->display) >= 0;
}

static bool create_window(struct client *client, enum window_id id,
	const char *title, const char *app_id) {
	struct window *window = &client->windows[id];
	window->client = client;
	window->buffer = create_buffer(client, 0x00204060u + (uint32_t)id * 0x000d0903u);
	window->surface = wl_compositor_create_surface(client->compositor);
	if (window->buffer == NULL || window->surface == NULL) return false;
	window->xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base,
		window->surface);
	if (window->xdg_surface == NULL) return false;
	xdg_surface_add_listener(window->xdg_surface, &surface_listener, window);
	window->toplevel = xdg_surface_get_toplevel(window->xdg_surface);
	if (window->toplevel == NULL) return false;
	xdg_toplevel_add_listener(window->toplevel, &toplevel_listener, window);
	set_metadata(window, title, app_id);
	return map_window(window);
}

static bool sync_metadata(struct window *window, const char *title,
	const char *app_id) {
	set_metadata(window, title, app_id);
	return wl_display_roundtrip(window->client->display) >= 0;
}

static bool handle_command(struct client *client, const char *command, bool *done) {
	struct window *plain = &client->windows[WINDOW_PLAIN];
	struct window *auto_raise = &client->windows[WINDOW_AUTO_RAISE];
	struct window *start = &client->windows[WINDOW_START_ICONIFIED];
	if (strcmp(command, "UPDATE_PLAIN_TITLE") == 0) {
		if (!sync_metadata(plain, "NativeTitle", "org.wtwm.Plain")) return false;
		printf("PLAIN_TITLE_UPDATED\n");
		return true;
	}
	if (strcmp(command, "UPDATE_PLAIN_APP_ID") == 0) {
		if (!sync_metadata(plain, "Plain Window", "org.wtwm.NativeApp")) return false;
		printf("PLAIN_APP_ID_UPDATED\n");
		return true;
	}
	if (strcmp(command, "RESET_PLAIN") == 0) {
		if (!sync_metadata(plain, "Plain Window", "org.wtwm.Plain")) return false;
		printf("PLAIN_RESET\n");
		return true;
	}
	if (strcmp(command, "UPDATE_AUTO_APP_ID") == 0) {
		if (!sync_metadata(auto_raise, "Auto Window", "org.wtwm.NoAutoRaise"))
			return false;
		printf("AUTO_APP_ID_UPDATED\n");
		return true;
	}
	if (strcmp(command, "UNMAP_AUTO") == 0) {
		if (!unmap_window(auto_raise)) return false;
		printf("AUTO_UNMAPPED\n");
		return true;
	}
	if (strcmp(command, "REMAP_AUTO") == 0) {
		if (!map_window(auto_raise)) return false;
		printf("AUTO_REMAPPED\n");
		return true;
	}
	if (strcmp(command, "UNMAP_START") == 0) {
		if (!unmap_window(start)) return false;
		printf("START_UNMAPPED\n");
		return true;
	}
	if (strcmp(command, "REMAP_START") == 0) {
		if (!map_window(start)) return false;
		printf("START_REMAPPED\n");
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		*done = true;
		return true;
	}
	fprintf(stderr, "unknown native rules command: %s\n", command);
	return false;
}

static void finish_client(struct client *client) {
	for (size_t i = 0; i < WINDOW_COUNT; ++i) {
		struct window *window = &client->windows[i];
		if (window->toplevel != NULL) xdg_toplevel_destroy(window->toplevel);
		if (window->xdg_surface != NULL) xdg_surface_destroy(window->xdg_surface);
		if (window->surface != NULL) wl_surface_destroy(window->surface);
		if (window->buffer != NULL) wl_buffer_destroy(window->buffer);
	}
	if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
	if (client->shm != NULL) wl_shm_destroy(client->shm);
	if (client->compositor != NULL) wl_compositor_destroy(client->compositor);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "native rules client: connect failed: %s\n", strerror(errno));
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||
		client.shm == NULL || client.wm_base == NULL) {
		fprintf(stderr, "native rules client: required globals are unavailable\n");
		return 1;
	}
	if (!create_window(&client, WINDOW_TITLE, "NativeTitle", "org.wtwm.Title") ||
		!create_window(&client, WINDOW_APP_ID, "App Window", "org.wtwm.NativeApp") ||
		!create_window(&client, WINDOW_TITLE_CASE, "nativecase",
			"org.wtwm.TitleCase") ||
		!create_window(&client, WINDOW_APP_ID_CASE, "Case App Window",
			"org.wtwm.nativecase") ||
		!create_window(&client, WINDOW_LITERAL_STAR, "*", "org.wtwm.Star") ||
		!create_window(&client, WINDOW_COLLISION, "Collision Window",
			"org.wtwm.Collision") ||
		!create_window(&client, WINDOW_AUTO_RAISE, "Auto Window",
			"org.wtwm.AutoRaise") ||
		!create_window(&client, WINDOW_START_ICONIFIED, "Start Window",
			"org.wtwm.StartIconified") ||
		!create_window(&client, WINDOW_PLAIN, "Plain Window", "org.wtwm.Plain")) {
		fprintf(stderr, "native rules client: window creation failed\n");
		return 1;
	}
	printf("READY\n");

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
