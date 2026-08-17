/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <unistd.h>

struct client_window {
	const char *instance;
	const char *title;
	Window window;
};

static _Noreturn void fail(const char *message) {
	fprintf(stderr, "m7 icon differential client: %s\n", message);
	exit(EXIT_FAILURE);
}

static unsigned long named_pixel(Display *display, const char *name) {
	XColor exact;
	XColor screen;
	if (!XAllocNamedColor(display, DefaultColormap(display,
			DefaultScreen(display)), name, &screen, &exact))
		fail("could not allocate client color");
	return screen.pixel;
}

static void set_metadata(Display *display, struct client_window *client,
		int x, int y, int width, int height) {
	XClassHint class_hint = {
		.res_name = (char *)client->instance,
		.res_class = (char *)"WtwmM7Differential",
	};
	XSizeHints size_hints = {
		.flags = USPosition | USSize,
		.x = x,
		.y = y,
		.width = width,
		.height = height,
	};
	XWMHints wm_hints = {.flags = InputHint, .input = True};
	XStoreName(display, client->window, client->title);
	XSetIconName(display, client->window, client->title);
	XSetClassHint(display, client->window, &class_hint);
	XSetWMNormalHints(display, client->window, &size_hints);
	XSetWMHints(display, client->window, &wm_hints);
}

int main(void) {
	setvbuf(stdout, NULL, _IOLBF, 0);
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) fail("could not open DISPLAY");
	Window root = DefaultRootWindow(display);
	struct client_window clients[2] = {
		{.instance = "m7-alpha", .title = "Reference Alpha"},
		{.instance = "m7-bravo", .title = "Reference Bravo"},
	};
	clients[0].window = XCreateSimpleWindow(display, root, 30, 80, 120, 70,
		0, named_pixel(display, "#101010"), named_pixel(display, "#286090"));
	clients[1].window = XCreateSimpleWindow(display, root, 180, 80, 120, 70,
		0, named_pixel(display, "#101010"), named_pixel(display, "#904828"));
	set_metadata(display, &clients[0], 30, 80, 120, 70);
	set_metadata(display, &clients[1], 180, 80, 120, 70);
	for (size_t index = 0; index < 2; ++index) {
		XSelectInput(display, clients[index].window,
			ExposureMask | StructureNotifyMask);
		XMapWindow(display, clients[index].window);
		XSync(display, False);
	}
	/* StartIconified legitimately suppresses a client MapNotify under twm. */
	puts("READY");

	bool running = true;
	while (running) {
		while (XPending(display) != 0) {
			XEvent event;
			XNextEvent(display, &event);
		}
		fd_set descriptors;
		FD_ZERO(&descriptors);
		FD_SET(ConnectionNumber(display), &descriptors);
		FD_SET(STDIN_FILENO, &descriptors);
		int maximum = ConnectionNumber(display) > STDIN_FILENO ?
			ConnectionNumber(display) : STDIN_FILENO;
		int result = select(maximum + 1, &descriptors, NULL, NULL, NULL);
		if (result < 0) {
			if (errno == EINTR) continue;
			fail("select failed");
		}
		if (FD_ISSET(STDIN_FILENO, &descriptors)) {
			char command[64];
			if (fgets(command, sizeof(command), stdin) == NULL) break;
			command[strcspn(command, "\r\n")] = '\0';
			if (strcmp(command, "QUIT") != 0) fail("invalid command");
			puts("QUITTING");
			running = false;
		}
	}
	for (size_t index = 0; index < 2; ++index)
		XDestroyWindow(display, clients[index].window);
	XCloseDisplay(display);
	return EXIT_SUCCESS;
}
