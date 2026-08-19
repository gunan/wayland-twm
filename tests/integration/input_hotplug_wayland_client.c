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

struct observer {
	struct wl_display *display;
	struct wl_registry *registry;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct xdg_wm_base *wm_base;
	struct wl_seat *seat;
	struct wl_keyboard *keyboard;
	struct wl_pointer *pointer;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffer;
	char title[128];
	const char *app_id;
	char token[64];
	uint32_t capabilities;
	uint32_t depressed;
	uint32_t latched;
	uint32_t locked;
	uint32_t group;
	unsigned capability_sequence;
	unsigned keyboard_generation;
	unsigned pointer_generation;
	unsigned key_events;
	unsigned button_events;
	unsigned close_count;
	bool attach_on_configure;
	bool mapped;
	bool keyboard_focus;
	bool pointer_focus;
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
	struct observer *observer = data;
	observer->keyboard_focus = surface == observer->surface;
	if (observer->armed && observer->keyboard_focus)
		printf("EVENT KEYBOARD_ENTER %s held=%zu\n", observer->token,
			keys->size / sizeof(uint32_t));
}

static void keyboard_leave(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, struct wl_surface *surface) {
	(void)keyboard;
	(void)serial;
	struct observer *observer = data;
	if (surface != observer->surface) return;
	observer->keyboard_focus = false;
	if (observer->armed) printf("EVENT KEYBOARD_LEAVE %s\n", observer->token);
}

static void keyboard_key(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, uint32_t time, uint32_t key, uint32_t state) {
	(void)keyboard;
	(void)serial;
	(void)time;
	struct observer *observer = data;
	++observer->key_events;
	if (observer->armed)
		printf("EVENT KEY %s %" PRIu32 " %s\n", observer->token, key,
			state == WL_KEYBOARD_KEY_STATE_PRESSED ? "press" : "release");
}

