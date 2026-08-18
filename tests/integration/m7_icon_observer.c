/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static _Noreturn void fail(const char *message) {
	fprintf(stderr, "m7 icon observer: %s\n", message);
	exit(EXIT_FAILURE);
}

static void pause_milliseconds(long milliseconds) {
	struct timespec duration = {
		.tv_sec = milliseconds / 1000,
		.tv_nsec = milliseconds % 1000 * 1000000,
	};
	while (nanosleep(&duration, &duration) < 0 && errno == EINTR) {
	}
}

static unsigned int mask_shift(unsigned long mask) {
	unsigned int shift = 0;
	while (mask != 0 && (mask & 1UL) == 0) {
		mask >>= 1;
		shift++;
	}
	return shift;
}

static unsigned int channel(unsigned long pixel, unsigned long mask) {
	if (mask == 0) return 0;
	unsigned int shift = mask_shift(mask);
	unsigned long maximum = mask >> shift;
	unsigned long value = (pixel & mask) >> shift;
	return (unsigned int)((value * 255UL + maximum / 2UL) / maximum);
}

static void capture(Display *display, const char *path) {
	int screen = DefaultScreen(display);
	Window root = RootWindow(display, screen);
	unsigned int width = (unsigned int)DisplayWidth(display, screen);
	unsigned int height = (unsigned int)DisplayHeight(display, screen);
	XImage *image = XGetImage(display, root, 0, 0, width, height, AllPlanes,
		ZPixmap);
	if (image == NULL) fail("XGetImage failed");
	FILE *output = fopen(path, "wb");
	if (output == NULL) fail("could not open capture output");
	if (fprintf(output, "P6\n%u %u\n255\n", width, height) < 0)
		fail("could not write capture header");
	Visual *visual = DefaultVisual(display, screen);
	for (unsigned int y = 0; y < height; ++y) {
		for (unsigned int x = 0; x < width; ++x) {
			unsigned long pixel = XGetPixel(image, (int)x, (int)y);
			unsigned char rgb[3] = {
				(unsigned char)channel(pixel, visual->red_mask),
				(unsigned char)channel(pixel, visual->green_mask),
				(unsigned char)channel(pixel, visual->blue_mask),
			};
			if (fwrite(rgb, sizeof(rgb), 1, output) != 1)
				fail("could not write capture pixels");
		}
	}
	if (fclose(output) != 0) fail("could not close capture output");
	XDestroyImage(image);
}

static void pointer(Display *display) {
	Window root_return;
	Window child_return;
	int root_x;
	int root_y;
	int window_x;
	int window_y;
	unsigned int mask;
	if (!XQueryPointer(display, DefaultRootWindow(display), &root_return,
			&child_return, &root_x, &root_y, &window_x, &window_y, &mask))
		fail("XQueryPointer failed");
	printf("{\"x\":%d,\"y\":%d}\n", root_x, root_y);
}

static bool sentinel_reparented(Display *display, Window window) {
	Window root;
	Window parent;
	Window *children = NULL;
	unsigned int child_count = 0;
	bool queried = XQueryTree(display, window, &root, &parent, &children,
		&child_count) != 0;
	if (children != NULL) XFree(children);
	return queried && parent != DefaultRootWindow(display);
}

static void ready(Display *display) {
	Window window = XCreateSimpleWindow(display, DefaultRootWindow(display),
		1, 1, 16, 16, 0, 0, 0);
	XStoreName(display, window, "wtwm-m7-reference-ready");
	XMapWindow(display, window);
	XSync(display, False);
	bool managed = false;
	for (unsigned int attempt = 0; attempt < 500; ++attempt) {
		if (sentinel_reparented(display, window)) {
			managed = true;
			break;
		}
		pause_milliseconds(10);
		XSync(display, False);
	}
	XDestroyWindow(display, window);
	XSync(display, False);
	if (!managed) fail("window manager did not reparent the readiness sentinel");
}

static _Noreturn void usage(const char *program) {
	fprintf(stderr, "usage: %s ready | pointer | capture OUTPUT.ppm\n", program);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv) {
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) fail("could not open DISPLAY");
	if (argc == 2 && strcmp(argv[1], "ready") == 0) {
		ready(display);
	} else if (argc == 2 && strcmp(argv[1], "pointer") == 0) {
		pointer(display);
	} else if (argc == 3 && strcmp(argv[1], "capture") == 0) {
		capture(display, argv[2]);
	} else {
		XCloseDisplay(display);
		usage(argv[0]);
	}
	XCloseDisplay(display);
	return EXIT_SUCCESS;
}
