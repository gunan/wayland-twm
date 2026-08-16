/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

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

struct client {
	struct wl_display *display;
	struct wl_registry *registry;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct wl_seat *seat;
	struct wl_keyboard *keyboard;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	const char *title;
	const char *app_id;
	char token[64];
	unsigned key_count;
	unsigned close_count;
	unsigned cycle;
	bool attach_on_configure;
	bool mapped;
	bool focused;
	bool armed;
};

static void wm_base_ping(void *data, struct xdg_wm_base *wm_base,
		uint32_t serial) {
	(void)data;
	xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
	.ping = wm_base_ping,
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
	(void)serial;
	(void)keys;
	struct client *client = data;
	client->focused = surface == client->surface;
	if (client->armed && client->focused)
		printf("EVENT ENTER %s\n", client->token);
}

static void keyboard_leave(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, struct wl_surface *surface) {
	(void)keyboard;
	(void)serial;
	struct client *client = data;
	if (surface != client->surface) return;
	if (client->armed) printf("EVENT LEAVE %s\n", client->token);
	client->focused = false;
}

static void keyboard_key(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, uint32_t time, uint32_t key, uint32_t state) {
	(void)keyboard;
	(void)serial;
	(void)time;
	struct client *client = data;
	if (!client->armed || !client->focused) return;
	client->key_count++;
	printf("EVENT KEY %s %" PRIu32 " %s\n", client->token, key,
		state == WL_KEYBOARD_KEY_STATE_PRESSED ? "press" : "release");
}

static void keyboard_modifiers(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, uint32_t depressed, uint32_t latched,
		uint32_t locked, uint32_t group) {
	(void)data;
	(void)keyboard;
	(void)serial;
	(void)depressed;
	(void)latched;
	(void)locked;
	(void)group;
}

static void keyboard_repeat_info(void *data, struct wl_keyboard *keyboard,
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
	.repeat_info = keyboard_repeat_info,
};

