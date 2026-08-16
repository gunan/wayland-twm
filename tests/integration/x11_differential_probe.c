/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ROLE_COUNT 8U

struct role_spec {
	const char *role;
	const char *title;
	const char *instance;
	const char *class_name;
	bool override_redirect;
};

struct drawable_geometry {
	bool present;
	unsigned int width;
	unsigned int height;
	unsigned int depth;
};

struct observed_window {
	const struct role_spec *spec;
	Window window;
	Window parent;
	Window transient_for;
	XWindowAttributes attributes;
	char *title;
	XClassHint class_hint;
};

static const struct role_spec roles[ROLE_COUNT] = {
	{"xterm", "WTWM Real Xterm", "wtwm-real-xterm", "WtwmRealXterm", false},
	{"xclock", "WTWM Real XClock", "wtwm-real-xclock", "XClock", false},
	{"xload", "WTWM Real XLoad", "wtwm-real-xload", "XLoad", false},
	{"emacs", "WTWM Real Emacs", "wtwm-real-emacs", "Emacs-gtk", false},
	{"terminal-dialog", "WTWM Terminal Dialog", "wtwm-terminal-dialog",
		"WtwmTerminalDialog", false},
	{"icccm-normal", "xwm-parent-initial", "xwm-instance-initial",
		"XwmClassInitial", false},
	{"icccm-transient", "xwm-transient", "xwm-transient-instance",
		"XwmTransientClass", false},
	{"icccm-override", "xwm-override-redirect", NULL, NULL, true},
};

static int x_error;

static int handle_x_error(Display *display, XErrorEvent *event) {
	(void)display;
	(void)event;
	x_error = 1;
	return 0;
}

static void json_string(const char *value) {
	const unsigned char *cursor = (const unsigned char *)value;
	putchar('"');
	while (*cursor != '\0') {
		switch (*cursor) {
		case '"': fputs("\\\"", stdout); break;
		case '\\': fputs("\\\\", stdout); break;
		case '\b': fputs("\\b", stdout); break;
		case '\f': fputs("\\f", stdout); break;
		case '\n': fputs("\\n", stdout); break;
		case '\r': fputs("\\r", stdout); break;
		case '\t': fputs("\\t", stdout); break;
		default:
			if (*cursor < 0x20U) printf("\\u%04x", *cursor);
			else putchar((int)*cursor);
			break;
		}
		cursor++;
	}
	putchar('"');
}

static bool query_parent(Display *display, Window window, Window *parent) {
	Window root;
	Window *children = NULL;
	unsigned int child_count = 0;
	Status status = XQueryTree(display, window, &root, parent, &children,
		&child_count);
	if (children != NULL) XFree(children);
	return status != 0;
}

static bool role_matches(Display *display, Window window,
		const struct role_spec *spec, char **title, XClassHint *class_hint) {
	XWindowAttributes attributes;
	*title = NULL;
	class_hint->res_name = NULL;
	class_hint->res_class = NULL;
	if (!XGetWindowAttributes(display, window, &attributes) ||
		attributes.class == InputOnly ||
		(bool)attributes.override_redirect != spec->override_redirect ||
		!XFetchName(display, window, title) || *title == NULL ||
		strcmp(*title, spec->title) != 0) {
		if (*title != NULL) XFree(*title);
		*title = NULL;
		return false;
	}
	if (spec->instance == NULL) return true;
	if (!XGetClassHint(display, window, class_hint) ||
		class_hint->res_name == NULL || class_hint->res_class == NULL ||
		strcmp(class_hint->res_name, spec->instance) != 0 ||
		strcmp(class_hint->res_class, spec->class_name) != 0) {
		if (class_hint->res_name != NULL) XFree(class_hint->res_name);
		if (class_hint->res_class != NULL) XFree(class_hint->res_class);
		XFree(*title);
		class_hint->res_name = NULL;
		class_hint->res_class = NULL;
		*title = NULL;
		return false;
	}
	return true;
}