static void keyboard_modifiers(void *data, struct wl_keyboard *keyboard,
		uint32_t serial, uint32_t depressed, uint32_t latched,
		uint32_t locked, uint32_t group) {
	(void)keyboard;
	(void)serial;
	struct observer *observer = data;
	observer->depressed = depressed;
	observer->latched = latched;
	observer->locked = locked;
	observer->group = group;
	if (observer->armed)
		printf("EVENT MODIFIERS %s %" PRIu32 " %" PRIu32 " %" PRIu32
			" %" PRIu32 "\n", observer->token, depressed, latched, locked,
			group);
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

static void pointer_enter(void *data, struct wl_pointer *pointer,
		uint32_t serial, struct wl_surface *surface,
		wl_fixed_t surface_x, wl_fixed_t surface_y) {
	(void)pointer;
	(void)serial;
	struct observer *observer = data;
	observer->pointer_focus = surface == observer->surface;
	if (observer->armed && observer->pointer_focus)
		printf("EVENT POINTER_ENTER %s %.3f %.3f\n", observer->token,
			wl_fixed_to_double(surface_x), wl_fixed_to_double(surface_y));
}

static void pointer_leave(void *data, struct wl_pointer *pointer,
		uint32_t serial, struct wl_surface *surface) {
	(void)pointer;
	(void)serial;
	struct observer *observer = data;
	if (surface != observer->surface) return;
	observer->pointer_focus = false;
	if (observer->armed) printf("EVENT POINTER_LEAVE %s\n", observer->token);
}

static void pointer_motion(void *data, struct wl_pointer *pointer,
		uint32_t time, wl_fixed_t surface_x, wl_fixed_t surface_y) {
	(void)pointer;
	(void)time;
	struct observer *observer = data;
	if (observer->armed)
		printf("EVENT POINTER_MOTION %s %.3f %.3f\n", observer->token,
			wl_fixed_to_double(surface_x), wl_fixed_to_double(surface_y));
}

static void pointer_button(void *data, struct wl_pointer *pointer,
		uint32_t serial, uint32_t time, uint32_t button, uint32_t state) {
	(void)pointer;
	(void)serial;
	(void)time;
	struct observer *observer = data;
	++observer->button_events;
	if (observer->armed)
		printf("EVENT BUTTON %s %" PRIu32 " %s\n", observer->token, button,
			state == WL_POINTER_BUTTON_STATE_PRESSED ? "press" : "release");
}

static void pointer_axis(void *data, struct wl_pointer *pointer,
		uint32_t time, uint32_t axis, wl_fixed_t value) {
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
	struct observer *observer = data;
	if ((capabilities & WL_SEAT_CAPABILITY_KEYBOARD) != 0 &&
			observer->keyboard == NULL) {
		observer->keyboard = wl_seat_get_keyboard(seat);
		wl_keyboard_add_listener(observer->keyboard, &keyboard_listener, observer);
		++observer->keyboard_generation;
	} else if ((capabilities & WL_SEAT_CAPABILITY_KEYBOARD) == 0 &&
			observer->keyboard != NULL) {
		wl_keyboard_destroy(observer->keyboard);
		observer->keyboard = NULL;
		observer->keyboard_focus = false;
		observer->depressed = 0;
		observer->latched = 0;
		observer->locked = 0;
		observer->group = 0;
	}
	if ((capabilities & WL_SEAT_CAPABILITY_POINTER) != 0 &&
			observer->pointer == NULL) {
		observer->pointer = wl_seat_get_pointer(seat);
		wl_pointer_add_listener(observer->pointer, &pointer_listener, observer);
		++observer->pointer_generation;
	} else if ((capabilities & WL_SEAT_CAPABILITY_POINTER) == 0 &&
			observer->pointer != NULL) {
		wl_pointer_destroy(observer->pointer);
		observer->pointer = NULL;
		observer->pointer_focus = false;
	}
	observer->capabilities = capabilities;
	++observer->capability_sequence;
	if (observer->armed)
		printf("EVENT CAPABILITIES %s keyboard=%d pointer=%d sequence=%u "
			"keyboard_generation=%u pointer_generation=%u\n", observer->token,
			(capabilities & WL_SEAT_CAPABILITY_KEYBOARD) != 0,
			(capabilities & WL_SEAT_CAPABILITY_POINTER) != 0,
			observer->capability_sequence, observer->keyboard_generation,
			observer->pointer_generation);
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
	struct observer *observer = data;
	if (strcmp(interface, wl_compositor_interface.name) == 0) {
		observer->compositor = wl_registry_bind(registry, name,
			&wl_compositor_interface, version < 5 ? version : 5);
	} else if (strcmp(interface, wl_shm_interface.name) == 0) {
		observer->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
		observer->wm_base = wl_registry_bind(registry, name,
			&xdg_wm_base_interface, version < 3 ? version : 3);
		xdg_wm_base_add_listener(observer->wm_base, &wm_base_listener, observer);
	} else if (strcmp(interface, wl_seat_interface.name) == 0) {
		observer->seat = wl_registry_bind(registry, name,
			&wl_seat_interface, version < 7 ? version : 7);
		wl_seat_add_listener(observer->seat, &seat_listener, observer);
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
	struct observer *observer = data;
	xdg_surface_ack_configure(xdg_surface, serial);
	if (!observer->attach_on_configure) return;
	wl_surface_attach(observer->surface, observer->buffer, 0, 0);
	wl_surface_damage_buffer(observer->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(observer->surface);
	observer->attach_on_configure = false;
	observer->mapped = true;
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
	struct observer *observer = data;
	++observer->close_count;
	if (observer->armed)
		printf("EVENT CLOSE %s %u\n", observer->token, observer->close_count);
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

static struct wl_buffer *create_buffer(struct observer *observer,
		int width, int height) {
	char name[] = "/wtwm-input-hotplug-XXXXXX";
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
	for (size_t index = 0; index < size / sizeof(*pixels); ++index)
		pixels[index] = UINT32_C(0x003070b0);
	munmap(pixels, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(observer->shm, fd,
		(int32_t)size);
	struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height,
		(int32_t)stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return buffer;
}

static bool initialize_window(struct observer *observer) {
	observer->buffer = create_buffer(observer, 220, 140);
	observer->surface = wl_compositor_create_surface(observer->compositor);
	if (observer->buffer == NULL || observer->surface == NULL) return false;
	observer->xdg_surface = xdg_wm_base_get_xdg_surface(observer->wm_base,
		observer->surface);
	if (observer->xdg_surface == NULL) return false;
	xdg_surface_add_listener(observer->xdg_surface,
		&xdg_surface_listener, observer);
	observer->toplevel = xdg_surface_get_toplevel(observer->xdg_surface);
	if (observer->toplevel == NULL) return false;
	xdg_toplevel_add_listener(observer->toplevel, &toplevel_listener, observer);
	xdg_toplevel_set_title(observer->toplevel, observer->title);
	xdg_toplevel_set_app_id(observer->toplevel, observer->app_id);
	observer->attach_on_configure = true;
	wl_surface_commit(observer->surface);
	while (!observer->mapped) {
		if (wl_display_dispatch(observer->display) < 0) return false;
	}
	return wl_display_roundtrip(observer->display) >= 0;
}

static bool handle_command(struct observer *observer, char *command,
		bool *done) {
	char token[64];
	if (sscanf(command, "ARM %63s", token) == 1) {
		if (wl_display_roundtrip(observer->display) < 0) return false;
		strcpy(observer->token, token);
		observer->key_events = 0;
		observer->button_events = 0;
		observer->armed = true;
		printf("OK ARMED %s\n", observer->token);
		return true;
	}
	if (sscanf(command, "REPORT %63s", token) == 1) {
		if (strcmp(token, observer->token) != 0 ||
				wl_display_roundtrip(observer->display) < 0) return false;
		printf("OK REPORT %s keyboard=%d pointer=%d cap_seq=%u "
			"key_gen=%u pointer_gen=%u keyboard_focus=%d pointer_focus=%d "
			"keys=%u buttons=%u modifiers=%" PRIu32 ",%" PRIu32 ",%" PRIu32
			",%" PRIu32 " close=%u\n", observer->token,
			(observer->capabilities & WL_SEAT_CAPABILITY_KEYBOARD) != 0,
			(observer->capabilities & WL_SEAT_CAPABILITY_POINTER) != 0,
			observer->capability_sequence, observer->keyboard_generation,
			observer->pointer_generation, observer->keyboard_focus,
			observer->pointer_focus, observer->key_events,
			observer->button_events, observer->depressed, observer->latched,
			observer->locked, observer->group, observer->close_count);
		return true;
	}
	if (strcmp(command, "EXIT") == 0) {
		puts("OK EXIT");
		*done = true;
		return true;
	}
	fprintf(stderr, "unknown input observer command: %s\n", command);
	return false;
}

static void finish_observer(struct observer *observer) {
	if (observer->toplevel != NULL) xdg_toplevel_destroy(observer->toplevel);
	if (observer->xdg_surface != NULL)
		xdg_surface_destroy(observer->xdg_surface);
	if (observer->surface != NULL) wl_surface_destroy(observer->surface);
	if (observer->buffer != NULL) wl_buffer_destroy(observer->buffer);
	if (observer->pointer != NULL) wl_pointer_destroy(observer->pointer);
	if (observer->keyboard != NULL) wl_keyboard_destroy(observer->keyboard);
	if (observer->seat != NULL) wl_seat_destroy(observer->seat);
	if (observer->wm_base != NULL) xdg_wm_base_destroy(observer->wm_base);
	if (observer->shm != NULL) wl_shm_destroy(observer->shm);
	if (observer->compositor != NULL)
		wl_compositor_destroy(observer->compositor);
	if (observer->registry != NULL) wl_registry_destroy(observer->registry);
}

int main(int argc, char **argv) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	if (argc != 3) {
		fprintf(stderr, "usage: %s TITLE APP_ID\n", argv[0]);
		return EXIT_FAILURE;
	}
	struct observer observer = {.app_id = argv[2]};
	(void)snprintf(observer.title, sizeof(observer.title), "%s", argv[1]);
	observer.display = wl_display_connect(NULL);
	if (observer.display == NULL) {
		fprintf(stderr, "input observer: connect failed: %s\n", strerror(errno));
		return EXIT_FAILURE;
	}
	observer.registry = wl_display_get_registry(observer.display);
	wl_registry_add_listener(observer.registry, &registry_listener, &observer);
	if (wl_display_roundtrip(observer.display) < 0 ||
			wl_display_roundtrip(observer.display) < 0 ||
			observer.compositor == NULL || observer.shm == NULL ||
			observer.wm_base == NULL || observer.seat == NULL) {
		fprintf(stderr, "input observer: required globals unavailable\n");
		return EXIT_FAILURE;
	}
	if (!initialize_window(&observer)) {
		fprintf(stderr, "input observer: toplevel initialization failed\n");
		return EXIT_FAILURE;
	}
	printf("OK READY %s keyboard=%d pointer=%d cap_seq=%u key_gen=%u "
		"pointer_gen=%u\n", observer.title,
		(observer.capabilities & WL_SEAT_CAPABILITY_KEYBOARD) != 0,
		(observer.capabilities & WL_SEAT_CAPABILITY_POINTER) != 0,
		observer.capability_sequence, observer.keyboard_generation,
		observer.pointer_generation);

	bool done = false;
	char command[128];
	while (!done) {
		if (wl_display_dispatch_pending(observer.display) < 0 ||
				wl_display_flush(observer.display) < 0) break;
		struct pollfd descriptors[] = {
			{.fd = wl_display_get_fd(observer.display), .events = POLLIN},
			{.fd = STDIN_FILENO, .events = POLLIN},
		};
		int result;
		do result = poll(descriptors, 2, -1);
		while (result < 0 && errno == EINTR);
		if (result < 0) break;
		if ((descriptors[0].revents & (POLLIN | POLLERR | POLLHUP)) != 0 &&
				wl_display_dispatch(observer.display) < 0) break;
		if ((descriptors[1].revents & (POLLIN | POLLHUP)) != 0) {
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (!handle_command(&observer, command, &done)) break;
		}
	}

	finish_observer(&observer);
	wl_display_disconnect(observer.display);
	return done ? EXIT_SUCCESS : EXIT_FAILURE;
}
