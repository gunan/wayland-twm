/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define ROLE_PROPERTY "_WTWM_REFERENCE_ROLE"

static void set_metadata(Display *display, Window window, const char *role,
		const char *title, int x, int y, int width, int height) {
	XClassHint class_hint = {.res_name = (char *)role,
		.res_class = (char *)"WtwmReference"};
	XSizeHints size_hints = {0};
	XWMHints wm_hints = {0};
	Atom role_atom = XInternAtom(display, ROLE_PROPERTY, False);

	XStoreName(display, window, title);
	XSetIconName(display, window, title);
	XSetClassHint(display, window, &class_hint);
	size_hints.flags = USPosition | USSize;
	size_hints.x = x;
	size_hints.y = y;
	size_hints.width = width;
	size_hints.height = height;
	XSetWMNormalHints(display, window, &size_hints);
	wm_hints.flags = InputHint;
	wm_hints.input = True;
	XSetWMHints(display, window, &wm_hints);
	XChangeProperty(display, window, role_atom, XA_STRING, 8, PropModeReplace,
		(const unsigned char *)role, (int)strlen(role));
}

static int wait_for_window_manager(Display *display) {
	int screen = DefaultScreen(display);
	Window root = RootWindow(display, screen);
	Window sentinel = XCreateSimpleWindow(display, root, 4, 4, 16, 16, 0,
		BlackPixel(display, screen), WhitePixel(display, screen));
	set_metadata(display, sentinel, "sentinel", "M4 Trace Readiness", 4, 4, 16, 16);
	XMapWindow(display, sentinel);
	for (int attempt = 0; attempt < 1000; ++attempt) {
		Window query_root;
		Window parent;
		Window *children = NULL;
		unsigned count = 0;
		XSync(display, False);
		if (XQueryTree(display, sentinel, &query_root, &parent, &children, &count)) {
			if (children != NULL) XFree(children);
			if (parent != root) {
				XDestroyWindow(display, sentinel);
				XSync(display, False);
				return EXIT_SUCCESS;
			}
		}
		struct timespec duration = {.tv_sec = 0, .tv_nsec = 10000000L};
		(void)nanosleep(&duration, NULL);
	}
	fprintf(stderr, "m4 trace client: twm did not reparent readiness sentinel\n");
	XDestroyWindow(display, sentinel);
	return EXIT_FAILURE;
}

static _Noreturn void run_scenario(Display *display) {
	int screen = DefaultScreen(display);
	Window root = RootWindow(display, screen);
	unsigned long black = BlackPixel(display, screen);
	unsigned long white = WhitePixel(display, screen);
	Window alpha = XCreateSimpleWindow(display, root, 30, 28, 100, 65, 0,
		black, white);
	Window bravo = XCreateSimpleWindow(display, root, 88, 58, 110, 70, 0,
		black, white);
	set_metadata(display, alpha, "alpha", "Reference Alpha", 30, 28, 100, 65);
	set_metadata(display, bravo, "bravo", "Reference Bravo", 88, 58, 110, 70);
	XSelectInput(display, alpha, ExposureMask | StructureNotifyMask);
	XSelectInput(display, bravo, ExposureMask | StructureNotifyMask);
	XMapWindow(display, alpha);
	XSync(display, False);
	XMapWindow(display, bravo);
	XSync(display, False);
	setvbuf(stdout, NULL, _IOLBF, 0);
	puts("READY");

	for (;;) {
		XEvent event;
		XNextEvent(display, &event);
		if (event.type == Expose && event.xexpose.count == 0) {
			XClearWindow(display, event.xexpose.window);
			XFlush(display);
		}
	}
}

int main(int argc, char **argv) {
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) {
		fprintf(stderr, "m4 trace client: could not open DISPLAY\n");
		return EXIT_FAILURE;
	}
	if (argc == 2 && strcmp(argv[1], "wait-wm") == 0) {
		int result = wait_for_window_manager(display);
		XCloseDisplay(display);
		return result;
	}
	if (argc == 2 && strcmp(argv[1], "scenario") == 0) run_scenario(display);
	fprintf(stderr, "usage: %s wait-wm | scenario\n", argv[0]);
	XCloseDisplay(display);
	return EXIT_FAILURE;
}