static void seat_capabilities(void *data, struct wl_seat *seat,
		uint32_t capabilities) {
	struct client *client = data;
	if ((capabilities & WL_SEAT_CAPABILITY_KEYBOARD) != 0 &&
			client->keyboard == NULL) {
		client->keyboard = wl_seat_get_keyboard(seat);
		wl_keyboard_add_listener(client->keyboard, &keyboard_listener, client);
	} else if ((capabilities & WL_SEAT_CAPABILITY_KEYBOARD) == 0 &&
			client->keyboard != NULL) {
		wl_keyboard_destroy(client->keyboard);
		client->keyboard = NULL;
		client->focused = false;
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
	} else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
		client->wm_base = wl_registry_bind(registry, name,
			&xdg_wm_base_interface, version < 3 ? version : 3);
		xdg_wm_base_add_listener(client->wm_base, &wm_base_listener, client);
	} else if (strcmp(interface, wl_seat_interface.name) == 0) {
		client->seat = wl_registry_bind(registry, name,
			&wl_seat_interface, version < 7 ? version : 7);
		wl_seat_add_listener(client->seat, &seat_listener, client);
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

static void xdg_surface_configure(void *data, struct xdg_surface *xdg_surface,
		uint32_t serial) {
	struct client *client = data;
	xdg_surface_ack_configure(xdg_surface, serial);
	if (!client->attach_on_configure) return;
	wl_surface_attach(client->surface, client->buffer, 0, 0);
	wl_surface_damage_buffer(client->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(client->surface);
	client->attach_on_configure = false;
	client->mapped = true;
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
	client->close_count++;
	printf("EVENT CLOSE %u\n", client->close_count);
}

static void toplevel_configure_bounds(void *data, struct xdg_toplevel *toplevel,
		int32_t width, int32_t height) {
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

static struct wl_buffer *create_buffer(struct client *client, int width,
		int height) {
	char name[] = "/wtwm-stress-XXXXXX";
	int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
	if (fd < 0) return NULL;
	shm_unlink(name);
	size_t stride = (size_t)width * 4;
	size_t size = stride * (size_t)height;
	if (ftruncate(fd, (off_t)size) < 0) {
		close(fd);
		return NULL;
	}
	uint32_t *pixels = mmap(NULL, size, PROT_READ | PROT_WRITE,
		MAP_SHARED, fd, 0);
	if (pixels == MAP_FAILED) {
		close(fd);
		return NULL;
	}
	for (size_t i = 0; i < size / sizeof(*pixels); ++i)
		pixels[i] = UINT32_C(0x004070b0);
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(client->shm, fd,
		(int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height,
		(int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

static bool map_client(struct client *client) {
	client->attach_on_configure = true;
	client->mapped = false;
	xdg_toplevel_set_title(client->toplevel, client->title);
	xdg_toplevel_set_app_id(client->toplevel, client->app_id);
	wl_surface_commit(client->surface);
	while (!client->mapped) {
		if (wl_display_dispatch(client->display) < 0) return false;
	}
	return wl_display_roundtrip(client->display) >= 0;
}

static bool unmap_client(struct client *client) {
	wl_surface_attach(client->surface, NULL, 0, 0);
	wl_surface_commit(client->surface);
	client->mapped = false;
	client->focused = false;
	return wl_display_roundtrip(client->display) >= 0;
}

static bool handle_command(struct client *client, char *command, bool *done) {
	char token[64];
	unsigned cycle;
	if (sscanf(command, "ARM %63s", token) == 1) {
		if (wl_display_roundtrip(client->display) < 0) return false;
		strcpy(client->token, token);
		client->key_count = 0;
		client->armed = true;
		printf("OK ARMED %s\n", client->token);
		return true;
	}
	if (sscanf(command, "REPORT %63s", token) == 1) {
		if (strcmp(token, client->token) != 0 ||
				wl_display_roundtrip(client->display) < 0) return false;
		printf("OK REPORT %s keys=%u focus=%d close=%u\n", client->token,
			client->key_count, client->focused, client->close_count);
		return true;
	}
	if (sscanf(command, "UNMAP %u", &cycle) == 1) {
		if (!client->mapped || cycle != client->cycle + 1 ||
				!unmap_client(client)) return false;
		client->cycle = cycle;
		printf("OK UNMAPPED %u\n", cycle);
		return true;
	}
	if (sscanf(command, "REMAP %u", &cycle) == 1) {
		if (client->mapped || cycle != client->cycle ||
				!map_client(client)) return false;
		printf("OK REMAPPED %u\n", cycle);
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
		puts("OK EXIT");
		*done = true;
		return true;
	}
	fprintf(stderr, "unknown stress Wayland command: %s\n", command);
	return false;
}

static void finish_client(struct client *client) {
	if (client->toplevel != NULL) xdg_toplevel_destroy(client->toplevel);
	if (client->xdg_surface != NULL) xdg_surface_destroy(client->xdg_surface);
	if (client->surface != NULL) wl_surface_destroy(client->surface);
	if (client->buffer != NULL) wl_buffer_destroy(client->buffer);
	if (client->keyboard != NULL) wl_keyboard_destroy(client->keyboard);
	if (client->seat != NULL) wl_seat_destroy(client->seat);
	if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
	if (client->shm != NULL) wl_shm_destroy(client->shm);
	if (client->compositor != NULL) wl_compositor_destroy(client->compositor);
	if (client->registry != NULL) wl_registry_destroy(client->registry);
}

int main(int argc, char **argv) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	if (argc != 3) {
		fprintf(stderr, "usage: %s TITLE APP_ID\n", argv[0]);
		return EXIT_FAILURE;
	}
	struct client client = {
		.title = argv[1],
		.app_id = argv[2],
	};
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "stress Wayland client: connect failed: %s\n",
			strerror(errno));
		return EXIT_FAILURE;
	}
	client.registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(client.registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 ||
			wl_display_roundtrip(client.display) < 0 ||
			client.compositor == NULL || client.shm == NULL ||
			client.wm_base == NULL || client.seat == NULL ||
			client.keyboard == NULL) {
		fprintf(stderr, "stress Wayland client: required globals unavailable\n");
		return EXIT_FAILURE;
	}
	client.buffer = create_buffer(&client, 180, 120);
	client.surface = wl_compositor_create_surface(client.compositor);
	if (client.buffer == NULL || client.surface == NULL) return EXIT_FAILURE;
	client.xdg_surface = xdg_wm_base_get_xdg_surface(client.wm_base,
		client.surface);
	if (client.xdg_surface == NULL) return EXIT_FAILURE;
	xdg_surface_add_listener(client.xdg_surface, &xdg_surface_listener, &client);
	client.toplevel = xdg_surface_get_toplevel(client.xdg_surface);
	if (client.toplevel == NULL) return EXIT_FAILURE;
	xdg_toplevel_add_listener(client.toplevel, &toplevel_listener, &client);
	if (!map_client(&client)) return EXIT_FAILURE;
	printf("OK READY %s\n", client.title);

	bool done = false;
	char command[128];
	while (!done) {
		if (wl_display_dispatch_pending(client.display) < 0 ||
				wl_display_flush(client.display) < 0) break;
		struct pollfd descriptors[] = {
			{.fd = wl_display_get_fd(client.display), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, -1);
		while (result < 0 && errno == EINTR);
		if (result < 0) break;
		if ((descriptors[0].revents & (POLLIN | POLLERR | POLLHUP)) != 0 &&
				wl_display_dispatch(client.display) < 0) break;
		if ((descriptors[1].revents & (POLLIN | POLLHUP)) != 0) {
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (!handle_command(&client, command, &done)) break;
		}
	}

	finish_client(&client);
	wl_display_disconnect(client.display);
	return done ? EXIT_SUCCESS : EXIT_FAILURE;
}
