/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define REQUIRED_STABLE_OBSERVATIONS 3
#define MAX_OBSERVATIONS 1500

struct geometry {
	int root_x;
	int root_y;
	unsigned int width;
	unsigned int height;
	unsigned int border_width;
	int map_state;
};

struct observation {
	struct geometry client;
	struct geometry frame;
	bool title_present;
	struct geometry title;
};

static _Noreturn void die(const char *message) {
	fprintf(stderr, "geometry matrix client: %s\n", message);
	exit(EXIT_FAILURE);
}

static int parse_nonnegative(const char *text, const char *name) {
	char *end = NULL;
	long value;

	errno = 0;
	value = strtol(text, &end, 10);
	if (errno != 0 || end == text || *end != '\0' || value < 0 ||
		value > INT_MAX) {
		fprintf(stderr, "geometry matrix client: invalid %s: %s\n", name, text);
		exit(EXIT_FAILURE);
	}
	return (int)value;
}

static void pause_briefly(void) {
	struct timespec duration = {.tv_sec = 0, .tv_nsec = 10000000L};

	while (nanosleep(&duration, &duration) != 0 && errno == EINTR) {
	}
}

static void set_metadata(Display *display, Window window, const char *instance,
		const char *title, int x, int y, int width, int height,
		const char *hint_profile) {
	XClassHint class_hint = {0};
	XSizeHints hints = {0};
	XWMHints wm_hints = {0};

	XStoreName(display, window, title);
	class_hint.res_name = (char *)instance;
	class_hint.res_class = (char *)"WtwmGeometryMatrix";
	XSetClassHint(display, window, &class_hint);

	hints.flags = USPosition | USSize;
	hints.x = x;
	hints.y = y;
	hints.width = width;
	hints.height = height;
	if (strcmp(hint_profile, "position-size") == 0) {
		/* The positioning flags are the intentionally minimal profile. */
	}
	else if (strcmp(hint_profile, "min-max") == 0) {
		hints.flags |= PMinSize | PMaxSize;
		hints.min_width = 80;
		hints.min_height = 60;
		hints.max_width = 240;
		hints.max_height = 180;
	}
	else if (strcmp(hint_profile, "base-increment") == 0) {
		hints.flags |= PBaseSize | PResizeInc;
		hints.base_width = 17;
		hints.base_height = 11;
		hints.width_inc = 10;
		hints.height_inc = 7;
	}
	else if (strcmp(hint_profile, "complete") == 0) {
		hints.flags |= PMinSize | PMaxSize | PBaseSize | PResizeInc | PAspect;
		hints.min_width = 73;
		hints.min_height = 52;
		hints.max_width = 263;
		hints.max_height = 187;
		hints.base_width = 13;
		hints.base_height = 9;
		hints.width_inc = 8;
		hints.height_inc = 6;
		hints.min_aspect.x = 4;
		hints.min_aspect.y = 3;
		hints.max_aspect.x = 16;
		hints.max_aspect.y = 9;
	}
	else {
		die("unknown normal-hints profile");
	}
	XSetWMNormalHints(display, window, &hints);

	wm_hints.flags = InputHint;
	wm_hints.input = True;
	XSetWMHints(display, window, &wm_hints);
}

static bool query_parent(Display *display, Window window, Window *parent) {
	Window root;
	Window *children = NULL;
	unsigned int child_count = 0;
	Status status = XQueryTree(display, window, &root, parent, &children,
		&child_count);

	if (children != NULL) {
		XFree(children);
	}
	return status != 0;
}

static bool read_geometry(Display *display, Window root, Window window,
		struct geometry *result) {
	XWindowAttributes attributes;
	Window child;

	if (!XGetWindowAttributes(display, window, &attributes) ||
		!XTranslateCoordinates(display, window, root, 0, 0,
			&result->root_x, &result->root_y, &child)) {
		return false;
	}
	result->width = (unsigned int)attributes.width;
	result->height = (unsigned int)attributes.height;
	result->border_width = (unsigned int)attributes.border_width;
	result->map_state = attributes.map_state;
	return true;
}

static bool collect_observation(Display *display, Window client,
		bool expected_title, struct observation *result) {
	Window root = DefaultRootWindow(display);
	Window parent;
	Window frame;
	Window query_root;
	Window *children = NULL;
	unsigned int child_count = 0;
	unsigned int title_count = 0;

	if (!query_parent(display, client, &parent) || parent == None || parent == root) {
		return false;
	}
	frame = parent;
	for (;;) {
		if (!query_parent(display, frame, &parent) || parent == None) {
			return false;
		}
		if (parent == root) {
			break;
		}
		frame = parent;
	}
	memset(result, 0, sizeof(*result));
	if (!read_geometry(display, root, client, &result->client) ||
		!read_geometry(display, root, frame, &result->frame) ||
		result->client.map_state != IsViewable ||
		result->frame.map_state != IsViewable ||
		!XQueryTree(display, frame, &query_root, &parent, &children,
			&child_count)) {
		if (children != NULL) {
			XFree(children);
		}
		return false;
	}
	for (unsigned int i = 0; i < child_count; ++i) {
		struct geometry candidate;

		if (children[i] == client ||
			!read_geometry(display, root, children[i], &candidate) ||
			candidate.map_state != IsViewable) {
			continue;
		}
		result->title = candidate;
		title_count++;
	}
	if (children != NULL) {
		XFree(children);
	}
	if (title_count > 1U) {
		die("managed frame has multiple unexpected direct decoration children");
	}
	result->title_present = title_count == 1U;
	return result->title_present == expected_title;
}

