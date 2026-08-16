/* SPDX-License-Identifier: MIT */
#include <X11/Xlib.h>
#include <X11/keysym.h>
#include <X11/extensions/XTest.h>

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static _Noreturn void usage(const char *program) {
	fprintf(stderr, "usage: %s pointer X Y | button NUMBER press|release | "
		"key KEYSYM press|release\n", program);
	exit(EXIT_FAILURE);
}

static int parse_integer(const char *text) {
	char *end = NULL;
	errno = 0;
	long value = strtol(text, &end, 10);
	if (errno != 0 || end == text || *end != '\0' || value < 0 || value > INT_MAX)
		usage("m4-trace-input");
	return (int)value;
}

static Bool parse_state(const char *text) {
	if (strcmp(text, "press") == 0) return True;
	if (strcmp(text, "release") == 0) return False;
	usage("m4-trace-input");
}

int main(int argc, char **argv) {
	Display *display = XOpenDisplay(NULL);
	if (display == NULL) {
		fprintf(stderr, "m4 trace input: could not open DISPLAY\n");
		return EXIT_FAILURE;
	}
	Bool sent = False;
	if (argc == 4 && strcmp(argv[1], "pointer") == 0) {
		sent = XTestFakeMotionEvent(display, DefaultScreen(display),
			parse_integer(argv[2]), parse_integer(argv[3]), CurrentTime);
	} else if (argc == 4 && strcmp(argv[1], "button") == 0) {
		sent = XTestFakeButtonEvent(display, (unsigned int)parse_integer(argv[2]),
			parse_state(argv[3]), CurrentTime);
	} else if (argc == 4 && strcmp(argv[1], "key") == 0) {
		KeySym symbol = XStringToKeysym(argv[2]);
		KeyCode code = symbol == NoSymbol ? 0 : XKeysymToKeycode(display, symbol);
		if (code == 0) usage(argv[0]);
		sent = XTestFakeKeyEvent(display, code, parse_state(argv[3]), CurrentTime);
	} else {
		XCloseDisplay(display);
		usage(argv[0]);
	}
	XSync(display, False);
	XCloseDisplay(display);
	if (!sent) {
		fprintf(stderr, "m4 trace input: XTEST rejected synthetic input\n");
		return EXIT_FAILURE;
	}
	return EXIT_SUCCESS;
}
