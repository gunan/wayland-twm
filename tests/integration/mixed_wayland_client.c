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

enum role_index {
	ROLE_NATIVE_A,
	ROLE_NATIVE_B,
	ROLE_COUNT,
};

struct client;

struct role {
	struct client *client;
	const char *name;
	const char *title;
	const char *app_id;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	bool attach_on_configure;
	bool mapped;
	bool activated;
};

struct client {
	struct wl_display *display;
	struct wl_registry *registry;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct wl_seat *seat;
	struct wl_keyboard *keyboard;
	struct role roles[ROLE_COUNT];
	struct role *keyboard_role;
	char token[64];
	unsigned key_count[ROLE_COUNT];
	bool armed;
	bool closed;
};

static struct role *role_for_surface(struct client *client,
		struct wl_surface *surface) {
	for (size_t i = 0; i < ROLE_COUNT; ++i) {
		if (client->roles[i].surface == surface) return &client->roles[i];
	}
	return NULL;
}

static size_t role_index(const struct client *client, const struct role *role) {
	return (size_t)(role - client->roles);
}

static struct role *role_named(struct client *client, const char *name) {
	for (size_t i = 0; i < ROLE_COUNT; ++i) {
		if (strcmp(client->roles[i].name, name) == 0) return &client->roles[i];
	}
	return NULL;
}

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
	client->keyboard_role = role_for_surface(client, surface);
	if (client->armed && client->keyboard_role != NULL) {
		printf("EVENT ENTER %s %s\n", client->token,
			client->keyboard_role->name);
	}
}

static void keyboard_leave(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, struct wl_surface *surface) {
	(void)keyboard;
	(void)serial;
	struct client *client = data;
	struct role *role = role_for_surface(client, surface);
	if (client->armed && role != NULL)
		printf("EVENT LEAVE %s %s\n", client->token, role->name);
	if (client->keyboard_role == role) client->keyboard_role = NULL;
}