static struct observation await_stable_observation(Display *display,
		Window client, bool expected_title) {
	struct observation current = {0};
	struct observation previous = {0};
	int consecutive = 0;

	for (int attempt = 0; attempt < MAX_OBSERVATIONS; ++attempt) {
		XSync(display, False);
		if (collect_observation(display, client, expected_title, &current)) {
			if (consecutive > 0 &&
				memcmp(&current, &previous, sizeof(current)) == 0) {
				consecutive++;
			}
			else {
				previous = current;
				consecutive = 1;
			}
			if (consecutive >= REQUIRED_STABLE_OBSERVATIONS) {
				return current;
			}
		}
		else {
			consecutive = 0;
		}
		pause_briefly();
	}
	die("window geometry did not reach the expected stable managed state");
}

static void print_geometry(const char *label, const struct geometry *geometry) {
	printf("%s\t%d\t%d\t%u\t%u\t%u\t%s\n", label,
		geometry->root_x, geometry->root_y, geometry->width, geometry->height,
		geometry->border_width,
		geometry->map_state == IsViewable ? "viewable" : "not-viewable");
}

static void print_normal_hints(Display *display, Window window) {
	XSizeHints hints = {0};
	long supplied = 0;
	long flags;

	if (!XGetWMNormalHints(display, window, &hints, &supplied)) {
		die("managed client lost WM_NORMAL_HINTS");
	}
	flags = hints.flags;
	printf("hints\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n",
		(flags & USPosition) != 0, (flags & USSize) != 0,
		(flags & PMinSize) != 0, hints.min_width, hints.min_height,
		(flags & PMaxSize) != 0, hints.max_width, hints.max_height,
		(flags & PBaseSize) != 0, hints.base_width, hints.base_height,
		(flags & PResizeInc) != 0, hints.width_inc, hints.height_inc,
		(flags & PAspect) != 0,
		hints.min_aspect.x, hints.min_aspect.y,
		hints.max_aspect.x, hints.max_aspect.y,
		(flags & PWinGravity) != 0);
}

static _Noreturn void usage(const char *program) {
	fprintf(stderr, "usage: %s CASE normal|transient CLIENT_BORDER WIDTH HEIGHT "
		"position-size|min-max|base-increment|complete title|no-title\n",
		program);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv) {
	Display *display;
	Window root;
	Window owner = None;
	Window client;
	Window transient_for = None;
	struct observation observation;
	XWindowAttributes root_attributes;
	const char *case_id;
	const char *kind;
	const char *hint_profile;
	int client_border;
	int width;
	int height;
	bool expected_title;

	if (argc != 8) {
		usage(argv[0]);
	}
	case_id = argv[1];
	kind = argv[2];
	client_border = parse_nonnegative(argv[3], "client border width");
	width = parse_nonnegative(argv[4], "width");
	height = parse_nonnegative(argv[5], "height");
	hint_profile = argv[6];
	if (strcmp(argv[7], "title") == 0) {
		expected_title = true;
	}
	else if (strcmp(argv[7], "no-title") == 0) {
		expected_title = false;
	}
	else {
		usage(argv[0]);
	}
	if (strcmp(kind, "normal") != 0 && strcmp(kind, "transient") != 0) {
		usage(argv[0]);
	}

	display = XOpenDisplay(NULL);
	if (display == NULL) {
		die("could not open DISPLAY");
	}
	root = DefaultRootWindow(display);
	if (strcmp(kind, "transient") == 0) {
		owner = XCreateSimpleWindow(display, root, 36, 34, 180, 104, 0,
			BlackPixel(display, DefaultScreen(display)),
			WhitePixel(display, DefaultScreen(display)));
		set_metadata(display, owner, "geometry-matrix-owner",
			"WTWM Geometry Matrix Owner", 36, 34, 180, 104, "position-size");
		XMapWindow(display, owner);
	}
	client = XCreateSimpleWindow(display, root, 160, 120,
		(unsigned int)width, (unsigned int)height, (unsigned int)client_border,
		BlackPixel(display, DefaultScreen(display)),
		WhitePixel(display, DefaultScreen(display)));
	set_metadata(display, client, case_id, "WTWM Geometry Matrix",
		160, 120, width, height, hint_profile);
	if (owner != None) {
		XSetTransientForHint(display, client, owner);
		transient_for = owner;
	}
	XMapWindow(display, client);
	XSync(display, False);

	observation = await_stable_observation(display, client, expected_title);
	if (!XGetWindowAttributes(display, root, &root_attributes)) {
		die("could not read root geometry");
	}
	printf("screen\t%d\t%d\t%d\n", root_attributes.width,
		root_attributes.height, root_attributes.depth);
	printf("case\t%s\n", case_id);
	printf("kind\t%s\n", kind);
	printf("request\t160\t120\t%d\t%d\t%d\n", width, height,
		client_border);
	printf("transient\t%s\n", transient_for == None ? "false" : "true");
	print_geometry("client", &observation.client);
	print_geometry("frame", &observation.frame);
	if (observation.title_present) {
		print_geometry("title", &observation.title);
	}
	else {
		puts("title\tabsent");
	}
	print_normal_hints(display, client);

	XDestroyWindow(display, client);
	if (owner != None) {
		XDestroyWindow(display, owner);
	}
	XSync(display, False);
	XCloseDisplay(display);
	return EXIT_SUCCESS;
}
