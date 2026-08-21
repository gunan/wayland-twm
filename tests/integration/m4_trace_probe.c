/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ROLE_COUNT 2U
#define ROLE_PROPERTY "_WTWM_REFERENCE_ROLE"

struct observed {
	const char *role;
	Window client;
	Window frame;
	XWindowAttributes client_attributes;
	XWindowAttributes frame_attributes;
	int client_x;
	int client_y;
	int frame_inner_x;
	int frame_inner_y;
	bool iconified;
	bool titled;
};

static const char *const roles[ROLE_COUNT] = {"alpha", "bravo"};

static _Noreturn void die(const char *message) {
	fprintf(stderr, "m4 trace probe: %s\n", message);
	exit(EXIT_FAILURE);
}

static bool read_role(Display *display, Window window, char *buffer,
		size_t buffer_size) {
	Atom atom = XInternAtom(display, ROLE_PROPERTY, False);
	Atom type;
	int format;
	unsigned long count;
	unsigned long after;
	unsigned char *data = NULL;
	bool found = false;
	if (XGetWindowProperty(display, window, atom, 0, 32, False, XA_STRING,
			&type, &format, &count, &after, &data) == Success &&
			type == XA_STRING && format == 8 && count > 0 && count < buffer_size) {
		memcpy(buffer, data, count);
		buffer[count] = '\0';
		found = true;
	}
	if (data != NULL) XFree(data);
	return found;
}

static bool find_role(Display *display, Window window, const char *wanted,
		unsigned depth, Window *result) {
	char role[32];
	if (read_role(display, window, role, sizeof(role)) && strcmp(role, wanted) == 0) {
		*result = window;
		return true;
	}
	if (depth == 0) return false;
	Window root;
	Window parent;
	Window *children = NULL;
	unsigned count = 0;
	if (!XQueryTree(display, window, &root, &parent, &children, &count)) return false;
	for (unsigned i = 0; i < count; ++i) {
		if (find_role(display, children[i], wanted, depth - 1, result)) {
			XFree(children);
			return true;
		}
	}
	if (children != NULL) XFree(children);
	return false;
}

static Window root_child(Display *display, Window root, Window window) {
	Window current = window;
	for (;;) {
		Window query_root;
		Window parent;
		Window *children = NULL;
		unsigned count = 0;
		if (!XQueryTree(display, current, &query_root, &parent, &children, &count))
			die("could not query client ancestry");
		if (children != NULL) XFree(children);
		if (parent == root) return current;
		if (parent == None || parent == current) die("client has no root ancestor");
		current = parent;
	}
}

static bool wm_state_is_iconic(Display *display, Window window) {
	Atom wm_state = XInternAtom(display, "WM_STATE", False);
	Atom type;
	int format;
	unsigned long count;
	unsigned long after;
	unsigned char *data = NULL;
	bool iconified = false;
	if (XGetWindowProperty(display, window, wm_state, 0, 2, False, wm_state,
			&type, &format, &count, &after, &data) == Success &&
			type == wm_state && format == 32 && count >= 1)
		iconified = ((long *)data)[0] == IconicState;
	if (data != NULL) XFree(data);
	return iconified;
}

static bool has_title_child(Display *display, const struct observed *item) {
	if (item->frame == item->client) return false;
	Window root;
	Window parent;
	Window *children = NULL;
	unsigned count = 0;
	if (!XQueryTree(display, item->frame, &root, &parent, &children, &count))
		return false;
	bool titled = false;
	for (unsigned i = 0; i < count; ++i)
		if (children[i] != item->client) titled = true;
	if (children != NULL) XFree(children);
	return titled;
}

static void observe(Display *display, Window root, struct observed *item,
		const char *role) {
	Window child;
	memset(item, 0, sizeof(*item));
	item->role = role;
	if (!find_role(display, root, role, 6, &item->client))
		die("controlled role is missing");
	item->frame = root_child(display, root, item->client);
	if (!XGetWindowAttributes(display, item->client, &item->client_attributes) ||
			!XGetWindowAttributes(display, item->frame, &item->frame_attributes) ||
			!XTranslateCoordinates(display, item->client, root, 0, 0,
				&item->client_x, &item->client_y, &child) ||
			!XTranslateCoordinates(display, item->frame, root, 0, 0,
				&item->frame_inner_x, &item->frame_inner_y, &child))
		die("could not read controlled geometry");
	item->iconified = wm_state_is_iconic(display, item->client);
	item->titled = has_title_child(display, item);
}