static void search_tree(Display *display, Window window, unsigned int depth,
		struct observed_window observed[ROLE_COUNT], unsigned int counts[ROLE_COUNT]) {
	Window root;
	Window parent;
	Window *children = NULL;
	unsigned int child_count = 0;
	for (unsigned int i = 0; i < ROLE_COUNT; ++i) {
		char *title = NULL;
		XClassHint class_hint = {0};
		if (!role_matches(display, window, &roles[i], &title, &class_hint)) continue;
		counts[i]++;
		if (counts[i] == 1U) {
			observed[i].spec = &roles[i];
			observed[i].window = window;
			observed[i].title = title;
			observed[i].class_hint = class_hint;
			if (!query_parent(display, window, &observed[i].parent) ||
				!XGetWindowAttributes(display, window, &observed[i].attributes)) {
				counts[i]++;
			}
			if (!XGetTransientForHint(display, window,
				&observed[i].transient_for)) observed[i].transient_for = None;
		} else {
			if (title != NULL) XFree(title);
			if (class_hint.res_name != NULL) XFree(class_hint.res_name);
			if (class_hint.res_class != NULL) XFree(class_hint.res_class);
		}
	}
	if (depth == 0U || !XQueryTree(display, window, &root, &parent, &children,
		&child_count)) return;
	for (unsigned int i = 0; i < child_count; ++i)
		search_tree(display, children[i], depth - 1U, observed, counts);
	if (children != NULL) XFree(children);
}

static const char *transient_role(const struct observed_window observed[ROLE_COUNT],
		Window window) {
	if (window == None) return NULL;
	for (unsigned int i = 0; i < ROLE_COUNT; ++i)
		if (observed[i].window == window) return observed[i].spec->role;
	return "external";
}

static struct drawable_geometry drawable_geometry(Display *display, Drawable drawable) {
	struct drawable_geometry result = {0};
	Window root;
	int x;
	int y;
	unsigned int border;
	if (drawable == None) return result;
	x_error = 0;
	if (XGetGeometry(display, drawable, &root, &x, &y, &result.width,
		&result.height, &border, &result.depth)) result.present = true;
	XSync(display, False);
	if (x_error) memset(&result, 0, sizeof(result));
	return result;
}

static void print_geometry(struct drawable_geometry geometry) {
	if (!geometry.present) {
		fputs("null", stdout);
		return;
	}
	printf("{\"depth\":%u,\"height\":%u,\"width\":%u}", geometry.depth,
		geometry.height, geometry.width);
}

static void print_normal_hints(Display *display, Window window) {
	XSizeHints hints = {0};
	long supplied = 0;
	bool present = XGetWMNormalHints(display, window, &hints, &supplied) != 0;
	long flags = present ? hints.flags : 0L;
	bool has_size = (flags & (USSize | PSize)) != 0;
	bool has_min_size = (flags & PMinSize) != 0;
	bool has_max_size = (flags & PMaxSize) != 0;
	bool has_resize_inc = (flags & PResizeInc) != 0;
	bool has_aspect = (flags & PAspect) != 0;
	bool has_base_size = (flags & PBaseSize) != 0;
	bool has_win_gravity = (flags & PWinGravity) != 0;
	int width = has_size ? hints.width : 0;
	int height = has_size ? hints.height : 0;
	int min_width = has_min_size ? hints.min_width : 0;
	int min_height = has_min_size ? hints.min_height : 0;
	int max_width = has_max_size ? hints.max_width : 0;
	int max_height = has_max_size ? hints.max_height : 0;
	int width_inc = has_resize_inc ? hints.width_inc : 0;
	int height_inc = has_resize_inc ? hints.height_inc : 0;
	int min_aspect_x = has_aspect ? hints.min_aspect.x : 0;
	int min_aspect_y = has_aspect ? hints.min_aspect.y : 0;
	int max_aspect_x = has_aspect ? hints.max_aspect.x : 0;
	int max_aspect_y = has_aspect ? hints.max_aspect.y : 0;
	int base_width = has_base_size ? hints.base_width : 0;
	int base_height = has_base_size ? hints.base_height : 0;
	int win_gravity = has_win_gravity ? hints.win_gravity : 0;
	/* Exact position is outside this differential even when its flag is set. */
	int x = 0;
	int y = 0;
	printf("{\"base_height\":%d,\"base_width\":%d,\"flags\":%ld,"
		"\"height\":%d,\"height_inc\":%d,\"max_aspect_x\":%d,"
		"\"max_aspect_y\":%d,\"max_height\":%d,\"max_width\":%d,"
		"\"min_aspect_x\":%d,\"min_aspect_y\":%d,\"min_height\":%d,"
		"\"min_width\":%d,\"present\":%s,\"supplied\":%ld,"
		"\"width\":%d,\"width_inc\":%d,\"win_gravity\":%d,"
		"\"x\":%d,\"y\":%d}",
		base_height, base_width, flags, height, height_inc, max_aspect_x,
		max_aspect_y, max_height, max_width, min_aspect_x, min_aspect_y,
		min_height, min_width, present ? "true" : "false", supplied,
		width, width_inc, win_gravity, x, y);
}

