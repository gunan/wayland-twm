#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <unistd.h>

struct visual_window {
	const char *role;
	const char *title;
	Window window;
	unsigned long accent;
	bool mapped;
};

static _Noreturn void die(const char *message) {
	fprintf(stderr, "m5 visual client: %s\n", message);
	exit(EXIT_FAILURE);
}

static unsigned long named_pixel(Display *display, const char *name) {
	XColor exact;
	XColor screen;
	if (!XAllocNamedColor(display, DefaultColormap(display,
			DefaultScreen(display)), name, &screen, &exact))
		die("could not allocate a scenario color");
	return screen.pixel;
}

static void set_utf8_title(Display *display, Window window, const char *title) {
	Atom utf8 = XInternAtom(display, "UTF8_STRING", False);
	Atom net_wm_name = XInternAtom(display, "_NET_WM_NAME", False);
	XStoreName(display, window, title);
	XSetIconName(display, window, title);
	XChangeProperty(display, window, net_wm_name, utf8, 8, PropModeReplace,
		(const unsigned char *)title, (int)strlen(title));
}

static void set_metadata(Display *display, struct visual_window *visual,
		int x, int y, int width, int height) {
	XClassHint class_hint = {
		.res_name = (char *)visual->role,
		.res_class = (char *)"WtwmReference",
	};
	XSizeHints size_hints = {
		.flags = USPosition | USSize,
		.x = x,
		.y = y,
		.width = width,
		.height = height,
	};
	XWMHints wm_hints = {
		.flags = InputHint,
		.input = True,
	};
	set_utf8_title(display, visual->window, visual->title);
	XSetClassHint(display, visual->window, &class_hint);
	XSetWMNormalHints(display, visual->window, &size_hints);
	XSetWMHints(display, visual->window, &wm_hints);
}

static void draw_windows(Display *display,
		const struct visual_window windows[static 2]) {
	GC gc = XCreateGC(display, windows[0].window, 0, NULL);
	XSetForeground(display, gc, windows[0].accent);
	XFillRectangle(display, windows[0].window, gc, 8, 8, 52, 14);
	XFillRectangle(display, windows[0].window, gc, 24, 30, 64, 20);
	XSetForeground(display, gc, windows[1].accent);
	XFillRectangle(display, windows[1].window, gc, 10, 10, 72, 16);
	XFillRectangle(display, windows[1].window, gc, 42, 34, 56, 22);
	XFreeGC(display, gc);
}

static struct visual_window *find_window(struct visual_window windows[static 2],
		const char *role) {
	for (size_t i = 0; i < 2; ++i)
		if (strcmp(windows[i].role, role) == 0) return &windows[i];
	return NULL;
}

static void handle_command(Display *display,
		struct visual_window windows[static 2], char *line) {
	line[strcspn(line, "\r\n")] = '\0';
	char *space = strchr(line, ' ');
	if (space == NULL) {
		if (strcmp(line, "QUIT") == 0) {
			puts("QUITTING");
			fflush(stdout);
			XCloseDisplay(display);
			exit(EXIT_SUCCESS);
		}
		die("invalid command");
	}
	*space++ = '\0';
	char *argument = strchr(space, ' ');
	if (argument != NULL) *argument++ = '\0';
	struct visual_window *visual = find_window(windows, space);
	if (visual == NULL) die("unknown window role");
	if (strcmp(line, "PHASE") == 0 && argument == NULL) {
		XRaiseWindow(display, visual->window);
		XSetInputFocus(display, visual->window, RevertToPointerRoot, CurrentTime);
		XSync(display, False);
		printf("PHASE %s\n", visual->role);
	} else if (strcmp(line, "TITLE") == 0) {
		set_utf8_title(display, visual->window, argument != NULL ? argument : "");
		XSync(display, False);
		printf("TITLE %s\n", visual->role);
	} else if (strcmp(line, "RAPID") == 0 && argument != NULL) {
		char *end = NULL;
		errno = 0;
		long count = strtol(argument, &end, 10);
		if (errno != 0 || end == argument || *end != '\0' || count < 1 ||
				count > 1000)
			die("invalid rapid-title count");
		char title[96];
		for (long i = 0; i < count; ++i) {
			(void)snprintf(title, sizeof(title), "rapid-title-%03ld", i);
			set_utf8_title(display, visual->window, title);
		}
		XSync(display, False);
		printf("RAPID %s %ld\n", visual->role, count);
	} else {
		die("invalid command arguments");
	}
	fflush(stdout);
}

int main(void) {
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) die("could not open DISPLAY");
	Window root = DefaultRootWindow(display);
	unsigned long black = named_pixel(display, "#101010");
	struct visual_window windows[2] = {
		{.role = "alpha", .title = "Reference Alpha",
			.accent = named_pixel(display, "#78c8ff")},
		{.role = "bravo", .title = "Reference Bravo",
			.accent = named_pixel(display, "#ffc078")},
	};
	windows[0].window = XCreateSimpleWindow(display, root, 30, 28, 100, 65,
		0, black, named_pixel(display, "#286090"));
	windows[1].window = XCreateSimpleWindow(display, root, 88, 58, 110, 70,
		0, black, named_pixel(display, "#904828"));
	set_metadata(display, &windows[0], 30, 28, 100, 65);
	set_metadata(display, &windows[1], 88, 58, 110, 70);
	for (size_t i = 0; i < 2; ++i)
		XSelectInput(display, windows[i].window,
			ExposureMask | StructureNotifyMask);
	XMapWindow(display, windows[0].window);
	XSync(display, False);
	XMapWindow(display, windows[1].window);
	XSync(display, False);

	bool ready = false;
	for (;;) {
		while (XPending(display) != 0) {
			XEvent event;
			XNextEvent(display, &event);
			for (size_t i = 0; i < 2; ++i) {
				if (event.xany.window != windows[i].window) continue;
				if (event.type == MapNotify) windows[i].mapped = true;
				if (event.type == Expose && event.xexpose.count == 0)
					draw_windows(display, windows);
			}
		}
		if (!ready && windows[0].mapped && windows[1].mapped) {
			XClearWindow(display, windows[0].window);
			XClearWindow(display, windows[1].window);
			draw_windows(display, windows);
			XSync(display, False);
			puts("READY");
			fflush(stdout);
			ready = true;
		}
		fd_set read_fds;
		FD_ZERO(&read_fds);
		FD_SET(ConnectionNumber(display), &read_fds);
		FD_SET(STDIN_FILENO, &read_fds);
		int maximum = ConnectionNumber(display) > STDIN_FILENO ?
			ConnectionNumber(display) : STDIN_FILENO;
		if (select(maximum + 1, &read_fds, NULL, NULL, NULL) < 0) {
			if (errno == EINTR) continue;
			die("select failed");
		}
		if (FD_ISSET(STDIN_FILENO, &read_fds)) {
			char line[2048];
			if (fgets(line, sizeof(line), stdin) == NULL) break;
			handle_command(display, windows, line);
		}
	}
	XCloseDisplay(display);
	return EXIT_SUCCESS;
}