static const char *focus_role(Window focus, Window root,
		const struct observed items[ROLE_COUNT]) {
	if (focus == None || focus == PointerRoot || focus == root) return "root";
	for (unsigned i = 0; i < ROLE_COUNT; ++i)
		if (focus == items[i].client) return items[i].role;
	return "other";
}

static void print_window(const struct observed *item) {
	int border = item->frame_attributes.border_width;
	int outer_x = item->frame_inner_x - border;
	int outer_y = item->frame_inner_y - border;
	int outer_width = item->frame_attributes.width + 2 * border;
	int outer_height = item->frame_attributes.height + 2 * border;
	printf("{\"role\":\"%s\",\"client\":{"
		"\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,\"border_width\":%d},"
		"\"frame\":{\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
		"\"outer_width\":%d,\"outer_height\":%d,\"border_width\":%d,"
		"\"content_x\":%d,\"content_y\":%d},"
		"\"mapped\":%s,\"iconified\":%s,\"titled\":%s}",
		item->role, item->client_x, item->client_y,
		item->client_attributes.width, item->client_attributes.height,
		item->client_attributes.border_width, outer_x, outer_y,
		item->frame_attributes.width, item->frame_attributes.height,
		outer_width, outer_height, border, item->client_x - outer_x,
		item->client_y - outer_y,
		item->client_attributes.map_state == IsViewable ? "true" : "false",
		item->iconified ? "true" : "false", item->titled ? "true" : "false");
}

int main(void) {
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) die("could not open DISPLAY");
	Window root = DefaultRootWindow(display);
	XWindowAttributes root_attributes;
	struct observed items[ROLE_COUNT];
	for (unsigned i = 0; i < ROLE_COUNT; ++i) observe(display, root, &items[i], roles[i]);
	if (!XGetWindowAttributes(display, root, &root_attributes)) die("could not read root");
	Window focus;
	int revert;
	XGetInputFocus(display, &focus, &revert);
	(void)revert;
	Window pointer_root;
	Window pointer_child;
	int pointer_root_x;
	int pointer_root_y;
	int pointer_window_x;
	int pointer_window_y;
	unsigned pointer_mask;
	if (!XQueryPointer(display, root, &pointer_root, &pointer_child,
			&pointer_root_x, &pointer_root_y, &pointer_window_x,
			&pointer_window_y, &pointer_mask))
		die("could not read root pointer coordinates");
	(void)pointer_root;
	(void)pointer_child;
	(void)pointer_window_x;
	(void)pointer_window_y;
	(void)pointer_mask;

	Window query_root;
	Window parent;
	Window *children = NULL;
	unsigned child_count = 0;
	if (!XQueryTree(display, root, &query_root, &parent, &children, &child_count))
		die("could not read root stack");
	const char *stack[ROLE_COUNT] = {NULL, NULL};
	unsigned stack_count = 0;
	for (unsigned i = 0; i < child_count; ++i)
		for (unsigned role = 0; role < ROLE_COUNT; ++role)
			if (children[i] == items[role].frame &&
					items[role].client_attributes.map_state == IsViewable &&
					stack_count < ROLE_COUNT)
				stack[stack_count++] = items[role].role;
	if (children != NULL) XFree(children);

	printf("{\"screen\":{\"width\":%d,\"height\":%d,\"depth\":%d},"
		"\"pointer\":{\"x\":%d,\"y\":%d},\"focus\":\"%s\",\"stack\":[",
		root_attributes.width, root_attributes.height, root_attributes.depth,
		pointer_root_x, pointer_root_y, focus_role(focus, root, items));
	for (unsigned i = 0; i < stack_count; ++i) {
		if (i != 0) putchar(',');
		printf("\"%s\"", stack[i]);
	}
	fputs("],\"windows\":[", stdout);
	for (unsigned i = 0; i < ROLE_COUNT; ++i) {
		if (i != 0) putchar(',');
		print_window(&items[i]);
	}
	puts("]}");
	XCloseDisplay(display);
	return EXIT_SUCCESS;
}