static void print_wm_hints(Display *display, Window window) {
	XWMHints *hints = XGetWMHints(display, window);
	long flags = hints != NULL ? hints->flags : 0L;
	struct drawable_geometry icon_pixmap = drawable_geometry(display,
		hints != NULL && (flags & IconPixmapHint) ? hints->icon_pixmap : None);
	struct drawable_geometry icon_mask = drawable_geometry(display,
		hints != NULL && (flags & IconMaskHint) ? hints->icon_mask : None);
	struct drawable_geometry icon_window = drawable_geometry(display,
		hints != NULL && (flags & IconWindowHint) ? hints->icon_window : None);
	printf("{\"flags\":%ld,\"icon_mask\":", flags);
	print_geometry(icon_mask);
	fputs(",\"icon_pixmap\":", stdout);
	print_geometry(icon_pixmap);
	fputs(",\"icon_window\":", stdout);
	print_geometry(icon_window);
	printf(",\"input\":%s,\"input_specified\":%s,\"present\":%s,"
		"\"urgent\":%s}",
		hints != NULL && hints->input ? "true" : "false",
		flags & InputHint ? "true" : "false", hints != NULL ? "true" : "false",
		flags & XUrgencyHint ? "true" : "false");
	if (hints != NULL) XFree(hints);
}

static void print_net_wm_icon(Display *display, Window window) {
	Atom property = XInternAtom(display, "_NET_WM_ICON", False);
	Atom actual_type = None;
	int actual_format = 0;
	unsigned long count = 0;
	unsigned long bytes_after = 0;
	unsigned char *data = NULL;
	unsigned long width = 0;
	unsigned long height = 0;
	uint32_t checksum = UINT32_C(2166136261);
	if (XGetWindowProperty(display, window, property, 0, 1048576, False,
		XA_CARDINAL, &actual_type, &actual_format, &count, &bytes_after,
		&data) != Success || actual_type != XA_CARDINAL || actual_format != 32 ||
		count < 2U || data == NULL) {
		fputs("{\"checksum\":null,\"height\":null,\"items\":0,"
			"\"present\":false,\"width\":null}", stdout);
		if (data != NULL) XFree(data);
		return;
	}
	const unsigned long *items = (const unsigned long *)data;
	width = items[0];
	height = items[1];
	for (unsigned long i = 0; i < count; ++i) {
		uint32_t value = (uint32_t)items[i];
		for (unsigned int byte = 0; byte < 4U; ++byte) {
			checksum ^= value & UINT32_C(0xff);
			checksum *= UINT32_C(16777619);
			value >>= 8U;
		}
	}
	printf("{\"checksum\":%" PRIu32 ",\"height\":%lu,\"items\":%lu,"
		"\"present\":true,\"width\":%lu}", checksum, height, count, width);
	XFree(data);
}

static bool supports_delete(Display *display, Window window) {
	Atom *protocols = NULL;
	int count = 0;
	Atom wanted = XInternAtom(display, "WM_DELETE_WINDOW", False);
	bool found = false;
	if (XGetWMProtocols(display, window, &protocols, &count)) {
		for (int i = 0; i < count; ++i) if (protocols[i] == wanted) found = true;
	}
	if (protocols != NULL) XFree(protocols);
	return found;
}

