/* Force an event to arrive during a compositor-owned XWM flush. XCB is allowed
 * to read events while writing; wlroots must subsequently see socket readiness
 * to dispatch events which are already in libxcb's queue. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xcb/xcb.h>

static xcb_connection_t *focus_connection;

/* Only the compositor needs this fixture. In particular, an instrumented
 * shared library must not be preloaded by unsanitized Xwayland/xkbcomp. */
__attribute__((constructor)) static void clear_child_preload(void) {
	if (unsetenv("LD_PRELOAD") != 0) abort();
}

xcb_void_cookie_t xcb_set_input_focus(xcb_connection_t *connection,
		uint8_t revert_to, xcb_window_t focus, xcb_timestamp_t time) {
	static xcb_void_cookie_t (*original)(xcb_connection_t *, uint8_t,
		xcb_window_t, xcb_timestamp_t);
	if (original == NULL) {
		void *symbol = dlsym(RTLD_NEXT, "xcb_set_input_focus");
		memcpy(&original, &symbol, sizeof(original));
	}
	if (original == NULL) abort();
	focus_connection = connection;
	return original(connection, revert_to, focus, time);
}

int xcb_flush(xcb_connection_t *connection) {
	static int (*original)(xcb_connection_t *);
	if (original == NULL) {
		void *symbol = dlsym(RTLD_NEXT, "xcb_flush");
		memcpy(&original, &symbol, sizeof(original));
	}
	if (original == NULL) abort();
	int result = original(connection);
	if (focus_connection != connection) return result;
	focus_connection = NULL;
	const char *path = getenv("WTWM_TEST_XCB_QUEUE");
	if (path == NULL) return result;
	FILE *file = fopen(path, "r");
	if (file == NULL) return result;
	unsigned window = 0;
	int scanned = fscanf(file, "%u", &window);
	fclose(file);
	if (scanned != 1 || window == 0 || unlink(path) != 0) abort();
	const char title[] = "wtwm-queued-x11";
	xcb_change_property(connection, XCB_PROP_MODE_REPLACE, window,
		XCB_ATOM_WM_NAME, XCB_ATOM_STRING, 8, sizeof(title) - 1, title);
	/* The reply comes after PropertyNotify and therefore moves that event
	 * into libxcb. Do not poll it or send another event to rescue the XWM. */
	xcb_get_input_focus_reply_t *reply = xcb_get_input_focus_reply(connection,
		xcb_get_input_focus(connection), NULL);
	if (reply == NULL) abort();
	free(reply);
	return result;
}