static void keyboard_key(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, uint32_t time, uint32_t key, uint32_t state) {
	(void)keyboard;
	(void)serial;
	(void)time;
	struct client *client = data;
	if (!client->armed || client->keyboard_role == NULL) return;
	client->key_count[role_index(client, client->keyboard_role)]++;
	printf("EVENT KEY %s %s %" PRIu32 " %s\n", client->token,
		client->keyboard_role->name, key,
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
		client->keyboard_role = NULL;
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
	struct role *role = data;
	xdg_surface_ack_configure(xdg_surface, serial);
	if (!role->attach_on_configure) return;
	wl_surface_attach(role->surface, role->buffer, 0, 0);
	wl_surface_damage_buffer(role->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(role->surface);
	role->attach_on_configure = false;
	role->mapped = true;
}

static const struct xdg_surface_listener xdg_surface_listener = {
	.configure = xdg_surface_configure,
};

static void toplevel_configure(void *data, struct xdg_toplevel *toplevel,
		int32_t width, int32_t height, struct wl_array *states) {
	(void)toplevel;
	(void)width;
	(void)height;
	struct role *role = data;
	role->activated = false;
	uint32_t *state;
	wl_array_for_each(state, states) {
		if (*state == XDG_TOPLEVEL_STATE_ACTIVATED) role->activated = true;
	}
}

static void toplevel_close(void *data, struct xdg_toplevel *toplevel) {
	(void)toplevel;
	struct role *role = data;
	role->client->closed = true;
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
		int height, uint32_t color) {
	char name[] = "/wtwm-mixed-XXXXXX";
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
	for (size_t i = 0; i < size / sizeof(*pixels); ++i) pixels[i] = color;
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(client->shm, fd, (int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height,
		(int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

static bool wait_until_mapped(struct role *role) {
	while (!role->mapped && !role->client->closed) {
		if (wl_display_dispatch(role->client->display) < 0) return false;
	}
	return role->mapped && wl_display_roundtrip(role->client->display) >= 0;
}

static bool map_role(struct role *role) {
	role->attach_on_configure = true;
	role->mapped = false;
	xdg_toplevel_set_title(role->toplevel, role->title);
	xdg_toplevel_set_app_id(role->toplevel, role->app_id);
	wl_surface_commit(role->surface);
	return wait_until_mapped(role);
}

static bool unmap_role(struct role *role) {
	wl_surface_attach(role->surface, NULL, 0, 0);
	wl_surface_commit(role->surface);
	role->mapped = false;
	return wl_display_roundtrip(role->client->display) >= 0;
}

static bool initialize_role(struct client *client, enum role_index index,
		const char *name, const char *title, const char *app_id,
		uint32_t color) {
	struct role *role = &client->roles[index];
	*role = (struct role){
		.client = client,
		.name = name,
		.title = title,
		.app_id = app_id,
	};
	role->buffer = create_buffer(client, 180, 120, color);
	role->surface = wl_compositor_create_surface(client->compositor);
	if (role->buffer == NULL || role->surface == NULL) return false;
	role->xdg_surface = xdg_wm_base_get_xdg_surface(client->wm_base, role->surface);
	if (role->xdg_surface == NULL) return false;
	xdg_surface_add_listener(role->xdg_surface, &xdg_surface_listener, role);
	role->toplevel = xdg_surface_get_toplevel(role->xdg_surface);
	if (role->toplevel == NULL) return false;
	xdg_toplevel_add_listener(role->toplevel, &toplevel_listener, role);
	return map_role(role);
}

static bool handle_command(struct client *client, char *command, bool *done) {
	char name[64];
	if (sscanf(command, "ARM %63s", name) == 1) {
		if (wl_display_roundtrip(client->display) < 0) return false;
		strcpy(client->token, name);
		memset(client->key_count, 0, sizeof(client->key_count));
		client->armed = true;
		printf("OK ARMED %s\n", client->token);
		return true;
	}
	if (sscanf(command, "REPORT %63s", name) == 1) {
		if (strcmp(name, client->token) != 0 ||
				wl_display_roundtrip(client->display) < 0) return false;
		printf("OK REPORT %s native-a=%u native-b=%u focus=%s active-a=%d active-b=%d\n",
			client->token, client->key_count[ROLE_NATIVE_A],
			client->key_count[ROLE_NATIVE_B],
			client->keyboard_role != NULL ? client->keyboard_role->name : "none",
			client->roles[ROLE_NATIVE_A].activated,
			client->roles[ROLE_NATIVE_B].activated);
		return true;
	}
	if (sscanf(command, "UNMAP %63s", name) == 1) {
		struct role *role = role_named(client, name);
		if (role == NULL || !role->mapped || !unmap_role(role)) return false;
		printf("OK UNMAPPED %s\n", role->name);
		return true;
	}
	if (sscanf(command, "REMAP %63s", name) == 1) {
		struct role *role = role_named(client, name);
		if (role == NULL || role->mapped || !map_role(role)) return false;
		printf("OK REMAPPED %s\n", role->name);
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		printf("OK EXIT\n");
		*done = true;
		return true;
	}
	fprintf(stderr, "unknown mixed Wayland command: %s\n", command);
	return false;
}

static void finish_role(struct role *role) {
	if (role->toplevel != NULL) xdg_toplevel_destroy(role->toplevel);
	if (role->xdg_surface != NULL) xdg_surface_destroy(role->xdg_surface);
	if (role->surface != NULL) wl_surface_destroy(role->surface);
	if (role->buffer != NULL) wl_buffer_destroy(role->buffer);
}

static void finish_client(struct client *client) {
	for (size_t i = 0; i < ROLE_COUNT; ++i) finish_role(&client->roles[i]);
	if (client->keyboard != NULL) wl_keyboard_destroy(client->keyboard);
	if (client->seat != NULL) wl_seat_destroy(client->seat);
	if (client->wm_base != NULL) xdg_wm_base_destroy(client->wm_base);
	if (client->shm != NULL) wl_shm_destroy(client->shm);
	if (client->compositor != NULL) wl_compositor_destroy(client->compositor);
	if (client->registry != NULL) wl_registry_destroy(client->registry);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct client client = {0};
	client.display = wl_display_connect(NULL);
	if (client.display == NULL) {
		fprintf(stderr, "mixed Wayland client: connect failed: %s\n",
			strerror(errno));
		return EXIT_FAILURE;
	}
	client.registry = wl_display_get_registry(client.display);
	wl_registry_add_listener(client.registry, &registry_listener, &client);
	if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||
			client.shm == NULL || client.wm_base == NULL || client.seat == NULL ||
			client.keyboard == NULL) {
		fprintf(stderr, "mixed Wayland client: required globals unavailable\n");
		return EXIT_FAILURE;
	}
	if (!initialize_role(&client, ROLE_NATIVE_A, "native-a",
			"wtwm-mixed-native-a", "org.wtwm.MixedNativeA", UINT32_C(0x004080c0)) ||
			!initialize_role(&client, ROLE_NATIVE_B, "native-b",
			"wtwm-mixed-native-b", "org.wtwm.MixedNativeB", UINT32_C(0x00c07030))) {
		fprintf(stderr, "mixed Wayland client: toplevel initialization failed\n");
		return EXIT_FAILURE;
	}
	puts("OK READY native-a native-b");

	bool done = false;
	char command[128];
	while (!done && !client.closed) {
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