static void print_window(Display *display,
		const struct observed_window observed[ROLE_COUNT], unsigned int index) {
	const struct observed_window *item = &observed[index];
	char *icon_name = NULL;
	const char *transient = transient_role(observed, item->transient_for);
	fputs("{\"class\":", stdout);
	if (item->class_hint.res_class == NULL) fputs("null", stdout);
	else json_string(item->class_hint.res_class);
	fputs(",\"icon_name\":", stdout);
	if (!XGetIconName(display, item->window, &icon_name) || icon_name == NULL)
		fputs("null", stdout);
	else json_string(icon_name);
	fputs(",\"instance\":", stdout);
	if (item->class_hint.res_name == NULL) fputs("null", stdout);
	else json_string(item->class_hint.res_name);
	printf(",\"mapped\":%s,\"net_wm_icon\":",
		item->attributes.map_state == IsViewable ? "true" : "false");
	print_net_wm_icon(display, item->window);
	fputs(",\"normal_hints\":", stdout);
	print_normal_hints(display, item->window);
	printf(",\"override_redirect\":%s,\"role\":",
		item->attributes.override_redirect ? "true" : "false");
	json_string(item->spec->role);
	printf(",\"root_parent\":%s,\"supports_delete\":%s,\"title\":",
		item->parent == DefaultRootWindow(display) ? "true" : "false",
		supports_delete(display, item->window) ? "true" : "false");
	json_string(item->title);
	fputs(",\"transient_for\":", stdout);
	if (transient == NULL) fputs("null", stdout);
	else json_string(transient);
	fputs(",\"wm_hints\":", stdout);
	print_wm_hints(display, item->window);
	putchar('}');
	if (icon_name != NULL) XFree(icon_name);
}

static void free_observed(struct observed_window observed[ROLE_COUNT]) {
	for (unsigned int i = 0; i < ROLE_COUNT; ++i) {
		if (observed[i].title != NULL) XFree(observed[i].title);
		if (observed[i].class_hint.res_name != NULL)
			XFree(observed[i].class_hint.res_name);
		if (observed[i].class_hint.res_class != NULL)
			XFree(observed[i].class_hint.res_class);
	}
}

static bool wait_for_reference_reparent(Display *display) {
	Window root = DefaultRootWindow(display);
	Window sentinel = XCreateSimpleWindow(display, root, 0, 0, 16, 16, 0, 0, 0);
	XClassHint class_hint = {
		.res_name = (char *)"wtwm-differential-sentinel",
		.res_class = (char *)"WtwmDifferentialSentinel",
	};
	XStoreName(display, sentinel, "WTWM differential readiness sentinel");
	XSetClassHint(display, sentinel, &class_hint);
	XSelectInput(display, sentinel, StructureNotifyMask);
	XMapWindow(display, sentinel);
	XFlush(display);
	bool reparented = false;
	for (;;) {
		Window parent = None;
		if (query_parent(display, sentinel, &parent) && parent != None &&
			parent != root && parent != sentinel) {
			reparented = true;
			break;
		}
		struct pollfd descriptor = {
			.fd = ConnectionNumber(display),
			.events = POLLIN,
		};
		int status = poll(&descriptor, 1, 250);
		if (status <= 0) break;
		while (XPending(display) > 0) {
			XEvent event;
			XNextEvent(display, &event);
		}
	}
	XDestroyWindow(display, sentinel);
	XSync(display, False);
	return reparented;
}

int main(int argc, char **argv) {
	if (argc != 2 || (strcmp(argv[1], "ready") != 0 &&
		strcmp(argv[1], "capture") != 0)) {
		fprintf(stderr, "usage: x11-differential-probe ready|capture\n");
		return 2;
	}
	XSetErrorHandler(handle_x_error);
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) return 3;
	if (strcmp(argv[1], "ready") == 0) {
		bool ready = wait_for_reference_reparent(display);
		XCloseDisplay(display);
		return ready ? 0 : 3;
	}
	struct observed_window observed[ROLE_COUNT] = {0};
	unsigned int counts[ROLE_COUNT] = {0};
	search_tree(display, DefaultRootWindow(display), 12U, observed, counts);
	for (unsigned int i = 0; i < ROLE_COUNT; ++i) {
		if (counts[i] != 1U || observed[i].attributes.map_state != IsViewable) {
			free_observed(observed);
			XCloseDisplay(display);
			return 3;
		}
	}
	fputs("{\"clients\":[", stdout);
	for (unsigned int i = 0; i < ROLE_COUNT; ++i) {
		if (i != 0U) putchar(',');
		print_window(display, observed, i);
	}
	fputs("],\"schema_version\":1}\n", stdout);
	free_observed(observed);
	XCloseDisplay(display);
	return 0;
}
