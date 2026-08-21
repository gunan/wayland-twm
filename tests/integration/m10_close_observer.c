/* SPDX-License-Identifier: MIT */
#include <X11/Xlib.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct match {
	Window client;
	unsigned int count;
};

static void find_named(Display *display, Window window, const char *title,
		unsigned int depth, struct match *match) {
	if (depth > 32) return;
	char *name = NULL;
	if (XFetchName(display, window, &name) != 0 && name != NULL) {
		if (strcmp(name, title) == 0) {
			match->client = window;
			match->count++;
		}
		XFree(name);
	}
	Window root;
	Window parent;
	Window *children = NULL;
	unsigned int count = 0;
	if (XQueryTree(display, window, &root, &parent, &children, &count) == 0)
		return;
	for (unsigned int index = 0; index < count; ++index)
		find_named(display, children[index], title, depth + 1, match);
	if (children != NULL) XFree(children);
}

static Window outer_frame(Display *display, Window client, Window root,
		bool *reparented) {
	Window current = client;
	*reparented = false;
	for (unsigned int depth = 0; depth < 32; ++depth) {
		Window query_root;
		Window parent;
		Window *children = NULL;
		unsigned int count = 0;
		if (XQueryTree(display, current, &query_root, &parent, &children,
				&count) == 0) break;
		if (children != NULL) XFree(children);
		if (parent == root) {
			*reparented = current != client;
			return current;
		}
		if (parent == None || parent == current) break;
		current = parent;
	}
	return client;
}

int main(int argc, char **argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: m10-close-observer TITLE\n");
		return EXIT_FAILURE;
	}
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) {
		fprintf(stderr, "m10 close observer: could not open DISPLAY\n");
		return EXIT_FAILURE;
	}
	Window root = DefaultRootWindow(display);
	struct match match = {0};
	find_named(display, root, argv[1], 0, &match);
	if (match.count != 1) {
		printf("{\"count\":%u}\n", match.count);
		XCloseDisplay(display);
		return EXIT_SUCCESS;
	}
	bool reparented = false;
	Window frame = outer_frame(display, match.client, root, &reparented);
	Window ignored_root;
	int ignored_x;
	int ignored_y;
	unsigned int width;
	unsigned int height;
	unsigned int border;
	unsigned int depth;
	if (XGetGeometry(display, frame, &ignored_root, &ignored_x, &ignored_y,
			&width, &height, &border, &depth) == 0) {
		XCloseDisplay(display);
		return EXIT_FAILURE;
	}
	int root_x;
	int root_y;
	Window child;
	if (XTranslateCoordinates(display, frame, root, 0, 0, &root_x, &root_y,
			&child) == 0) {
		XCloseDisplay(display);
		return EXIT_FAILURE;
	}
	printf(
		"{\"count\":1,\"client\":%lu,\"frame\":%lu,"
		"\"x\":%d,\"y\":%d,\"width\":%u,\"height\":%u,"
		"\"reparented\":%s}\n",
		(unsigned long)match.client, (unsigned long)frame, root_x, root_y,
		width, height, reparented ? "true" : "false");
	XCloseDisplay(display);
	return EXIT_SUCCESS;
}
