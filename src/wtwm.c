/* SPDX-License-Identifier: MIT
 *
 * wtwm is built on wlroots' public 0.18 scene and xdg-shell APIs.  The small
 * compositor core follows the same event-driven shape as wlroots/tinywl, with
 * server-side decorations and twm actions kept in this project.
 */
#define _POSIX_C_SOURCE 200809L
#define WLR_USE_UNSTABLE

#include "wtwm/config.h"
#include "wtwm/geometry.h"
#include "wtwm/interaction.h"
#include "text.h"
#ifdef WTWM_TEST_CONTROL
#include "test_control.h"
#endif

#include <errno.h>
#include <getopt.h>
#include <inttypes.h>
#include <limits.h>
#ifdef __linux__
#include <linux/input-event-codes.h>
#else
#define BTN_MOUSE 0x110
#define BTN_LEFT 0x110
#define BTN_RIGHT 0x111
#define BTN_MIDDLE 0x112
#endif
#include <signal.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <wayland-server-core.h>
#include <wlr/backend.h>
#ifdef WTWM_TEST_CONTROL
#include <drm_fourcc.h>
#include <fcntl.h>
#include <fontconfig/fontconfig.h>
#include <pango/pangocairo.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <wlr/backend/headless.h>
#include <wlr/interfaces/wlr_keyboard.h>
#include <wlr/types/wlr_buffer.h>
#endif
#include <wlr/render/allocator.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_input_device.h>
#include <wlr/types/wlr_keyboard.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_pointer.h>
#include <wlr/types/wlr_primary_selection.h>
#include <wlr/types/wlr_primary_selection_v1.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_xcursor_manager.h>
#include <wlr/types/wlr_xdg_decoration_v1.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/log.h>
#include <wlr/xwayland/xwayland.h>
#include <xcb/xcb.h>
#include <xkbcommon/xkbcommon.h>

enum cursor_mode { CURSOR_PASSTHROUGH, CURSOR_MOVE, CURSOR_RESIZE };

struct server;

#ifdef WTWM_TEST_CONTROL
enum {
	TEST_TRACE_INITIAL_CAPACITY = 64,
	TEST_TRACE_MAX_EVENTS = 4096,
	TEST_TRACE_IDENTITY_MAX = 256,
};

struct test_trace_event {
	uint64_t sequence;
	uint64_t window_id;
	char event[16];
	char context[16];
	char type[8];
	char title[TEST_TRACE_IDENTITY_MAX];
	char app_id[TEST_TRACE_IDENTITY_MAX];
	char instance[TEST_TRACE_IDENTITY_MAX];
	char class_name[TEST_TRACE_IDENTITY_MAX];
	char icon_name[TEST_TRACE_IDENTITY_MAX];
	int client_x;
	int client_y;
	int client_width;
	int client_height;
	int frame_x;
	int frame_y;
	int frame_width;
	int frame_height;
	int outer_width;
	int outer_height;
	int border_width;
	int title_bar_height;
	int title_height;
	int content_x;
	int content_y;
	int stack;
	bool mapped;
	bool iconified;
	bool focused;
};

struct test_control {
	struct server *server;
	char path[sizeof(((struct sockaddr_un *)0)->sun_path)];
	int listen_fd;
	int client_fd;
	struct wl_event_source *listen_source;
	struct wl_event_source *client_source;
	char input[4096];
	size_t input_length;
	struct wlr_keyboard keyboard;
	bool keyboard_initialized;
	unsigned animation_ms;
	uint32_t input_time_ms;
	struct test_trace_event *trace_events;
	size_t trace_event_count;
	size_t trace_event_capacity;
	uint64_t trace_next_sequence;
	uint64_t trace_next_window_id;
	uint64_t trace_dropped;
};
#endif

struct toplevel {
	struct wl_list link;
	struct wl_list xwayland_link;
	struct server *server;
	struct wlr_xdg_toplevel *xdg;
	struct wlr_xwayland_surface *xwayland;
	struct wlr_scene_tree *tree;
	struct wlr_scene_tree *content;
	struct wlr_scene_rect *frame;
	struct wlr_scene_rect *title;
	struct wlr_scene_rect *focus_mark;
	struct wlr_scene_rect *left_button;
	struct wlr_scene_rect *left_dot;
	struct wlr_scene_rect *right_button;
	struct wlr_scene_rect *right_inner;
	struct wlr_scene_buffer *title_text;
	int title_text_height;
	int width;
	int height;
	int border_width;
	int original_client_border;
	bool border_initialized;
	int title_bar_height;
	int title_height;
	int frame_x;
	int frame_y;
	bool frame_positioned;
	uint16_t pending_configure_mask;
	bool mapped;
	bool placed;
	bool iconified;
	bool decorated;
	bool associated;
	bool rules_initialized;
	bool auto_raise;
	char *icon_name;
	uint32_t net_wm_icon_width;
	uint32_t net_wm_icon_height;
	uint32_t net_wm_icon_count;
	uint32_t net_wm_icon_checksum;
	bool net_wm_icon_truncated;
	struct wl_event_source *xwayland_sync_idle;
#ifdef WTWM_TEST_CONTROL
	uint64_t test_id;
#endif
	struct wl_listener map;
	struct wl_listener unmap;
	struct wl_listener commit;
	struct wl_listener destroy;
	struct wl_listener request_move;
	struct wl_listener request_resize;
	struct wl_listener request_maximize;
	struct wl_listener request_fullscreen;
	struct wl_listener request_minimize;
	struct wl_listener set_title;
	struct wl_listener set_app_id;
	struct wl_listener associate;
	struct wl_listener dissociate;
	struct wl_listener request_configure;
	struct wl_listener set_class;
	struct wl_listener set_parent;
	struct wl_listener set_hints;
	struct wl_listener set_override_redirect;
	struct wl_listener set_geometry;
};

struct popup {
	struct wl_list link;
	struct server *server;
	struct wlr_xdg_popup *xdg;
	struct wlr_scene_tree *tree;
	struct toplevel *root;
	unsigned depth;
	bool mapped;
	struct wl_listener map;
	struct wl_listener unmap;
	struct wl_listener commit;
	struct wl_listener reposition;
	struct wl_listener destroy;
	struct wl_listener scene_destroy;
};

struct keyboard {
	struct wl_list link;
	struct server *server;
	struct wlr_keyboard *wlr;
	struct wl_listener modifiers;
	struct wl_listener key;
	struct wl_listener destroy;
};

struct output {
	struct wl_list link;
	struct server *server;
	struct wlr_output *wlr;
	struct wl_listener frame;
	struct wl_listener request_state;
	struct wl_listener destroy;
};

struct decoration {
	struct wlr_xdg_toplevel_decoration_v1 *wlr;
	struct wl_listener request_mode;
	struct wl_listener destroy;
};

struct menu_view {
	struct wlr_scene_tree *tree;
	struct wlr_scene_rect *highlight;
	const struct wtwm_menu *definition;
	struct toplevel *target;
	int x;
	int y;
	int width;
	int row_height;
	int selected;
};

struct interaction_session {
	struct wtwm_interaction_box original;
	struct wtwm_interaction_box preview;
	struct wlr_scene_tree *outline;
	struct wlr_scene_rect *outline_top;
	struct wlr_scene_rect *outline_bottom;
	struct wlr_scene_rect *outline_left;
	struct wlr_scene_rect *outline_right;
	uint32_t resize_edges;
	enum wtwm_constrained_axis constrained_axis;
	double pointer_start_x;
	double pointer_start_y;
	double grab_x;
	double grab_y;
	double resize_offset_x;
	double resize_offset_y;
	bool force_move;
	bool opaque_move;
	bool constrained_move;
	bool started;
	bool moved;
	bool raised;
};

struct action_frame {
	const struct wtwm_action *actions;
	size_t count;
	size_t next;
};

struct action_continuation {
	struct action_frame frames[9];
	size_t frame_count;
	struct toplevel *toplevel;
	uint32_t context;
	bool active;
};

struct server {
	struct wtwm_config config;
	struct wl_display *display;
	struct wlr_backend *backend;
	struct wlr_renderer *renderer;
	struct wlr_allocator *allocator;
	struct wlr_compositor *compositor;
	struct wlr_scene *scene;
	struct wlr_scene_tree *view_tree;
	struct wlr_scene_tree *overlay_tree;
	struct wlr_scene_tree *menu_tree;
	struct wlr_scene_output_layout *scene_layout;
	struct wlr_output_layout *output_layout;
	struct wl_list outputs;
	struct wl_listener new_output;
	struct wlr_xdg_shell *xdg_shell;
	struct wl_listener new_toplevel;
	struct wl_listener new_popup;
	struct wlr_xdg_decoration_manager_v1 *decoration_manager;
	struct wl_listener new_decoration;
	struct wl_list toplevels;
	struct wl_list xwayland_views;
	struct wl_list popups;
	unsigned placement_index;
	struct menu_view menu;
	struct wlr_cursor *cursor;
	struct wlr_xcursor_manager *cursor_manager;
	struct wl_listener cursor_motion;
	struct wl_listener cursor_motion_absolute;
	struct wl_listener cursor_button;
	struct wl_listener cursor_axis;
	struct wl_listener cursor_frame;
	struct wlr_seat *seat;
	struct wl_listener new_input;
	struct wl_listener request_cursor;
	struct wl_listener request_selection;
	struct wl_listener request_primary_selection;
	struct wl_list keyboards;
	struct wlr_xwayland *xwayland;
	struct wl_listener xwayland_ready;
	struct wl_listener xwayland_new_surface;
	xcb_atom_t atom_wm_protocols;
	xcb_atom_t atom_wm_delete_window;
	xcb_atom_t atom_wm_normal_hints;
	xcb_atom_t atom_wm_transient_for;
	xcb_atom_t atom_wm_icon_name;
	xcb_atom_t atom_net_wm_icon;
	char *previous_display;
	bool had_previous_display;
	bool xwayland_display_exported;
	enum cursor_mode cursor_mode;
	struct toplevel *grabbed;
	struct interaction_session interaction;
	struct action_continuation continuation;
	uint32_t current_input_time_ms;
	uint32_t last_move_time_ms;
	bool last_interaction_moved;
	uint64_t frame_sequence;
#ifdef WTWM_TEST_CONTROL
	struct test_control test_control;
#endif
};

static void new_xwayland_surface(struct wl_listener *listener, void *data);
static int xwayland_user_event(struct wlr_xwm *xwm, xcb_generic_event_t *event);
static void resume_action_continuation(struct server *server);
static struct server *xwayland_event_server;

static xcb_atom_t xwayland_atom(xcb_connection_t *connection, const char *name) {
	xcb_intern_atom_cookie_t cookie = xcb_intern_atom(
		connection, false, (uint16_t)strlen(name), name);
	xcb_intern_atom_reply_t *reply = xcb_intern_atom_reply(connection, cookie, NULL);
	if (reply == NULL) return XCB_ATOM_NONE;
	xcb_atom_t atom = reply->atom;
	free(reply);
	return atom;
}

static void xwayland_ready(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, xwayland_ready);
	(void)data;
	xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(server->xwayland);
	if (connection != NULL) {
		server->atom_wm_protocols = xwayland_atom(connection, "WM_PROTOCOLS");
		server->atom_wm_delete_window = xwayland_atom(connection, "WM_DELETE_WINDOW");
		server->atom_wm_normal_hints = xwayland_atom(connection, "WM_NORMAL_HINTS");
		server->atom_wm_transient_for = xwayland_atom(connection, "WM_TRANSIENT_FOR");
		server->atom_wm_icon_name = xwayland_atom(connection, "WM_ICON_NAME");
		server->atom_net_wm_icon = xwayland_atom(connection, "_NET_WM_ICON");
	}
	wlr_log(WLR_INFO, "Xwayland ready on DISPLAY=%s", server->xwayland->display_name);
}

static void xwayland_finish(struct server *server) {
	if (server->xwayland != NULL) {
		wl_list_remove(&server->xwayland_ready.link);
		wl_list_remove(&server->xwayland_new_surface.link);
		wlr_xwayland_destroy(server->xwayland);
		server->xwayland = NULL;
		if (xwayland_event_server == server) xwayland_event_server = NULL;
	}
	if (server->xwayland_display_exported) {
		if (server->had_previous_display)
			(void)setenv("DISPLAY", server->previous_display, true);
		else
			(void)unsetenv("DISPLAY");
		server->xwayland_display_exported = false;
	}
	free(server->previous_display);
	server->previous_display = NULL;
}

static bool xwayland_start(struct server *server) {
	const char *xwayland_override = getenv("WLR_XWAYLAND");
	if (xwayland_override != NULL && strchr(xwayland_override, '/') != NULL &&
			access(xwayland_override, X_OK) < 0) {
		wlr_log(WLR_ERROR, "Xwayland executable %s is unavailable: %s",
			xwayland_override, strerror(errno));
		return false;
	}
	server->xwayland = wlr_xwayland_create(
		server->display, server->compositor, true);
	if (server->xwayland == NULL) {
		wlr_log(WLR_ERROR, "%s", "Xwayland setup failed; continuing without X11 support");
		return false;
	}
	server->xwayland_ready.notify = xwayland_ready;
	wl_signal_add(&server->xwayland->events.ready, &server->xwayland_ready);
	server->xwayland_new_surface.notify = new_xwayland_surface;
	wl_signal_add(&server->xwayland->events.new_surface,
		&server->xwayland_new_surface);
	server->xwayland->data = server;
	server->xwayland->user_event_handler = xwayland_user_event;
	xwayland_event_server = server;
	wlr_xwayland_set_seat(server->xwayland, server->seat);

	const char *previous_display = getenv("DISPLAY");
	server->had_previous_display = previous_display != NULL;
	if (server->had_previous_display) {
		server->previous_display = strdup(previous_display);
		if (server->previous_display == NULL) {
			wlr_log(WLR_ERROR, "%s", "failed to preserve DISPLAY for Xwayland");
			xwayland_finish(server);
			return false;
		}
	}
	if (setenv("DISPLAY", server->xwayland->display_name, true) < 0) {
		wlr_log(WLR_ERROR, "failed to export Xwayland DISPLAY: %s", strerror(errno));
		xwayland_finish(server);
		return false;
	}
	server->xwayland_display_exported = true;
	wlr_log(WLR_INFO, "Xwayland allocated DISPLAY=%s", server->xwayland->display_name);
	return true;
}

struct hit_result {
	struct toplevel *toplevel;
	struct wlr_surface *surface;
	double sx;
	double sy;
	uint32_t context;
	bool left_button;
	bool right_button;
};

static struct toplevel *toplevel_from_scene_tree(struct wlr_scene_tree *tree) {
	while (tree != NULL && tree->node.data == NULL) tree = tree->node.parent;
	return tree ? tree->node.data : NULL;
}

static struct toplevel *toplevel_from_xdg(struct wlr_xdg_toplevel *xdg) {
	if (xdg == NULL || xdg->base->data == NULL) return NULL;
	struct toplevel *toplevel = toplevel_from_scene_tree(xdg->base->data);
	return toplevel != NULL && toplevel->xdg == xdg ? toplevel : NULL;
}

static struct wlr_surface *toplevel_surface(const struct toplevel *toplevel) {
	if (toplevel->xdg != NULL) return toplevel->xdg->base->surface;
	return toplevel->xwayland != NULL ? toplevel->xwayland->surface : NULL;
}

static const char *toplevel_title(const struct toplevel *toplevel) {
	const char *title = toplevel->xdg != NULL ? toplevel->xdg->title :
		(toplevel->xwayland != NULL ? toplevel->xwayland->title : NULL);
	return title != NULL ? title : "";
}

static struct toplevel *toplevel_for_surface(struct wlr_surface *surface) {
	if (surface == NULL) return NULL;
	surface = wlr_surface_get_root_surface(surface);
	struct wlr_xwayland_surface *xwayland =
		wlr_xwayland_surface_try_from_wlr_surface(surface);
	if (xwayland != NULL) return xwayland->data;
	struct wlr_xdg_popup *popup;
	while ((popup = wlr_xdg_popup_try_from_wlr_surface(surface)) != NULL) {
		if (popup->parent == NULL) return NULL;
		surface = wlr_surface_get_root_surface(popup->parent);
	}
	return toplevel_from_xdg(wlr_xdg_toplevel_try_from_wlr_surface(surface));
}

static bool surface_belongs_to_toplevel(struct wlr_surface *surface,
	struct toplevel *toplevel) {
	return toplevel_for_surface(surface) == toplevel;
}

static void color_value(const char *name, float color[4]) {
	color[0] = color[1] = color[2] = 0.2f;
	color[3] = 1.0f;
	if (name == NULL) return;
	if (name[0] == '#' && strlen(name) == 7) {
		unsigned value = 0;
		if (sscanf(name + 1, "%x", &value) == 1) {
			color[0] = (float)((value >> 16) & 255) / 255.0f;
			color[1] = (float)((value >> 8) & 255) / 255.0f;
			color[2] = (float)(value & 255) / 255.0f;
		}
		return;
	}
	if (strncasecmp(name, "gray", 4) == 0 || strncasecmp(name, "grey", 4) == 0) {
		char *end = NULL;
		long percent = strtol(name + 4, &end, 10);
		if (*end == '\0' && percent >= 0 && percent <= 100) {
			color[0] = color[1] = color[2] = (float)percent / 100.0f;
		}
		return;
	}
	if (strncasecmp(name, "rgb:", 4) == 0) {
		unsigned r = 0, g = 0, b = 0;
		char rs[5] = {0}, gs[5] = {0}, bs[5] = {0};
		if (sscanf(name + 4, "%4[^/]/%4[^/]/%4s", rs, gs, bs) == 3 &&
			sscanf(rs, "%x", &r) == 1 && sscanf(gs, "%x", &g) == 1 &&
			sscanf(bs, "%x", &b) == 1) {
			unsigned rm = (1u << (4u * (unsigned)strlen(rs))) - 1u;
			unsigned gm = (1u << (4u * (unsigned)strlen(gs))) - 1u;
			unsigned bm = (1u << (4u * (unsigned)strlen(bs))) - 1u;
			color[0] = (float)r / (float)rm;
			color[1] = (float)g / (float)gm;
			color[2] = (float)b / (float)bm;
		}
		return;
	}
	struct named_color { const char *name; float r, g, b; };
	static const struct named_color named[] = {
		{"black", 0, 0, 0}, {"white", 1, 1, 1}, {"slategrey", .44f, .50f, .56f},
		{"slategray", .44f, .50f, .56f}, {"red", 1, 0, 0}, {"green", 0, .5f, 0},
		{"blue", 0, 0, 1}, {"navy", 0, 0, .5f}, {"yellow", 1, 1, 0},
	};
	for (size_t i = 0; i < sizeof(named) / sizeof(named[0]); ++i) {
		if (strcasecmp(name, named[i].name) == 0) {
			color[0] = named[i].r; color[1] = named[i].g; color[2] = named[i].b;
			return;
		}
	}
}

static bool toplevel_matches(const struct wtwm_string_list *patterns,
		const struct toplevel *toplevel) {
	if (toplevel->xwayland != NULL)
		return wtwm_config_match_x11(patterns, toplevel->xwayland->title,
			toplevel->xwayland->instance, toplevel->xwayland->class);
	return wtwm_config_match_native(patterns, toplevel->xdg->title,
		toplevel->xdg->app_id);
}

static bool should_decorate(const struct toplevel *toplevel) {
	if (toplevel->xwayland != NULL && toplevel->xwayland->override_redirect)
		return false;
	bool transient = toplevel->xwayland != NULL &&
		toplevel->xwayland->parent != NULL;
	return wtwm_window_has_title(toplevel->server->config.no_title,
		toplevel_matches(&toplevel->server->config.make_title_windows, toplevel),
		toplevel_matches(&toplevel->server->config.no_title_windows, toplevel),
		transient, toplevel->server->config.decorate_transients);
}

static bool initialize_toplevel_rules(struct toplevel *toplevel) {
	if (toplevel->rules_initialized || (toplevel->xwayland != NULL &&
			toplevel->xwayland->override_redirect)) return false;
	toplevel->auto_raise = toplevel->server->config.auto_raise ||
		toplevel_matches(&toplevel->server->config.auto_raise_windows, toplevel);
	toplevel->rules_initialized = true;
	return true;
}

static bool should_start_iconified(const struct toplevel *toplevel,
		bool initial_rules) {
	return initial_rules && toplevel_matches(
		&toplevel->server->config.start_iconified_windows, toplevel);
}

static void sync_toplevel_popups(struct toplevel *toplevel);

static int configured_border_width(const struct server *server) {
	return server->config.border_width;
}

static int configured_title_bar_height(const struct server *server) {
	return wtwm_title_bar_height(wtwm_measure_font_height(server->config.title_font),
		server->config.frame_padding);
}

static bool toplevel_has_frame(const struct toplevel *toplevel) {
	return toplevel->xwayland == NULL || !toplevel->xwayland->override_redirect;
}

static void toplevel_geometry(const struct toplevel *toplevel,
		struct wtwm_frame_geometry *geometry) {
	wtwm_frame_geometry(toplevel->width, toplevel->height,
		toplevel_has_frame(toplevel) ? toplevel->border_width : 0,
		toplevel->title_bar_height,
		toplevel_has_frame(toplevel) && toplevel->decorated, geometry);
}

#ifdef WTWM_TEST_CONTROL
static void test_trace_copy(char destination[TEST_TRACE_IDENTITY_MAX],
		const char *source) {
	if (source == NULL) source = "";
	(void)snprintf(destination, TEST_TRACE_IDENTITY_MAX, "%s", source);
}

static int test_trace_stack_index(const struct toplevel *toplevel) {
	if (!toplevel->mapped || (toplevel->xwayland != NULL &&
			toplevel->xwayland->override_redirect)) return -1;
	int index = 0;
	struct toplevel *item;
	wl_list_for_each(item, &toplevel->server->toplevels, link) {
		if (item == toplevel) return index;
		++index;
	}
	return -1;
}

static struct test_trace_event *test_trace_append(struct toplevel *toplevel,
		const char *event, const char *context, int frame_x, int frame_y,
		int width, int height) {
	struct test_control *control = &toplevel->server->test_control;
	uint64_t sequence = ++control->trace_next_sequence;
	if (control->trace_event_count == TEST_TRACE_MAX_EVENTS) {
		++control->trace_dropped;
		return NULL;
	}
	if (control->trace_event_count == control->trace_event_capacity) {
		size_t capacity = control->trace_event_capacity == 0 ?
			TEST_TRACE_INITIAL_CAPACITY : control->trace_event_capacity * 2;
		if (capacity > TEST_TRACE_MAX_EVENTS) capacity = TEST_TRACE_MAX_EVENTS;
		struct test_trace_event *events = realloc(control->trace_events,
			capacity * sizeof(*events));
		if (events == NULL) {
			++control->trace_dropped;
			return NULL;
		}
		control->trace_events = events;
		control->trace_event_capacity = capacity;
	}
	struct test_trace_event *trace =
		&control->trace_events[control->trace_event_count++];
	memset(trace, 0, sizeof(*trace));
	trace->sequence = sequence;
	trace->window_id = toplevel->test_id;
	(void)snprintf(trace->event, sizeof(trace->event), "%s", event);
	(void)snprintf(trace->context, sizeof(trace->context), "%s", context);
	(void)snprintf(trace->type, sizeof(trace->type), "%s",
		toplevel->xwayland != NULL ? "x11" : "wayland");
	test_trace_copy(trace->title, toplevel_title(toplevel));
	const char *app_id = toplevel->xdg != NULL ? toplevel->xdg->app_id :
		(toplevel->xwayland != NULL ? toplevel->xwayland->class : NULL);
	test_trace_copy(trace->app_id, app_id);
	test_trace_copy(trace->instance, toplevel->xwayland != NULL ?
		toplevel->xwayland->instance : NULL);
	test_trace_copy(trace->class_name, toplevel->xwayland != NULL ?
		toplevel->xwayland->class : NULL);
	test_trace_copy(trace->icon_name, toplevel->icon_name);
	struct wtwm_frame_geometry geometry;
	wtwm_frame_geometry(width, height,
		toplevel_has_frame(toplevel) ? toplevel->border_width : 0,
		toplevel->title_bar_height,
		toplevel_has_frame(toplevel) && toplevel->decorated, &geometry);
	trace->client_x = frame_x + geometry.content_x;
	trace->client_y = frame_y + geometry.content_y;
	trace->client_width = geometry.client_width;
	trace->client_height = geometry.client_height;
	trace->frame_x = frame_x;
	trace->frame_y = frame_y;
	trace->frame_width = geometry.frame_width;
	trace->frame_height = geometry.frame_height;
	trace->outer_width = geometry.outer_width;
	trace->outer_height = geometry.outer_height;
	trace->border_width = geometry.border_width;
	trace->title_bar_height = geometry.title_bar_height;
	trace->title_height = geometry.title_extent;
	trace->content_x = geometry.content_x;
	trace->content_y = geometry.content_y;
	trace->stack = test_trace_stack_index(toplevel);
	trace->mapped = toplevel->mapped;
	trace->iconified = toplevel->iconified;
	trace->focused = surface_belongs_to_toplevel(
		toplevel->server->seat->keyboard_state.focused_surface, toplevel);
	return trace;
}

static void test_trace_toplevel_event_at(struct toplevel *toplevel,
		const char *event, const char *context, int frame_x, int frame_y,
		int width, int height) {
	(void)test_trace_append(toplevel, event, context,
		frame_x, frame_y, width, height);
}

static void test_trace_toplevel_event(struct toplevel *toplevel,
		const char *event, const char *context) {
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	int frame_x = toplevel->frame_x;
	int frame_y = toplevel->frame_y;
	if (toplevel->tree != NULL) {
		frame_x = toplevel->tree->node.x;
		frame_y = toplevel->tree->node.y;
	} else if (toplevel->xwayland != NULL && !toplevel->frame_positioned) {
		frame_x = toplevel->xwayland->x - geometry.content_x;
		frame_y = toplevel->xwayland->y - geometry.content_y;
	}
	test_trace_toplevel_event_at(toplevel, event, context,
		frame_x, frame_y, toplevel->width, toplevel->height);
}

static void test_trace_assign_id(struct toplevel *toplevel) {
	toplevel->test_id = ++toplevel->server->test_control.trace_next_window_id;
}

static void test_trace_input_snapshot(struct server *server,
		const char *event) {
	struct toplevel *toplevel;
	wl_list_for_each(toplevel, &server->toplevels, link)
		test_trace_toplevel_event(toplevel, event, "input");
}
#else
static void test_trace_toplevel_event_at(struct toplevel *toplevel,
		const char *event, const char *context, int frame_x, int frame_y,
		int width, int height) {
	(void)toplevel;
	(void)event;
	(void)context;
	(void)frame_x;
	(void)frame_y;
	(void)width;
	(void)height;
}

static void test_trace_toplevel_event(struct toplevel *toplevel,
		const char *event, const char *context) {
	(void)toplevel;
	(void)event;
	(void)context;
}

static void test_trace_assign_id(struct toplevel *toplevel) {
	(void)toplevel;
}
#endif

static void xwayland_gravity_offsets(const struct toplevel *toplevel,
		int *gravity_x, int *gravity_y) {
	uint32_t gravity = XCB_GRAVITY_NORTH_WEST;
	if (toplevel->xwayland != NULL && toplevel->xwayland->size_hints != NULL &&
			(toplevel->xwayland->size_hints->flags &
				XCB_ICCCM_SIZE_HINT_P_WIN_GRAVITY) != 0)
		gravity = toplevel->xwayland->size_hints->win_gravity;
	switch (gravity) {
	case XCB_GRAVITY_NORTH_EAST:
	case XCB_GRAVITY_EAST:
	case XCB_GRAVITY_SOUTH_EAST: *gravity_x = 1; break;
	case XCB_GRAVITY_NORTH:
	case XCB_GRAVITY_CENTER:
	case XCB_GRAVITY_SOUTH: *gravity_x = 0; break;
	default: *gravity_x = -1; break;
	}
	switch (gravity) {
	case XCB_GRAVITY_SOUTH_WEST:
	case XCB_GRAVITY_SOUTH:
	case XCB_GRAVITY_SOUTH_EAST: *gravity_y = 1; break;
	case XCB_GRAVITY_WEST:
	case XCB_GRAVITY_CENTER:
	case XCB_GRAVITY_EAST: *gravity_y = 0; break;
	default: *gravity_y = -1; break;
	}
}

static void update_title_text(struct toplevel *toplevel) {
	if (toplevel->title_text == NULL) return;
	toplevel->title_bar_height = configured_title_bar_height(toplevel->server);
	float foreground[4];
	color_value(toplevel->server->config.title_foreground, foreground);
	int width = 0, height = 0;
	struct wlr_buffer *buffer = wtwm_render_text(toplevel_title(toplevel),
		toplevel->server->config.title_font, foreground, &width, &height);
	if (buffer == NULL) return;
	toplevel->title_text_height = height;
	wlr_scene_buffer_set_buffer(toplevel->title_text, buffer);
	wlr_buffer_drop(buffer);
}

static void update_decoration(struct toplevel *toplevel) {
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	toplevel->title_height = geometry.title_extent;
	int border = geometry.border_width;
	int button = geometry.title_bar_height -
		2 * (toplevel->server->config.frame_padding +
			toplevel->server->config.button_indent);
	if (button < 1) button = 1;
	int title_padding = toplevel->server->config.title_padding;
	if (title_padding < 1) title_padding = 1;
	wlr_scene_rect_set_size(toplevel->frame,
		geometry.outer_width, geometry.outer_height);
	wlr_scene_rect_set_size(toplevel->title,
		geometry.client_width, geometry.title_bar_height > 0 ?
			geometry.title_bar_height : 1);
	wlr_scene_rect_set_size(toplevel->focus_mark,
		geometry.client_width > 2 * (button + title_padding) ?
			geometry.client_width - 2 * (button + title_padding) : 1, 2);
	wlr_scene_rect_set_size(toplevel->left_button, button, button);
	wlr_scene_rect_set_size(toplevel->right_button, button, button);
	wlr_scene_rect_set_size(toplevel->right_inner, button > 8 ? button - 8 : 1,
		button > 8 ? button - 8 : 1);
	wlr_scene_node_set_position(&toplevel->title->node, border, border);
	wlr_scene_node_set_position(&toplevel->focus_mark->node,
		border + button + title_padding,
		border + geometry.title_bar_height - 4);
	wlr_scene_node_set_position(&toplevel->left_button->node, border + 2, border + 2);
	wlr_scene_node_set_position(&toplevel->left_dot->node,
		border + button / 2, border + button / 2);
	wlr_scene_node_set_position(&toplevel->right_button->node,
		border + geometry.client_width - button - 2, border + 2);
	wlr_scene_node_set_position(&toplevel->right_inner->node,
		border + geometry.client_width - button + 2, border + 6);
	wlr_scene_node_set_position(&toplevel->title_text->node,
		border + button + title_padding + 1,
		border + (geometry.title_bar_height - toplevel->title_text_height) / 2);
	wlr_scene_node_set_position(&toplevel->content->node,
		geometry.content_x, geometry.content_y);
	sync_toplevel_popups(toplevel);
}

static void set_decorated(struct toplevel *toplevel, bool enabled) {
	toplevel->decorated = enabled;
	if (toplevel->title == NULL) return;
	wlr_scene_node_set_enabled(&toplevel->frame->node, toplevel_has_frame(toplevel));
	wlr_scene_node_set_enabled(&toplevel->title->node, enabled);
	wlr_scene_node_set_enabled(&toplevel->focus_mark->node, false);
	wlr_scene_node_set_enabled(&toplevel->left_button->node, enabled);
	wlr_scene_node_set_enabled(&toplevel->left_dot->node, enabled);
	wlr_scene_node_set_enabled(&toplevel->right_button->node, enabled);
	wlr_scene_node_set_enabled(&toplevel->right_inner->node, enabled);
	wlr_scene_node_set_enabled(&toplevel->title_text->node, enabled);
	update_decoration(toplevel);
}

static void set_focused_marker(struct server *server, struct toplevel *focused) {
	struct toplevel *item;
	wl_list_for_each(item, &server->toplevels, link) {
		if (item->focus_mark != NULL)
			wlr_scene_node_set_enabled(&item->focus_mark->node,
				item == focused && item->decorated);
	}
}

static int toplevel_content_x(const struct toplevel *toplevel) {
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	return geometry.content_x;
}

static int toplevel_content_y(const struct toplevel *toplevel) {
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	return geometry.content_y;
}

static void constrain_toplevel_size(struct toplevel *toplevel,
		int *width, int *height) {
	struct wtwm_size_hints constraints = {0};
	int limit = toplevel->xwayland != NULL ? UINT16_MAX : INT_MAX;
	if (toplevel->xwayland != NULL && toplevel->xwayland->size_hints != NULL) {
		xcb_size_hints_t *hints = toplevel->xwayland->size_hints;
		if ((hints->flags & XCB_ICCCM_SIZE_HINT_P_MIN_SIZE) != 0)
			constraints.flags |= WTWM_SIZE_HINT_MIN;
		if ((hints->flags & XCB_ICCCM_SIZE_HINT_P_MAX_SIZE) != 0)
			constraints.flags |= WTWM_SIZE_HINT_MAX;
		if ((hints->flags & XCB_ICCCM_SIZE_HINT_BASE_SIZE) != 0)
			constraints.flags |= WTWM_SIZE_HINT_BASE;
		if ((hints->flags & XCB_ICCCM_SIZE_HINT_P_RESIZE_INC) != 0)
			constraints.flags |= WTWM_SIZE_HINT_INCREMENT;
		if ((hints->flags & XCB_ICCCM_SIZE_HINT_P_ASPECT) != 0)
			constraints.flags |= WTWM_SIZE_HINT_ASPECT;
		constraints.min_width = hints->min_width;
		constraints.min_height = hints->min_height;
		constraints.max_width = hints->max_width;
		constraints.max_height = hints->max_height;
		constraints.base_width = hints->base_width;
		constraints.base_height = hints->base_height;
		constraints.width_increment = hints->width_inc;
		constraints.height_increment = hints->height_inc;
		constraints.min_aspect_x = hints->min_aspect_num;
		constraints.min_aspect_y = hints->min_aspect_den;
		constraints.max_aspect_x = hints->max_aspect_num;
		constraints.max_aspect_y = hints->max_aspect_den;
	} else if (toplevel->xdg != NULL) {
		if (toplevel->xdg->current.min_width > 0 ||
				toplevel->xdg->current.min_height > 0)
			constraints.flags |= WTWM_SIZE_HINT_MIN;
		if (toplevel->xdg->current.max_width > 0 ||
				toplevel->xdg->current.max_height > 0)
			constraints.flags |= WTWM_SIZE_HINT_MAX;
		constraints.min_width = toplevel->xdg->current.min_width > 0 ?
			toplevel->xdg->current.min_width : 1;
		constraints.min_height = toplevel->xdg->current.min_height > 0 ?
			toplevel->xdg->current.min_height : 1;
		constraints.max_width = toplevel->xdg->current.max_width > 0 ?
			toplevel->xdg->current.max_width : limit;
		constraints.max_height = toplevel->xdg->current.max_height > 0 ?
			toplevel->xdg->current.max_height : limit;
	}
	wtwm_constrain_size(&constraints, limit, limit, width, height);
}

static void configure_xwayland_frame(struct toplevel *toplevel,
		int frame_x, int frame_y, int width, int height) {
	if (width < 1) width = 1;
	if (height < 1) height = 1;
	if (width > UINT16_MAX) width = UINT16_MAX;
	if (height > UINT16_MAX) height = UINT16_MAX;
	toplevel->width = width;
	toplevel->height = height;
	if (toplevel->tree != NULL) {
		wlr_scene_node_set_position(&toplevel->tree->node, frame_x, frame_y);
		if (!toplevel->xwayland->override_redirect) {
			toplevel->frame_x = frame_x;
			toplevel->frame_y = frame_y;
			toplevel->frame_positioned = true;
		}
	}
	int client_x = frame_x + toplevel_content_x(toplevel);
	int client_y = frame_y + toplevel_content_y(toplevel);
	if (client_x < INT16_MIN) client_x = INT16_MIN;
	if (client_x > INT16_MAX) client_x = INT16_MAX;
	if (client_y < INT16_MIN) client_y = INT16_MIN;
	if (client_y > INT16_MAX) client_y = INT16_MAX;
	wlr_xwayland_surface_configure(toplevel->xwayland,
		(int16_t)client_x, (int16_t)client_y, (uint16_t)width, (uint16_t)height);
	if (toplevel->tree != NULL && toplevel->content != NULL)
		update_decoration(toplevel);
	test_trace_toplevel_event_at(toplevel, "configure", "client",
		frame_x, frame_y, width, height);
}

static void configure_xwayland_client(struct toplevel *toplevel,
		int client_x, int client_y, int width, int height) {
	configure_xwayland_frame(toplevel,
		client_x - toplevel_content_x(toplevel),
		client_y - toplevel_content_y(toplevel), width, height);
}

static void set_toplevel_position(struct toplevel *toplevel, int x, int y) {
	int old_x = toplevel->tree->node.x;
	int old_y = toplevel->tree->node.y;
	if (toplevel->xwayland == NULL) {
		wlr_scene_node_set_position(&toplevel->tree->node, x, y);
		sync_toplevel_popups(toplevel);
	} else {
		configure_xwayland_frame(toplevel, x, y,
			toplevel->width, toplevel->height);
	}
	if (x != old_x || y != old_y)
		test_trace_toplevel_event_at(toplevel, "move", "frame",
			x, y, toplevel->width, toplevel->height);
}

static void set_toplevel_box(struct toplevel *toplevel,
		int x, int y, int width, int height) {
	int old_x = toplevel->tree->node.x;
	int old_y = toplevel->tree->node.y;
	constrain_toplevel_size(toplevel, &width, &height);
	if (toplevel->xwayland == NULL) {
		wlr_scene_node_set_position(&toplevel->tree->node, x, y);
		sync_toplevel_popups(toplevel);
		wlr_xdg_toplevel_set_size(toplevel->xdg, width, height);
	} else {
		configure_xwayland_frame(toplevel, x, y, width, height);
	}
	if (x != old_x || y != old_y)
		test_trace_toplevel_event_at(toplevel, "move", "frame",
			x, y, width, height);
	test_trace_toplevel_event_at(toplevel, "resize", "frame",
		x, y, width, height);
}

static void activate_toplevel(struct toplevel *toplevel, bool activated) {
	if (toplevel->xdg != NULL)
		wlr_xdg_toplevel_set_activated(toplevel->xdg, activated);
	else
		wlr_xwayland_surface_activate(toplevel->xwayland, activated);
}

static void suspend_toplevel(struct toplevel *toplevel, bool suspended) {
	if (toplevel->xdg != NULL)
		wlr_xdg_toplevel_set_suspended(toplevel->xdg, suspended);
	else
		wlr_xwayland_surface_set_minimized(toplevel->xwayland, suspended);
}

static void focus_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || toplevel->iconified || !toplevel->mapped) return;
	struct server *server = toplevel->server;
	struct wlr_surface *surface = toplevel_surface(toplevel);
	if (surface == NULL || (toplevel->xwayland != NULL &&
			toplevel->xwayland->override_redirect)) return;
	struct wlr_surface *previous = server->seat->keyboard_state.focused_surface;
	struct toplevel *old = toplevel_for_surface(previous);
	bool changed = previous != surface;
	if (previous != surface) {
		if (old != NULL) activate_toplevel(old, false);
	}
	wlr_scene_node_raise_to_top(&toplevel->tree->node);
	wl_list_remove(&toplevel->link);
	wl_list_insert(&server->toplevels, &toplevel->link);
	if (toplevel->xwayland != NULL)
		wlr_xwayland_surface_restack(toplevel->xwayland, NULL, XCB_STACK_MODE_ABOVE);
	test_trace_toplevel_event(toplevel, "raise", "frame");
	activate_toplevel(toplevel, true);
	set_focused_marker(server, toplevel);
	struct wlr_keyboard *keyboard = wlr_seat_get_keyboard(server->seat);
	if (keyboard != NULL) {
		wlr_seat_keyboard_notify_enter(server->seat, surface, keyboard->keycodes,
			keyboard->num_keycodes, &keyboard->modifiers);
	}
	if (changed && old != NULL)
		test_trace_toplevel_event(old, "unfocus", "client");
	if (changed) test_trace_toplevel_event(toplevel, "focus", "client");
}

static void clear_keyboard_focus(struct server *server) {
	struct toplevel *old = toplevel_for_surface(
		server->seat->keyboard_state.focused_surface);
	wlr_seat_keyboard_clear_focus(server->seat);
	set_focused_marker(server, NULL);
	if (old != NULL) test_trace_toplevel_event(old, "unfocus", "client");
}

static void focus_next(struct server *server) {
	struct toplevel *item;
	wl_list_for_each(item, &server->toplevels, link) {
		if (item->mapped && !item->iconified) {
			focus_toplevel(item);
			return;
		}
	}
	clear_keyboard_focus(server);
}

static void lower_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped) return;
	wlr_scene_node_lower_to_bottom(&toplevel->tree->node);
	if (toplevel->xwayland != NULL)
		wlr_xwayland_surface_restack(toplevel->xwayland, NULL, XCB_STACK_MODE_BELOW);
	wl_list_remove(&toplevel->link);
	wl_list_insert(toplevel->server->toplevels.prev, &toplevel->link);
	test_trace_toplevel_event(toplevel, "lower", "frame");
}

static void raise_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped) return;
	wlr_scene_node_raise_to_top(&toplevel->tree->node);
	wl_list_remove(&toplevel->link);
	wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
	if (toplevel->xwayland != NULL)
		wlr_xwayland_surface_restack(toplevel->xwayland, NULL, XCB_STACK_MODE_ABOVE);
	test_trace_toplevel_event(toplevel, "raise", "frame");
}

static void clear_interaction_outline(struct server *server) {
	if (server->interaction.outline != NULL)
		wlr_scene_node_destroy(&server->interaction.outline->node);
	server->interaction.outline = NULL;
	server->interaction.outline_top = NULL;
	server->interaction.outline_bottom = NULL;
	server->interaction.outline_left = NULL;
	server->interaction.outline_right = NULL;
}

static void show_interaction_outline(struct server *server) {
	struct toplevel *toplevel = server->grabbed;
	if (toplevel == NULL) return;
	struct wtwm_frame_geometry geometry;
	wtwm_frame_geometry(server->interaction.preview.width,
		server->interaction.preview.height,
		toplevel_has_frame(toplevel) ? toplevel->border_width : 0,
		toplevel->title_bar_height,
		toplevel_has_frame(toplevel) && toplevel->decorated, &geometry);
	if (server->interaction.outline == NULL) {
		float color[4] = {1.0f, 1.0f, 1.0f, 1.0f};
		server->interaction.outline = wlr_scene_tree_create(server->overlay_tree);
		if (server->interaction.outline == NULL) return;
		server->interaction.outline_top = wlr_scene_rect_create(
			server->interaction.outline, 1, 1, color);
		server->interaction.outline_bottom = wlr_scene_rect_create(
			server->interaction.outline, 1, 1, color);
		server->interaction.outline_left = wlr_scene_rect_create(
			server->interaction.outline, 1, 1, color);
		server->interaction.outline_right = wlr_scene_rect_create(
			server->interaction.outline, 1, 1, color);
		if (server->interaction.outline_top == NULL ||
				server->interaction.outline_bottom == NULL ||
				server->interaction.outline_left == NULL ||
				server->interaction.outline_right == NULL) {
			clear_interaction_outline(server);
			return;
		}
	}
	wlr_scene_node_set_position(&server->interaction.outline->node,
		server->interaction.preview.x, server->interaction.preview.y);
	wlr_scene_rect_set_size(server->interaction.outline_top,
		geometry.outer_width, 1);
	wlr_scene_rect_set_size(server->interaction.outline_bottom,
		geometry.outer_width, 1);
	wlr_scene_rect_set_size(server->interaction.outline_left,
		1, geometry.outer_height);
	wlr_scene_rect_set_size(server->interaction.outline_right,
		1, geometry.outer_height);
	wlr_scene_node_set_position(&server->interaction.outline_bottom->node,
		0, geometry.outer_height > 0 ? geometry.outer_height - 1 : 0);
	wlr_scene_node_set_position(&server->interaction.outline_right->node,
		geometry.outer_width > 0 ? geometry.outer_width - 1 : 0, 0);
	test_trace_toplevel_event_at(toplevel, "outline",
		server->cursor_mode == CURSOR_MOVE ? "move" : "resize",
		server->interaction.preview.x, server->interaction.preview.y,
		server->interaction.preview.width, server->interaction.preview.height);
}

static void reset_cursor(struct server *server) {
	clear_interaction_outline(server);
	server->cursor_mode = CURSOR_PASSTHROUGH;
	server->grabbed = NULL;
	memset(&server->interaction, 0, sizeof(server->interaction));
}

static uint32_t resize_edges_from_wlr(uint32_t edges) {
	uint32_t converted = WTWM_RESIZE_EDGE_NONE;
	if ((edges & WLR_EDGE_LEFT) != 0) converted |= WTWM_RESIZE_EDGE_LEFT;
	if ((edges & WLR_EDGE_RIGHT) != 0) converted |= WTWM_RESIZE_EDGE_RIGHT;
	if ((edges & WLR_EDGE_TOP) != 0) converted |= WTWM_RESIZE_EDGE_TOP;
	if ((edges & WLR_EDGE_BOTTOM) != 0) converted |= WTWM_RESIZE_EDGE_BOTTOM;
	return converted;
}

static void begin_interactive(struct toplevel *toplevel, enum cursor_mode mode,
		uint32_t edges, bool force_move, bool from_titlebar, uint32_t time_msec) {
	if (toplevel == NULL || !toplevel->mapped || toplevel->iconified) return;
	struct server *server = toplevel->server;
	if (server->grabbed != NULL) return;
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	server->grabbed = toplevel;
	server->cursor_mode = mode;
	server->last_interaction_moved = false;
	server->interaction = (struct interaction_session){
		.original = {
			.x = toplevel->tree->node.x,
			.y = toplevel->tree->node.y,
			.width = toplevel->width,
			.height = toplevel->height,
		},
		.preview = {
			.x = toplevel->tree->node.x,
			.y = toplevel->tree->node.y,
			.width = toplevel->width,
			.height = toplevel->height,
		},
		.pointer_start_x = server->cursor->x,
		.pointer_start_y = server->cursor->y,
		.force_move = force_move,
		.opaque_move = mode == CURSOR_MOVE && server->config.opaque_move,
		.started = server->config.move_delta <= 0,
	};
	if (mode == CURSOR_MOVE) {
		uint32_t elapsed = time_msec - server->last_move_time_ms;
		if (wtwm_constrained_move_entry(server->config.constrained_move_time,
				elapsed)) {
			server->interaction.constrained_move = true;
			server->interaction.constrained_axis = WTWM_AXIS_NONE;
			double center_x = server->interaction.original.x +
				geometry.border_width + geometry.frame_width / 2.0;
			double center_y = server->interaction.original.y +
				geometry.border_width + geometry.frame_height / 2.0;
			wlr_cursor_warp_closest(server->cursor, NULL, center_x, center_y);
		} else {
			server->interaction.constrained_axis = WTWM_AXIS_NONE;
		}
		server->last_move_time_ms = time_msec;
		server->interaction.grab_x = server->cursor->x -
			server->interaction.original.x;
		server->interaction.grab_y = server->cursor->y -
			server->interaction.original.y;
		if (!server->interaction.opaque_move && server->interaction.started)
			show_interaction_outline(server);
		return;
	}
	server->interaction.resize_edges = resize_edges_from_wlr(edges);
	if (server->interaction.resize_edges == WTWM_RESIZE_EDGE_NONE &&
			server->config.auto_relative_resize) {
		server->interaction.resize_edges = wtwm_auto_relative_resize_edges(
			geometry.frame_width, geometry.frame_height, geometry.title_extent,
			(int)server->cursor->x - (server->interaction.original.x +
				geometry.border_width),
			(int)server->cursor->y - (server->interaction.original.y +
				geometry.border_width), from_titlebar);
	}
	double inner_left = server->interaction.original.x + geometry.border_width;
	double inner_top = server->interaction.original.y + geometry.border_width;
	double edge_x = (server->interaction.resize_edges & WTWM_RESIZE_EDGE_LEFT) != 0 ?
		inner_left : inner_left + geometry.frame_width;
	double edge_y = (server->interaction.resize_edges & WTWM_RESIZE_EDGE_TOP) != 0 ?
		inner_top : inner_top + geometry.frame_height;
	server->interaction.resize_offset_x = server->cursor->x - edge_x;
	server->interaction.resize_offset_y = server->cursor->y - edge_y;
	show_interaction_outline(server);
}

static void finish_interactive(struct server *server, bool aborted) {
	struct toplevel *toplevel = server->grabbed;
	if (toplevel == NULL) return;
	struct interaction_session interaction = server->interaction;
	enum cursor_mode mode = server->cursor_mode;
	clear_interaction_outline(server);
	if (aborted) {
		if (mode == CURSOR_MOVE && interaction.opaque_move)
			set_toplevel_position(toplevel,
				interaction.original.x, interaction.original.y);
		test_trace_toplevel_event_at(toplevel, "abort",
			mode == CURSOR_MOVE ? "move" : "resize",
			interaction.original.x, interaction.original.y,
			interaction.original.width, interaction.original.height);
	} else if (mode == CURSOR_MOVE) {
		if (!interaction.opaque_move && interaction.started) {
			set_toplevel_position(toplevel,
				interaction.preview.x, interaction.preview.y);
			if (!server->config.no_raise_on_move) raise_toplevel(toplevel);
		}
		test_trace_toplevel_event_at(toplevel, "commit", "move",
			interaction.preview.x, interaction.preview.y,
			interaction.preview.width, interaction.preview.height);
	} else {
		set_toplevel_box(toplevel,
			interaction.preview.x, interaction.preview.y,
			interaction.preview.width, interaction.preview.height);
		if (!server->config.no_raise_on_resize) raise_toplevel(toplevel);
		test_trace_toplevel_event_at(toplevel, "commit", "resize",
			interaction.preview.x, interaction.preview.y,
			interaction.preview.width, interaction.preview.height);
	}
	server->last_interaction_moved = aborted ? false : interaction.moved;
	reset_cursor(server);
	resume_action_continuation(server);
}

static bool spawn_shell(const char *command) {
	if (command == NULL || command[0] == '\0') return true;
	pid_t intermediate = fork();
	if (intermediate < 0) {
		wlr_log_errno(WLR_ERROR, "%s", "failed to fork shell launcher");
		return false;
	}
	if (intermediate == 0) {
		pid_t child = fork();
		if (child < 0) _exit(EXIT_FAILURE);
		if (child == 0) {
			execl("/bin/sh", "/bin/sh", "-c", command, (void *)NULL);
			_exit(127);
		}
		_exit(EXIT_SUCCESS);
	}

	int status;
	while (waitpid(intermediate, &status, 0) < 0) {
		if (errno == EINTR) continue;
		wlr_log_errno(WLR_ERROR, "%s", "failed to reap shell launcher");
		return false;
	}
	if (!WIFEXITED(status) || WEXITSTATUS(status) != EXIT_SUCCESS) {
		wlr_log(WLR_ERROR, "%s", "failed to launch shell command");
		return false;
	}
	return true;
}

static void hide_menu(struct server *server) {
	if (server->menu.tree != NULL) wlr_scene_node_destroy(&server->menu.tree->node);
	memset(&server->menu, 0, sizeof(server->menu));
	server->menu.selected = -1;
}

static void show_menu(struct server *server, const char *name,
	struct toplevel *target) {
	const struct wtwm_menu *menu = NULL;
	for (size_t i = 0; i < server->config.menu_count; ++i) {
		if (strcmp(server->config.menus[i].name, name) == 0) {
			menu = &server->config.menus[i];
			break;
		}
	}
	if (menu == NULL || menu->item_count == 0) {
		wlr_log(WLR_ERROR, "menu '%s' is not defined", name);
		return;
	}
	hide_menu(server);
	struct wlr_buffer **buffers = calloc(menu->item_count, sizeof(*buffers));
	int *widths = calloc(menu->item_count, sizeof(*widths));
	int *heights = calloc(menu->item_count, sizeof(*heights));
	if (buffers == NULL || widths == NULL || heights == NULL) {
		free(buffers); free(widths); free(heights); return;
	}
	int content_width = 1;
	int row_height = 18;
	for (size_t i = 0; i < menu->item_count; ++i) {
		float color[4];
		const char *color_name = menu->items[i].foreground[0] ?
			menu->items[i].foreground :
			(menu->items[i].action.type == WTWM_ACTION_TITLE ?
				server->config.menu_title_foreground : server->config.menu_foreground);
		color_value(color_name, color);
		buffers[i] = wtwm_render_text(menu->items[i].label,
			server->config.menu_font, color, &widths[i], &heights[i]);
		if (widths[i] > content_width) content_width = widths[i];
		if (heights[i] + 6 > row_height) row_height = heights[i] + 6;
	}
	int border_width = server->config.menu_border_width;
	if (border_width < 1) border_width = 1;
	int menu_width = content_width + 16 + 2 * border_width;
	int menu_height = (int)menu->item_count * row_height + 2 * border_width;
	float border[4], background[4], highlight[4];
	color_value(server->config.menu_border_color, border);
	color_value(server->config.menu_background, background);
	color_value(server->config.menu_foreground, highlight);
	highlight[3] = 0.30f;
	struct wlr_scene_tree *tree = wlr_scene_tree_create(server->menu_tree);
	wlr_scene_rect_create(tree, menu_width, menu_height, border);
	struct wlr_scene_rect *body = wlr_scene_rect_create(tree,
		menu_width - 2 * border_width, menu_height - 2 * border_width, background);
	wlr_scene_node_set_position(&body->node, border_width, border_width);
	for (size_t i = 0; i < menu->item_count; ++i) {
		if (menu->items[i].action.type == WTWM_ACTION_TITLE ||
			menu->items[i].background[0]) {
			float row_color[4];
			color_value(menu->items[i].background[0] ? menu->items[i].background :
				server->config.menu_title_background, row_color);
			struct wlr_scene_rect *row = wlr_scene_rect_create(tree,
				menu_width - 2 * border_width, row_height, row_color);
			wlr_scene_node_set_position(&row->node, border_width,
				border_width + (int)i * row_height);
		}
	}
	struct wlr_scene_rect *selection = wlr_scene_rect_create(tree,
		menu_width - 2 * border_width, row_height, highlight);
	wlr_scene_node_set_enabled(&selection->node, false);
	for (size_t i = 0; i < menu->item_count; ++i) {
		if (buffers[i] == NULL) continue;
		struct wlr_scene_buffer *text = wlr_scene_buffer_create(tree, buffers[i]);
		wlr_scene_node_set_position(&text->node, border_width + 8,
			border_width + (int)i * row_height + (row_height - heights[i]) / 2);
		wlr_buffer_drop(buffers[i]);
	}
	free(buffers); free(widths); free(heights);
	server->menu = (struct menu_view){
		.tree = tree,
		.highlight = selection,
		.definition = menu,
		.target = target,
		.x = (int)server->cursor->x,
		.y = (int)server->cursor->y,
		.width = menu_width,
		.row_height = row_height,
		.selected = -1,
	};
	wlr_scene_node_set_position(&tree->node, server->menu.x, server->menu.y);
}

static int menu_item_at(struct server *server) {
	if (server->menu.tree == NULL) return -1;
	int border = server->config.menu_border_width;
	if (border < 1) border = 1;
	int x = (int)server->cursor->x - server->menu.x;
	int y = (int)server->cursor->y - server->menu.y - border;
	if (x < border || x >= server->menu.width - border || y < 0) return -1;
	int item = y / server->menu.row_height;
	return item >= 0 && (size_t)item < server->menu.definition->item_count ? item : -1;
}

static void update_menu_selection(struct server *server) {
	int selected = menu_item_at(server);
	server->menu.selected = selected;
	wlr_scene_node_set_enabled(&server->menu.highlight->node, selected >= 0);
	if (selected >= 0) {
		int border = server->config.menu_border_width;
		if (border < 1) border = 1;
		wlr_scene_node_set_position(&server->menu.highlight->node, border,
			border + selected * server->menu.row_height);
	}
}

static bool xwayland_supports_delete(struct toplevel *toplevel) {
	if (toplevel->xwayland == NULL ||
			toplevel->server->atom_wm_delete_window == XCB_ATOM_NONE) return false;
	for (size_t i = 0; i < toplevel->xwayland->protocols_len; ++i) {
		if (toplevel->xwayland->protocols[i] ==
				toplevel->server->atom_wm_delete_window) return true;
	}
	return false;
}

static void delete_toplevel(struct toplevel *toplevel) {
	if (toplevel->xdg != NULL) {
		wlr_xdg_toplevel_send_close(toplevel->xdg);
		return;
	}
	if (!xwayland_supports_delete(toplevel)) {
		wlr_log(WLR_INFO, "X11 window 0x%08" PRIx32
			" does not advertise WM_DELETE_WINDOW", toplevel->xwayland->window_id);
		return;
	}
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(toplevel->server->xwayland);
	if (connection == NULL) return;
	xcb_client_message_event_t event = {
		.response_type = XCB_CLIENT_MESSAGE,
		.format = 32,
		.sequence = 0,
		.window = toplevel->xwayland->window_id,
		.type = toplevel->server->atom_wm_protocols,
	};
	event.data.data32[0] = toplevel->server->atom_wm_delete_window;
	event.data.data32[1] = XCB_CURRENT_TIME;
	xcb_send_event(connection, false, toplevel->xwayland->window_id,
		XCB_EVENT_MASK_NO_EVENT, (const char *)&event);
	xcb_flush(connection);
}

static void destroy_toplevel_client(struct toplevel *toplevel) {
	if (toplevel->xdg != NULL) {
		wlr_xdg_toplevel_send_close(toplevel->xdg);
		return;
	}
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(toplevel->server->xwayland);
	if (connection == NULL) return;
	xcb_kill_client(connection, toplevel->xwayland->window_id);
	xcb_flush(connection);
}

static const struct wtwm_function *find_function(struct server *server,
		const char *name) {
	for (size_t i = 0; i < server->config.function_count; ++i) {
		if (strcmp(server->config.functions[i].name, name) == 0)
			return &server->config.functions[i];
	}
	return NULL;
}

static void execute_action(struct server *server, struct toplevel *toplevel,
		const struct wtwm_action *action, uint32_t context);

static bool push_action_frame(struct action_continuation *continuation,
		const struct wtwm_function *function) {
	if (function == NULL || continuation->frame_count == 9) return false;
	continuation->frames[continuation->frame_count++] = (struct action_frame){
		.actions = function->actions,
		.count = function->action_count,
	};
	return true;
}

static void resume_action_continuation(struct server *server) {
	struct action_continuation *continuation = &server->continuation;
	while (continuation->active && continuation->frame_count != 0) {
		struct action_frame *frame =
			&continuation->frames[continuation->frame_count - 1];
		if (frame->next == frame->count) {
			--continuation->frame_count;
			continue;
		}
		const struct wtwm_action *action = &frame->actions[frame->next++];
		if (action->type == WTWM_ACTION_DELTASTOP) {
			if (!wtwm_delta_stop_continues(server->last_interaction_moved)) {
				memset(continuation, 0, sizeof(*continuation));
				return;
			}
			continue;
		}
		if (action->type == WTWM_ACTION_FUNCTION) {
			(void)push_action_frame(continuation,
				find_function(server, action->argument));
			continue;
		}
		execute_action(server, continuation->toplevel, action,
			continuation->context);
		if (server->grabbed != NULL) return;
	}
	memset(continuation, 0, sizeof(*continuation));
}

static void start_action_function(struct server *server,
		struct toplevel *toplevel, const struct wtwm_function *function,
		uint32_t context) {
	memset(&server->continuation, 0, sizeof(server->continuation));
	server->continuation.toplevel = toplevel;
	server->continuation.context = context;
	server->continuation.active = true;
	if (!push_action_frame(&server->continuation, function)) {
		memset(&server->continuation, 0, sizeof(server->continuation));
		return;
	}
	resume_action_continuation(server);
}

static void execute_action(struct server *server, struct toplevel *toplevel,
		const struct wtwm_action *action, uint32_t context) {
	switch (action->type) {
	case WTWM_ACTION_MOVE: case WTWM_ACTION_FORCEMOVE:
		begin_interactive(toplevel, CURSOR_MOVE, 0,
			action->type == WTWM_ACTION_FORCEMOVE,
			context == WTWM_CONTEXT_TITLE, server->current_input_time_ms); break;
	case WTWM_ACTION_RESIZE:
		begin_interactive(toplevel, CURSOR_RESIZE, 0, false,
			context == WTWM_CONTEXT_TITLE, server->current_input_time_ms); break;
	case WTWM_ACTION_RAISE:
		if (toplevel) focus_toplevel(toplevel);
		break;
	case WTWM_ACTION_LOWER:
		lower_toplevel(toplevel); break;
	case WTWM_ACTION_RAISELOWER:
		if (toplevel && toplevel->link.prev == &server->toplevels)
			lower_toplevel(toplevel);
		else if (toplevel)
			focus_toplevel(toplevel);
		break;
	case WTWM_ACTION_ICONIFY:
		if (toplevel) {
			toplevel->iconified = true;
			wlr_scene_node_set_enabled(&toplevel->tree->node, false);
			suspend_toplevel(toplevel, true);
			focus_next(server);
		}
		break;
	case WTWM_ACTION_DEICONIFY:
		if (toplevel) {
			toplevel->iconified = false;
			wlr_scene_node_set_enabled(&toplevel->tree->node, true);
			suspend_toplevel(toplevel, false);
			focus_toplevel(toplevel);
		}
		break;
	case WTWM_ACTION_FOCUS:
		if (toplevel) focus_toplevel(toplevel);
		break;
	case WTWM_ACTION_UNFOCUS:
		clear_keyboard_focus(server); break;
	case WTWM_ACTION_DELETE:
		if (toplevel) delete_toplevel(toplevel);
		break;
	case WTWM_ACTION_DESTROY:
		if (toplevel) destroy_toplevel_client(toplevel);
		break;
	case WTWM_ACTION_EXEC:
		spawn_shell(action->argument); break;
	case WTWM_ACTION_MENU:
		show_menu(server, action->argument, toplevel); break;
	case WTWM_ACTION_FUNCTION: start_action_function(server, toplevel,
		find_function(server, action->argument), context); break;
	case WTWM_ACTION_DELTASTOP: break;
	case WTWM_ACTION_WARPNEXT: focus_next(server); break;
	case WTWM_ACTION_QUIT: wl_display_terminate(server->display); break;
	default:
		wlr_log(WLR_DEBUG, "%s is parsed but not effective yet", action->name); break;
	}
}

static uint32_t current_modifiers(struct server *server) {
	struct wlr_keyboard *keyboard = wlr_seat_get_keyboard(server->seat);
	if (keyboard == NULL) return 0;
	uint32_t wlr = wlr_keyboard_get_modifiers(keyboard);
	uint32_t mods = 0;
	if (wlr & WLR_MODIFIER_SHIFT) mods |= WTWM_MOD_SHIFT;
	if (wlr & WLR_MODIFIER_CAPS) mods |= WTWM_MOD_LOCK;
	if (wlr & WLR_MODIFIER_CTRL) mods |= WTWM_MOD_CONTROL;
	if (wlr & WLR_MODIFIER_ALT) mods |= WTWM_MOD_META1;
	if (wlr & WLR_MODIFIER_LOGO) mods |= WTWM_MOD_META4;
	return mods;
}

static bool dispatch_binding(struct server *server, enum wtwm_binding_type type,
	unsigned button, const char *key, uint32_t context, struct toplevel *toplevel) {
	uint32_t modifiers = current_modifiers(server);
	for (size_t i = 0; i < server->config.binding_count; ++i) {
		const struct wtwm_binding *binding = &server->config.bindings[i];
		uint32_t compared_modifiers = modifiers;
		if ((binding->modifiers & WTWM_MOD_LOCK) == 0)
			compared_modifiers &= ~WTWM_MOD_LOCK;
		if (binding->type != type || binding->modifiers != compared_modifiers ||
			(binding->contexts & context) == 0) continue;
		if (type == WTWM_BINDING_BUTTON && binding->button != button) continue;
		if (type == WTWM_BINDING_KEY && strcasecmp(binding->key, key) != 0) continue;
		execute_action(server, toplevel, &binding->action, context);
		return true;
	}
	return false;
}

static struct hit_result desktop_at(struct server *server, double lx, double ly) {
	struct hit_result hit = {.context = WTWM_CONTEXT_ROOT};
	double sx = 0, sy = 0;
	struct wlr_scene_node *node = wlr_scene_node_at(&server->scene->tree.node,
		lx, ly, &sx, &sy);
	if (node == NULL) return hit;
	struct wlr_scene_node *leaf = node;
	struct wlr_scene_tree *tree = node->parent;
	hit.toplevel = toplevel_from_scene_tree(tree);
	if (hit.toplevel == NULL) return hit;
	hit.context = WTWM_CONTEXT_FRAME;
	if (leaf->type == WLR_SCENE_NODE_BUFFER) {
		struct wlr_scene_surface *scene_surface = wlr_scene_surface_try_from_buffer(
			wlr_scene_buffer_from_node(leaf));
		if (scene_surface != NULL) {
			hit.surface = scene_surface->surface;
			hit.sx = sx;
			hit.sy = sy;
			hit.context = WTWM_CONTEXT_WINDOW;
		}
	}
	if (hit.toplevel->title && (leaf == &hit.toplevel->title->node ||
		leaf == &hit.toplevel->focus_mark->node ||
		leaf == &hit.toplevel->title_text->node ||
		leaf == &hit.toplevel->left_button->node || leaf == &hit.toplevel->left_dot->node ||
		leaf == &hit.toplevel->right_button->node || leaf == &hit.toplevel->right_inner->node)) {
		hit.context = WTWM_CONTEXT_TITLE;
		hit.left_button = leaf == &hit.toplevel->left_button->node || leaf == &hit.toplevel->left_dot->node;
		hit.right_button = leaf == &hit.toplevel->right_button->node || leaf == &hit.toplevel->right_inner->node;
	}
	if (hit.toplevel->xwayland != NULL &&
			hit.toplevel->xwayland->override_redirect) hit.toplevel = NULL;
	return hit;
}

static void process_cursor_motion(struct server *server, uint32_t time_msec) {
	if (server->cursor_mode == CURSOR_MOVE) {
		struct interaction_session *interaction = &server->interaction;
		int dx = (int)(server->cursor->x - interaction->pointer_start_x);
		int dy = (int)(server->cursor->y - interaction->pointer_start_y);
		if (!interaction->started && !wtwm_interaction_threshold_reached(
				server->config.move_delta, dx, dy)) return;
		interaction->started = true;
		interaction->moved = true;
		int x = (int)(server->cursor->x - interaction->grab_x);
		int y = (int)(server->cursor->y - interaction->grab_y);
		if (interaction->constrained_move) {
			if (interaction->constrained_axis == WTWM_AXIS_NONE) {
				struct wtwm_frame_geometry geometry;
				toplevel_geometry(server->grabbed, &geometry);
				interaction->constrained_axis = wtwm_constrained_move_axis(
					geometry.outer_width, geometry.outer_height,
					(int)server->cursor->x - interaction->original.x,
					(int)server->cursor->y - interaction->original.y);
			}
			if (interaction->constrained_axis == WTWM_AXIS_NONE) return;
			if (interaction->constrained_axis == WTWM_AXIS_HORIZONTAL)
				y = interaction->original.y;
			else
				x = interaction->original.x;
		}
		struct wtwm_frame_geometry geometry;
		toplevel_geometry(server->grabbed, &geometry);
		if (server->config.dont_move_off) {
			struct wlr_box output_box = {0};
			wlr_output_layout_get_box(server->output_layout, NULL, &output_box);
			x -= output_box.x;
			y -= output_box.y;
			wtwm_clamp_move(output_box.width, output_box.height,
				geometry.outer_width, geometry.outer_height,
				interaction->force_move, &x, &y);
			x += output_box.x;
			y += output_box.y;
		}
		interaction->preview.x = x;
		interaction->preview.y = y;
		if (interaction->opaque_move) {
			if (!interaction->raised && !server->config.no_raise_on_move) {
				raise_toplevel(server->grabbed);
				interaction->raised = true;
			}
			set_toplevel_position(server->grabbed, x, y);
		} else {
			show_interaction_outline(server);
		}
		return;
	}
	if (server->cursor_mode == CURSOR_RESIZE) {
		struct interaction_session *interaction = &server->interaction;
		int dx = (int)(server->cursor->x - interaction->pointer_start_x);
		int dy = (int)(server->cursor->y - interaction->pointer_start_y);
		if (wtwm_interaction_threshold_reached(server->config.move_delta, dx, dy))
			interaction->moved = true;
		struct wtwm_frame_geometry geometry;
		toplevel_geometry(server->grabbed, &geometry);
		int border = geometry.border_width;
		int inner_left = interaction->original.x + border;
		int inner_top = interaction->original.y + border;
		int inner_right = inner_left + geometry.frame_width;
		int inner_bottom = inner_top + geometry.frame_height;
		if (interaction->resize_edges == WTWM_RESIZE_EDGE_NONE) {
			if (server->cursor->x <= inner_left)
				interaction->resize_edges |= WTWM_RESIZE_EDGE_LEFT;
			else if (server->cursor->x >= inner_right - 1)
				interaction->resize_edges |= WTWM_RESIZE_EDGE_RIGHT;
			if (server->cursor->y <= inner_top)
				interaction->resize_edges |= WTWM_RESIZE_EDGE_TOP;
			else if (server->cursor->y >= inner_bottom - 1)
				interaction->resize_edges |= WTWM_RESIZE_EDGE_BOTTOM;
			interaction->resize_offset_x = 0;
			interaction->resize_offset_y = 0;
		}
		uint32_t edges = interaction->resize_edges;
		if (edges == WTWM_RESIZE_EDGE_NONE) return;
		int raw_width = interaction->original.width;
		int raw_height = interaction->original.height;
		if ((edges & WTWM_RESIZE_EDGE_LEFT) != 0) {
			int edge = (int)(server->cursor->x - interaction->resize_offset_x);
			raw_width = inner_right - edge;
		} else if ((edges & WTWM_RESIZE_EDGE_RIGHT) != 0) {
			int edge = (int)(server->cursor->x - interaction->resize_offset_x);
			raw_width = edge - inner_left;
		}
		if ((edges & WTWM_RESIZE_EDGE_TOP) != 0) {
			int edge = (int)(server->cursor->y - interaction->resize_offset_y);
			raw_height = inner_bottom - edge - geometry.title_extent;
		} else if ((edges & WTWM_RESIZE_EDGE_BOTTOM) != 0) {
			int edge = (int)(server->cursor->y - interaction->resize_offset_y);
			raw_height = edge - inner_top - geometry.title_extent;
		}
		if (raw_width < 1) raw_width = 1;
		if (raw_height < 1) raw_height = 1;
		constrain_toplevel_size(server->grabbed, &raw_width, &raw_height);
		wtwm_anchor_constrained_resize(&interaction->original, edges,
			raw_width, raw_height, &interaction->preview);
		show_interaction_outline(server);
		return;
	}
	if (server->menu.tree != NULL) {
		update_menu_selection(server);
		wlr_cursor_set_xcursor(server->cursor, server->cursor_manager, "left_ptr");
		wlr_seat_pointer_clear_focus(server->seat);
		return;
	}
	struct hit_result hit = desktop_at(server, server->cursor->x, server->cursor->y);
	if (hit.toplevel != NULL &&
		server->seat->keyboard_state.focused_surface != toplevel_surface(hit.toplevel) &&
		hit.toplevel->auto_raise) focus_toplevel(hit.toplevel);
	if (hit.surface != NULL) {
		wlr_seat_pointer_notify_enter(server->seat, hit.surface, hit.sx, hit.sy);
		wlr_seat_pointer_notify_motion(server->seat, time_msec, hit.sx, hit.sy);
	} else {
		wlr_cursor_set_xcursor(server->cursor, server->cursor_manager,
			hit.context == WTWM_CONTEXT_TITLE ? "fleur" : "left_ptr");
		wlr_seat_pointer_clear_focus(server->seat);
	}
}

static void cursor_motion(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, cursor_motion);
	struct wlr_pointer_motion_event *event = data;
	wlr_cursor_move(server->cursor, &event->pointer->base, event->delta_x, event->delta_y);
	process_cursor_motion(server, event->time_msec);
}

static void cursor_motion_absolute(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, cursor_motion_absolute);
	struct wlr_pointer_motion_absolute_event *event = data;
	wlr_cursor_warp_absolute(server->cursor, &event->pointer->base, event->x, event->y);
	process_cursor_motion(server, event->time_msec);
}

static unsigned twm_button(uint32_t button) {
	if (button == BTN_LEFT) return 1;
	if (button == BTN_MIDDLE) return 2;
	if (button == BTN_RIGHT) return 3;
	return button >= BTN_MOUSE ? button - BTN_MOUSE + 1 : 0;
}

static void cursor_button(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, cursor_button);
	struct wlr_pointer_button_event *event = data;
	server->current_input_time_ms = event->time_msec;
	if (server->grabbed != NULL) {
		finish_interactive(server,
			event->state == WL_POINTER_BUTTON_STATE_PRESSED);
		return;
	}
	if (server->menu.tree != NULL) {
		if (event->state == WL_POINTER_BUTTON_STATE_RELEASED) {
			int selected = menu_item_at(server);
			struct wtwm_action action = {0};
			struct toplevel *target = server->menu.target;
			bool activate = selected >= 0 &&
				server->menu.definition->items[selected].action.type != WTWM_ACTION_TITLE;
			if (activate) action = server->menu.definition->items[selected].action;
			hide_menu(server);
			if (activate) execute_action(server, target, &action,
				target != NULL ? WTWM_CONTEXT_FRAME : WTWM_CONTEXT_ROOT);
		}
		return;
	}
	struct hit_result hit = desktop_at(server, server->cursor->x, server->cursor->y);
	if (event->state == WL_POINTER_BUTTON_STATE_RELEASED) {
		if (hit.surface != NULL)
			wlr_seat_pointer_notify_button(server->seat, event->time_msec,
				event->button, event->state);
		return;
	}
	bool handled = false;
	if ((hit.left_button || hit.right_button) && event->button == BTN_LEFT) {
		const struct wtwm_action *configured = NULL;
		for (size_t i = 0; i < server->config.title_button_count; ++i) {
			if (server->config.title_buttons[i].right_side == hit.right_button) {
				configured = &server->config.title_buttons[i].action;
				break;
			}
		}
		if (configured != NULL) execute_action(server, hit.toplevel, configured,
			WTWM_CONTEXT_TITLE);
		else if (hit.left_button) {
			struct wtwm_action action = {.type = WTWM_ACTION_ICONIFY};
			execute_action(server, hit.toplevel, &action, WTWM_CONTEXT_TITLE);
		} else {
			begin_interactive(hit.toplevel, CURSOR_RESIZE, 0, false, true,
				event->time_msec);
		}
		handled = true;
	}
	if (!handled) handled = dispatch_binding(server, WTWM_BINDING_BUTTON,
		twm_button(event->button), NULL, hit.context, hit.toplevel);
	if (!handled && hit.context == WTWM_CONTEXT_TITLE && event->button == BTN_LEFT) {
		begin_interactive(hit.toplevel, CURSOR_MOVE, 0, false, true,
			event->time_msec);
		handled = true;
	}
	if (!handled && hit.toplevel != NULL) focus_toplevel(hit.toplevel);
	if (!handled && hit.surface != NULL)
		wlr_seat_pointer_notify_button(server->seat, event->time_msec,
			event->button, event->state);
}

static void cursor_axis(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, cursor_axis);
	struct wlr_pointer_axis_event *event = data;
	wlr_seat_pointer_notify_axis(server->seat, event->time_msec, event->orientation,
		event->delta, event->delta_discrete, event->source, event->relative_direction);
}

static void cursor_frame(struct wl_listener *listener, void *data) {
	(void)data;
	struct server *server = wl_container_of(listener, server, cursor_frame);
	wlr_seat_pointer_notify_frame(server->seat);
}

static void keyboard_modifiers(struct wl_listener *listener, void *data) {
	(void)data;
	struct keyboard *keyboard = wl_container_of(listener, keyboard, modifiers);
	wlr_seat_set_keyboard(keyboard->server->seat, keyboard->wlr);
	wlr_seat_keyboard_notify_modifiers(keyboard->server->seat, &keyboard->wlr->modifiers);
}

static void keyboard_key(struct wl_listener *listener, void *data) {
	struct keyboard *keyboard = wl_container_of(listener, keyboard, key);
	struct server *server = keyboard->server;
	struct wlr_keyboard_key_event *event = data;
	server->current_input_time_ms = event->time_msec;
	uint32_t keycode = event->keycode + 8;
	const xkb_keysym_t *symbols = NULL;
	int count = xkb_state_key_get_syms(keyboard->wlr->xkb_state, keycode, &symbols);
	bool handled = false;
	if (event->state == WL_KEYBOARD_KEY_STATE_PRESSED) {
		struct wlr_surface *focused = server->seat->keyboard_state.focused_surface;
		struct toplevel *toplevel = toplevel_for_surface(focused);
		uint32_t context = toplevel ? WTWM_CONTEXT_WINDOW : WTWM_CONTEXT_ROOT;
		for (int i = 0; i < count && !handled; ++i) {
			char name[128];
			xkb_keysym_get_name(symbols[i], name, sizeof(name));
			handled = dispatch_binding(server, WTWM_BINDING_KEY, 0, name, context, toplevel);
			if (!handled && (current_modifiers(server) & WTWM_MOD_META1) &&
				symbols[i] == XKB_KEY_Escape) {
				wlr_log(WLR_INFO, "%s", "emergency Alt+Escape exit");
				wl_display_terminate(server->display);
				handled = true;
			}
		}
	}
	if (!handled) {
		wlr_seat_set_keyboard(server->seat, keyboard->wlr);
		wlr_seat_keyboard_notify_key(server->seat, event->time_msec,
			event->keycode, event->state);
	}
}

static void keyboard_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct keyboard *keyboard = wl_container_of(listener, keyboard, destroy);
	wl_list_remove(&keyboard->modifiers.link);
	wl_list_remove(&keyboard->key.link);
	wl_list_remove(&keyboard->destroy.link);
	wl_list_remove(&keyboard->link);
	free(keyboard);
}

static void new_keyboard(struct server *server, struct wlr_input_device *device) {
	struct keyboard *keyboard = calloc(1, sizeof(*keyboard));
	if (keyboard == NULL) return;
	keyboard->server = server;
	keyboard->wlr = wlr_keyboard_from_input_device(device);
	struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	struct xkb_keymap *keymap = xkb_keymap_new_from_names(context, NULL,
		XKB_KEYMAP_COMPILE_NO_FLAGS);
	wlr_keyboard_set_keymap(keyboard->wlr, keymap);
	xkb_keymap_unref(keymap);
	xkb_context_unref(context);
	wlr_keyboard_set_repeat_info(keyboard->wlr, 25, 600);
	keyboard->modifiers.notify = keyboard_modifiers;
	wl_signal_add(&keyboard->wlr->events.modifiers, &keyboard->modifiers);
	keyboard->key.notify = keyboard_key;
	wl_signal_add(&keyboard->wlr->events.key, &keyboard->key);
	keyboard->destroy.notify = keyboard_destroy;
	wl_signal_add(&device->events.destroy, &keyboard->destroy);
	wl_list_insert(&server->keyboards, &keyboard->link);
	wlr_seat_set_keyboard(server->seat, keyboard->wlr);
}

static void new_input(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, new_input);
	struct wlr_input_device *device = data;
	if (device->type == WLR_INPUT_DEVICE_KEYBOARD) new_keyboard(server, device);
	else if (device->type == WLR_INPUT_DEVICE_POINTER) wlr_cursor_attach_input_device(server->cursor, device);
	uint32_t capabilities = WL_SEAT_CAPABILITY_POINTER;
	if (!wl_list_empty(&server->keyboards)) capabilities |= WL_SEAT_CAPABILITY_KEYBOARD;
	wlr_seat_set_capabilities(server->seat, capabilities);
}

static void request_cursor(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, request_cursor);
	struct wlr_seat_pointer_request_set_cursor_event *event = data;
	if (server->seat->pointer_state.focused_client == event->seat_client)
		wlr_cursor_set_surface(server->cursor, event->surface, event->hotspot_x, event->hotspot_y);
}

static void request_selection(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, request_selection);
	struct wlr_seat_request_set_selection_event *event = data;
	wlr_seat_set_selection(server->seat, event->source, event->serial);
}

static void request_primary_selection(struct wl_listener *listener, void *data) {
	struct server *server =
		wl_container_of(listener, server, request_primary_selection);
	struct wlr_seat_request_set_primary_selection_event *event = data;
	wlr_seat_set_primary_selection(server->seat, event->source, event->serial);
}

static bool render_output(struct output *output) {
	struct wlr_scene_output *scene_output = wlr_scene_get_scene_output(
		output->server->scene, output->wlr);
	if (scene_output == NULL || !wlr_scene_output_commit(scene_output, NULL))
		return false;
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	wlr_scene_output_send_frame_done(scene_output, &now);
	++output->server->frame_sequence;
	return true;
}

static void output_frame(struct wl_listener *listener, void *data) {
	(void)data;
	struct output *output = wl_container_of(listener, output, frame);
	render_output(output);
}

static void output_request_state(struct wl_listener *listener, void *data) {
	struct output *output = wl_container_of(listener, output, request_state);
	const struct wlr_output_event_request_state *event = data;
	wlr_output_commit_state(output->wlr, event->state);
}

static void output_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct output *output = wl_container_of(listener, output, destroy);
	wl_list_remove(&output->frame.link);
	wl_list_remove(&output->request_state.link);
	wl_list_remove(&output->destroy.link);
	wl_list_remove(&output->link);
	free(output);
}

static void new_output(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, new_output);
	struct wlr_output *wlr_output = data;
	wlr_output_init_render(wlr_output, server->allocator, server->renderer);
	struct wlr_output_state state;
	wlr_output_state_init(&state);
	wlr_output_state_set_enabled(&state, true);
	struct wlr_output_mode *mode = wlr_output_preferred_mode(wlr_output);
	if (mode != NULL) wlr_output_state_set_mode(&state, mode);
	wlr_output_commit_state(wlr_output, &state);
	wlr_output_state_finish(&state);
	struct output *output = calloc(1, sizeof(*output));
	if (output == NULL) return;
	output->server = server;
	output->wlr = wlr_output;
	output->frame.notify = output_frame;
	wl_signal_add(&wlr_output->events.frame, &output->frame);
	output->request_state.notify = output_request_state;
	wl_signal_add(&wlr_output->events.request_state, &output->request_state);
	output->destroy.notify = output_destroy;
	wl_signal_add(&wlr_output->events.destroy, &output->destroy);
	wl_list_insert(&server->outputs, &output->link);
	struct wlr_output_layout_output *layout_output =
		wlr_output_layout_add_auto(server->output_layout, wlr_output);
	struct wlr_scene_output *scene_output = wlr_scene_output_create(server->scene, wlr_output);
	wlr_scene_output_layout_add_output(server->scene_layout, layout_output, scene_output);
}

static void update_toplevel_metadata(struct toplevel *toplevel,
	bool title_changed);

static void toplevel_map(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, map);
	if (toplevel->mapped) return;
	bool initial_rules = initialize_toplevel_rules(toplevel);
	toplevel->mapped = true;
	toplevel->iconified = false;
	wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
	if (!toplevel->placed) {
		unsigned n = toplevel->server->placement_index++;
		wlr_scene_node_set_position(&toplevel->tree->node,
			32 + (int)(n % 12) * 24, 32 + (int)(n % 10) * 24);
		toplevel->placed = true;
	}
	wlr_scene_node_set_enabled(&toplevel->tree->node, true);
	test_trace_toplevel_event(toplevel, "map", "client");
	if (should_start_iconified(toplevel, initial_rules)) {
		toplevel->iconified = true;
		wlr_scene_node_set_enabled(&toplevel->tree->node, false);
		suspend_toplevel(toplevel, true);
	} else {
		suspend_toplevel(toplevel, false);
		focus_toplevel(toplevel);
	}
}

static void dismiss_toplevel_popups(struct toplevel *toplevel) {
	for (;;) {
		struct popup *popup, *deepest = NULL;
		wl_list_for_each(popup, &toplevel->server->popups, link) {
			if (popup->root == toplevel &&
				(deepest == NULL || popup->depth > deepest->depth))
				deepest = popup;
		}
		if (deepest == NULL) return;
		wlr_xdg_popup_destroy(deepest->xdg);
	}
}

static void unmanage_toplevel(struct toplevel *toplevel) {
	struct server *server = toplevel->server;
	bool had_keyboard_focus = surface_belongs_to_toplevel(
		server->seat->keyboard_state.focused_surface, toplevel);
	bool had_pointer_focus = surface_belongs_to_toplevel(
		server->seat->pointer_state.focused_surface, toplevel);
	if (toplevel == server->grabbed) reset_cursor(server);
	if (server->continuation.toplevel == toplevel)
		memset(&server->continuation, 0, sizeof(server->continuation));
	if (server->menu.target == toplevel) hide_menu(server);
	if (had_pointer_focus) wlr_seat_pointer_clear_focus(server->seat);
	dismiss_toplevel_popups(toplevel);
	if (!toplevel->mapped) return;
	toplevel->mapped = false;
	wl_list_remove(&toplevel->link);
	wl_list_init(&toplevel->link);
	wlr_scene_node_set_enabled(&toplevel->tree->node, false);
	test_trace_toplevel_event(toplevel, "unmap", "client");
	if (had_keyboard_focus) {
		clear_keyboard_focus(server);
		focus_next(server);
	}
}

static void toplevel_unmap(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, unmap);
	unmanage_toplevel(toplevel);
}

static void toplevel_commit(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, commit);
	int previous_width = toplevel->width;
	int previous_height = toplevel->height;
	if (toplevel->xdg->base->initial_commit) {
		wlr_xdg_toplevel_set_size(toplevel->xdg, 0, 0);
		update_toplevel_metadata(toplevel, false);
	}
	struct wlr_box geometry;
	wlr_xdg_surface_get_geometry(toplevel->xdg->base, &geometry);
	if (geometry.width > 0) toplevel->width = geometry.width;
	if (geometry.height > 0) toplevel->height = geometry.height;
	update_decoration(toplevel);
	if (toplevel->width != previous_width || toplevel->height != previous_height)
		test_trace_toplevel_event(toplevel, "configure", "client");
}

static void toplevel_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, destroy);
	unmanage_toplevel(toplevel);
	test_trace_toplevel_event(toplevel, "destroy", "client");
	wl_list_remove(&toplevel->map.link);
	wl_list_remove(&toplevel->unmap.link);
	wl_list_remove(&toplevel->commit.link);
	wl_list_remove(&toplevel->destroy.link);
	wl_list_remove(&toplevel->request_move.link);
	wl_list_remove(&toplevel->request_resize.link);
	wl_list_remove(&toplevel->request_maximize.link);
	wl_list_remove(&toplevel->request_fullscreen.link);
	wl_list_remove(&toplevel->request_minimize.link);
	wl_list_remove(&toplevel->set_title.link);
	wl_list_remove(&toplevel->set_app_id.link);
	if (toplevel->xdg->base->data == toplevel->content)
		toplevel->xdg->base->data = NULL;
	wlr_scene_node_destroy(&toplevel->tree->node);
	free(toplevel);
}

static void request_move(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_move);
	begin_interactive(toplevel, CURSOR_MOVE, 0, false, false,
		toplevel->server->current_input_time_ms);
}

static void request_resize(struct wl_listener *listener, void *data) {
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_resize);
	struct wlr_xdg_toplevel_resize_event *event = data;
	begin_interactive(toplevel, CURSOR_RESIZE, event->edges, false, false,
		toplevel->server->current_input_time_ms);
}

static void request_maximize(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_maximize);
	if (toplevel->xdg->base->initialized) wlr_xdg_surface_schedule_configure(toplevel->xdg->base);
}

static void request_fullscreen(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_fullscreen);
	if (toplevel->xdg->base->initialized) wlr_xdg_surface_schedule_configure(toplevel->xdg->base);
}

static void request_minimize(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_minimize);
	struct wtwm_action action = {.type = WTWM_ACTION_ICONIFY};
	execute_action(toplevel->server, toplevel, &action, WTWM_CONTEXT_WINDOW);
}

static void update_toplevel_metadata(struct toplevel *toplevel, bool title_changed) {
	if (title_changed) update_title_text(toplevel);
	bool was_decorated = toplevel->decorated;
	set_decorated(toplevel, should_decorate(toplevel));
	if (toplevel->xwayland != NULL && toplevel->associated && toplevel->mapped &&
			was_decorated != toplevel->decorated)
		configure_xwayland_client(toplevel, toplevel->xwayland->x,
			toplevel->xwayland->y, toplevel->xwayland->width,
			toplevel->xwayland->height);
	if (title_changed) test_trace_toplevel_event(toplevel, "title", "title");
}

static void set_title(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_title);
	update_toplevel_metadata(toplevel, true);
}

static void set_app_id(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_app_id);
	update_toplevel_metadata(toplevel, false);
}

static void new_toplevel(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, new_toplevel);
	struct wlr_xdg_toplevel *xdg = data;
	struct toplevel *toplevel = calloc(1, sizeof(*toplevel));
	if (toplevel == NULL) return;
	toplevel->server = server;
	toplevel->xdg = xdg;
	test_trace_assign_id(toplevel);
	wl_list_init(&toplevel->link);
	toplevel->width = 640;
	toplevel->height = 480;
	toplevel->border_width = configured_border_width(server);
	toplevel->title_bar_height = configured_title_bar_height(server);
	toplevel->tree = wlr_scene_tree_create(server->view_tree);
	if (toplevel->tree == NULL) {
		free(toplevel);
		wlr_xdg_toplevel_send_close(xdg);
		return;
	}
	wlr_scene_node_set_enabled(&toplevel->tree->node, false);
	toplevel->tree->node.data = toplevel;
	float border[4], title[4], foreground[4];
	color_value(server->config.border_color, border);
	color_value(server->config.title_background, title);
	color_value(server->config.title_foreground, foreground);
	toplevel->frame = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->title = wlr_scene_rect_create(toplevel->tree, 1, 1, title);
	toplevel->focus_mark = wlr_scene_rect_create(toplevel->tree, 1, 2, foreground);
	toplevel->left_button = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->left_dot = wlr_scene_rect_create(toplevel->tree, 3, 3, foreground);
	toplevel->right_button = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->right_inner = wlr_scene_rect_create(toplevel->tree, 1, 1, title);
	toplevel->title_text = wlr_scene_buffer_create(toplevel->tree, NULL);
	toplevel->content = wlr_scene_xdg_surface_create(toplevel->tree, xdg->base);
	xdg->base->data = toplevel->content;
	update_toplevel_metadata(toplevel, true);
	toplevel->map.notify = toplevel_map;
	wl_signal_add(&xdg->base->surface->events.map, &toplevel->map);
	toplevel->unmap.notify = toplevel_unmap;
	wl_signal_add(&xdg->base->surface->events.unmap, &toplevel->unmap);
	toplevel->commit.notify = toplevel_commit;
	wl_signal_add(&xdg->base->surface->events.commit, &toplevel->commit);
	toplevel->destroy.notify = toplevel_destroy;
	wl_signal_add(&xdg->events.destroy, &toplevel->destroy);
	toplevel->request_move.notify = request_move;
	wl_signal_add(&xdg->events.request_move, &toplevel->request_move);
	toplevel->request_resize.notify = request_resize;
	wl_signal_add(&xdg->events.request_resize, &toplevel->request_resize);
	toplevel->request_maximize.notify = request_maximize;
	wl_signal_add(&xdg->events.request_maximize, &toplevel->request_maximize);
	toplevel->request_fullscreen.notify = request_fullscreen;
	wl_signal_add(&xdg->events.request_fullscreen, &toplevel->request_fullscreen);
	toplevel->request_minimize.notify = request_minimize;
	wl_signal_add(&xdg->events.request_minimize, &toplevel->request_minimize);
	toplevel->set_title.notify = set_title;
	wl_signal_add(&xdg->events.set_title, &toplevel->set_title);
	toplevel->set_app_id.notify = set_app_id;
	wl_signal_add(&xdg->events.set_app_id, &toplevel->set_app_id);
}

static bool create_xwayland_scene(struct toplevel *toplevel) {
	struct wlr_scene_tree *parent = toplevel->xwayland->override_redirect ?
		toplevel->server->overlay_tree : toplevel->server->view_tree;
	toplevel->tree = wlr_scene_tree_create(parent);
	if (toplevel->tree == NULL) return false;
	wlr_scene_node_set_enabled(&toplevel->tree->node, false);
	toplevel->tree->node.data = toplevel;
	float border[4], title[4], foreground[4];
	color_value(toplevel->server->config.border_color, border);
	color_value(toplevel->server->config.title_background, title);
	color_value(toplevel->server->config.title_foreground, foreground);
	toplevel->frame = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->title = wlr_scene_rect_create(toplevel->tree, 1, 1, title);
	toplevel->focus_mark = wlr_scene_rect_create(toplevel->tree, 1, 2, foreground);
	toplevel->left_button = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->left_dot = wlr_scene_rect_create(toplevel->tree, 3, 3, foreground);
	toplevel->right_button = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->right_inner = wlr_scene_rect_create(toplevel->tree, 1, 1, title);
	toplevel->title_text = wlr_scene_buffer_create(toplevel->tree, NULL);
	toplevel->content = wlr_scene_subsurface_tree_create(
		toplevel->tree, toplevel->xwayland->surface);
	if (toplevel->content == NULL) {
		wlr_scene_node_destroy(&toplevel->tree->node);
		toplevel->tree = NULL;
		return false;
	}
	update_toplevel_metadata(toplevel, true);
	return true;
}

static void destroy_xwayland_scene(struct toplevel *toplevel) {
	if (toplevel->tree != NULL) wlr_scene_node_destroy(&toplevel->tree->node);
	toplevel->tree = NULL;
	toplevel->content = NULL;
	toplevel->frame = NULL;
	toplevel->title = NULL;
	toplevel->focus_mark = NULL;
	toplevel->left_button = NULL;
	toplevel->left_dot = NULL;
	toplevel->right_button = NULL;
	toplevel->right_inner = NULL;
	toplevel->title_text = NULL;
}

static void position_xwayland_transient(struct toplevel *toplevel) {
	if (toplevel->xwayland->override_redirect || toplevel->tree == NULL) return;
	struct wlr_xwayland_surface *parent_surface = toplevel->xwayland->parent;
	struct toplevel *parent = parent_surface != NULL ? parent_surface->data : NULL;
	if (parent == NULL || parent == toplevel || !parent->mapped || parent->tree == NULL ||
			parent_surface->override_redirect) return;
	wlr_scene_node_place_above(&toplevel->tree->node, &parent->tree->node);
	wlr_xwayland_surface_restack(toplevel->xwayland,
		parent_surface, XCB_STACK_MODE_ABOVE);
	test_trace_toplevel_event(toplevel, "restack", "frame");
}

static void map_xwayland_toplevel(struct toplevel *toplevel) {
	if (toplevel->mapped || toplevel->tree == NULL) return;
	bool initial_rules = initialize_toplevel_rules(toplevel);
	toplevel->mapped = true;
	toplevel->iconified = false;
	toplevel->width = toplevel->xwayland->width;
	toplevel->height = toplevel->xwayland->height;
	if (toplevel->xwayland->override_redirect) {
		wlr_scene_node_set_position(&toplevel->tree->node,
			toplevel->xwayland->x, toplevel->xwayland->y);
		wlr_scene_node_raise_to_top(&toplevel->tree->node);
		test_trace_toplevel_event(toplevel, "raise", "frame");
	} else {
		wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
		int frame_x = toplevel->frame_x;
		int frame_y = toplevel->frame_y;
		if (!toplevel->frame_positioned) {
			struct wtwm_frame_geometry geometry;
			toplevel_geometry(toplevel, &geometry);
			int gravity_x = -1, gravity_y = -1;
			xwayland_gravity_offsets(toplevel, &gravity_x, &gravity_y);
			struct wtwm_window_position position;
			wtwm_initial_window_position(toplevel->xwayland->x,
				toplevel->xwayland->y, toplevel->original_client_border,
				&geometry, toplevel->server->config.client_border_width,
				gravity_x, gravity_y, &position);
			frame_x = position.frame_x;
			frame_y = position.frame_y;
		}
		configure_xwayland_frame(toplevel, frame_x, frame_y,
			toplevel->xwayland->width, toplevel->xwayland->height);
		toplevel->placed = true;
	}
	update_decoration(toplevel);
	wlr_scene_node_set_enabled(&toplevel->tree->node, true);
	test_trace_toplevel_event(toplevel, "map", "client");
	if (toplevel->xwayland->override_redirect) {
		if (wlr_xwayland_or_surface_wants_focus(toplevel->xwayland)) {
			struct wlr_keyboard *keyboard = wlr_seat_get_keyboard(toplevel->server->seat);
			if (keyboard != NULL) {
				wlr_seat_keyboard_notify_enter(toplevel->server->seat,
					toplevel->xwayland->surface, keyboard->keycodes,
					keyboard->num_keycodes, &keyboard->modifiers);
			}
		}
	} else {
		position_xwayland_transient(toplevel);
		if (should_start_iconified(toplevel, initial_rules)) {
			toplevel->iconified = true;
			wlr_scene_node_set_enabled(&toplevel->tree->node, false);
			suspend_toplevel(toplevel, true);
		} else {
			suspend_toplevel(toplevel, false);
			focus_toplevel(toplevel);
		}
	}
}

static void xwayland_surface_map(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, map);
	map_xwayland_toplevel(toplevel);
}

static void xwayland_surface_unmap(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, unmap);
	unmanage_toplevel(toplevel);
}

static void xwayland_surface_commit(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, commit);
	int previous_width = toplevel->width;
	int previous_height = toplevel->height;
	toplevel->width = toplevel->xwayland->width;
	toplevel->height = toplevel->xwayland->height;
	update_decoration(toplevel);
	if (toplevel->width != previous_width || toplevel->height != previous_height)
		test_trace_toplevel_event(toplevel, "configure", "client");
}

static void read_xwayland_icon_name(struct toplevel *toplevel) {
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(toplevel->server->xwayland);
	if (connection == NULL || toplevel->server->atom_wm_icon_name == XCB_ATOM_NONE)
		return;
	xcb_get_property_cookie_t cookie = xcb_get_property(connection, false,
		toplevel->xwayland->window_id, toplevel->server->atom_wm_icon_name,
		XCB_ATOM_ANY, 0, 2048);
	xcb_get_property_reply_t *reply = xcb_get_property_reply(connection, cookie, NULL);
	char *previous = toplevel->icon_name;
	toplevel->icon_name = NULL;
	if (reply != NULL && reply->format == 8) {
		int length = xcb_get_property_value_length(reply);
		if (length > 0)
			toplevel->icon_name = strndup(xcb_get_property_value(reply), (size_t)length);
	}
	free(reply);
	bool changed = strcmp(previous != NULL ? previous : "",
		toplevel->icon_name != NULL ? toplevel->icon_name : "") != 0;
	free(previous);
	if (changed) test_trace_toplevel_event(toplevel, "icon_name", "icon");
}

static void read_xwayland_net_wm_icon(struct toplevel *toplevel) {
	toplevel->net_wm_icon_width = 0;
	toplevel->net_wm_icon_height = 0;
	toplevel->net_wm_icon_count = 0;
	toplevel->net_wm_icon_checksum = 0;
	toplevel->net_wm_icon_truncated = false;
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(toplevel->server->xwayland);
	if (connection == NULL || toplevel->server->atom_net_wm_icon == XCB_ATOM_NONE)
		return;
	/* Bound untrusted icon data while accepting one complete 256x256 icon. */
	const uint32_t max_words = 256 * 256 + 2;
	xcb_get_property_cookie_t cookie = xcb_get_property(connection, false,
		toplevel->xwayland->window_id, toplevel->server->atom_net_wm_icon,
		XCB_ATOM_CARDINAL, 0, max_words);
	xcb_get_property_reply_t *reply = xcb_get_property_reply(connection, cookie, NULL);
	if (reply == NULL || reply->format != 32) {
		free(reply);
		return;
	}
	const uint32_t *values = xcb_get_property_value(reply);
	toplevel->net_wm_icon_truncated = reply->bytes_after != 0;
	size_t length = (size_t)xcb_get_property_value_length(reply) / sizeof(*values);
	size_t index = 0;
	uint32_t checksum = UINT32_C(2166136261);
	while (index + 2 <= length) {
		uint32_t width = values[index++];
		uint32_t height = values[index++];
		if (width == 0 || height == 0 || width > 4096 || height > 4096 ||
				(uint64_t)width * height > length - index) break;
		size_t pixels = (size_t)width * height;
		if (toplevel->net_wm_icon_count == 0) {
			toplevel->net_wm_icon_width = width;
			toplevel->net_wm_icon_height = height;
		}
		++toplevel->net_wm_icon_count;
		for (size_t i = 0; i < pixels; ++i) {
			checksum ^= values[index + i];
			checksum *= UINT32_C(16777619);
		}
		index += pixels;
	}
	if (toplevel->net_wm_icon_count != 0)
		toplevel->net_wm_icon_checksum = checksum;
	free(reply);
}

static void xwayland_deferred_sync(void *data) {
	struct toplevel *toplevel = data;
	bool parent_cleared = false;
	toplevel->xwayland_sync_idle = NULL;
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(toplevel->server->xwayland);
	if (connection != NULL && toplevel->server->atom_wm_protocols != XCB_ATOM_NONE) {
		xcb_get_property_cookie_t cookie = xcb_get_property(connection, false,
			toplevel->xwayland->window_id, toplevel->server->atom_wm_protocols,
			XCB_ATOM_ATOM, 0, 1);
		xcb_get_property_reply_t *reply =
			xcb_get_property_reply(connection, cookie, NULL);
		if (reply == NULL || reply->type != XCB_ATOM_ATOM || reply->value_len == 0) {
			free(toplevel->xwayland->protocols);
			toplevel->xwayland->protocols = NULL;
			toplevel->xwayland->protocols_len = 0;
		}
		free(reply);
	}
	if (connection != NULL && toplevel->server->atom_wm_normal_hints != XCB_ATOM_NONE) {
		xcb_get_property_cookie_t cookie = xcb_get_property(connection, false,
			toplevel->xwayland->window_id, toplevel->server->atom_wm_normal_hints,
			XCB_ATOM_ANY, 0, 1);
		xcb_get_property_reply_t *reply =
			xcb_get_property_reply(connection, cookie, NULL);
		if (reply == NULL || reply->value_len == 0) {
			free(toplevel->xwayland->size_hints);
			toplevel->xwayland->size_hints = NULL;
		}
		free(reply);
	}
	if (connection != NULL && toplevel->server->atom_wm_transient_for != XCB_ATOM_NONE) {
		xcb_get_property_cookie_t cookie = xcb_get_property(connection, false,
			toplevel->xwayland->window_id,
			toplevel->server->atom_wm_transient_for, XCB_ATOM_WINDOW, 0, 1);
		xcb_get_property_reply_t *reply =
			xcb_get_property_reply(connection, cookie, NULL);
		if ((reply == NULL || reply->type != XCB_ATOM_WINDOW || reply->value_len == 0) &&
				toplevel->xwayland->parent != NULL) {
			wl_list_remove(&toplevel->xwayland->parent_link);
			wl_list_init(&toplevel->xwayland->parent_link);
			toplevel->xwayland->parent = NULL;
			parent_cleared = true;
		}
		free(reply);
	}
	if (parent_cleared) update_toplevel_metadata(toplevel, false);
}

static void schedule_xwayland_sync(struct toplevel *toplevel) {
	if (toplevel->xwayland_sync_idle != NULL) return;
	toplevel->xwayland_sync_idle = wl_event_loop_add_idle(
		wl_display_get_event_loop(toplevel->server->display),
		xwayland_deferred_sync, toplevel);
}

static void initialize_xwayland_border(struct toplevel *toplevel) {
	if (toplevel->border_initialized) return;
	toplevel->border_initialized = true;
	if (toplevel->xwayland->override_redirect) {
		toplevel->border_width = 0;
		return;
	}
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(toplevel->server->xwayland);
	if (connection != NULL) {
		xcb_get_geometry_cookie_t cookie = xcb_get_geometry(connection,
			toplevel->xwayland->window_id);
		xcb_get_geometry_reply_t *reply = xcb_get_geometry_reply(connection, cookie, NULL);
		if (reply != NULL) {
			toplevel->original_client_border = reply->border_width;
			free(reply);
		}
		if (toplevel->original_client_border > 0) {
			uint32_t border = 0;
			xcb_configure_window(connection, toplevel->xwayland->window_id,
				XCB_CONFIG_WINDOW_BORDER_WIDTH, &border);
			xcb_flush(connection);
		}
	}
	toplevel->border_width = toplevel->server->config.client_border_width ?
		toplevel->original_client_border :
		configured_border_width(toplevel->server);
}

static void xwayland_associate(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, associate);
	if (toplevel->associated || toplevel->xwayland->surface == NULL) return;
	initialize_xwayland_border(toplevel);
	if (!create_xwayland_scene(toplevel)) return;
	toplevel->associated = true;
	read_xwayland_icon_name(toplevel);
	read_xwayland_net_wm_icon(toplevel);
	toplevel->map.notify = xwayland_surface_map;
	wl_signal_add(&toplevel->xwayland->surface->events.map, &toplevel->map);
	toplevel->unmap.notify = xwayland_surface_unmap;
	wl_signal_add(&toplevel->xwayland->surface->events.unmap, &toplevel->unmap);
	toplevel->commit.notify = xwayland_surface_commit;
	wl_signal_add(&toplevel->xwayland->surface->events.commit, &toplevel->commit);
	if (toplevel->xwayland->surface->mapped) {
		map_xwayland_toplevel(toplevel);
	} else if (wlr_surface_has_buffer(toplevel->xwayland->surface)) {
		/* Xwayland may commit its buffer and queue a frame callback before
		 * wlroots pairs WL_SURFACE_ID with this X window. The Xwayland role
		 * then misses that commit and remains unmapped while waiting for the
		 * callback. Complete it only after our association listeners exist so
		 * Xwayland produces a post-association commit for the role to map. */
		struct timespec now;
		if (clock_gettime(CLOCK_MONOTONIC, &now) == 0)
			wlr_surface_send_frame_done(toplevel->xwayland->surface, &now);
	}
}

static void xwayland_dissociate(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, dissociate);
	if (!toplevel->associated) return;
	unmanage_toplevel(toplevel);
	wl_list_remove(&toplevel->map.link);
	wl_list_remove(&toplevel->unmap.link);
	wl_list_remove(&toplevel->commit.link);
	destroy_xwayland_scene(toplevel);
	toplevel->associated = false;
	/* twm discards its managed-window record on client unmap. The next X11
	 * MapRequest is therefore a fresh rule snapshot, including StartIconified. */
	toplevel->rules_initialized = false;
	toplevel->auto_raise = false;
}

static void xwayland_request_configure(struct wl_listener *listener, void *data) {
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_configure);
	struct wlr_xwayland_surface_configure_event *event = data;
	if (!toplevel->associated || !toplevel->mapped || toplevel->tree == NULL) {
		toplevel->pending_configure_mask = 0;
		configure_xwayland_client(toplevel, event->x, event->y,
			event->width, event->height);
		return;
	}
	if (toplevel->xwayland->override_redirect) {
		configure_xwayland_frame(toplevel, event->x, event->y,
			event->width, event->height);
		return;
	}
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	int gravity_x = -1, gravity_y = -1;
	xwayland_gravity_offsets(toplevel, &gravity_x, &gravity_y);
	(void)gravity_x;
	uint16_t mask = toplevel->pending_configure_mask;
	toplevel->pending_configure_mask = 0;
	struct wtwm_window_position position;
	wtwm_configure_request_position(toplevel->tree->node.x,
		toplevel->tree->node.y, event->x, event->y,
		(mask & XCB_CONFIG_WINDOW_X) != 0,
		(mask & XCB_CONFIG_WINDOW_Y) != 0,
		&geometry, gravity_y, &position);
	int width = (mask & XCB_CONFIG_WINDOW_WIDTH) != 0 ?
		event->width : toplevel->width;
	int height = (mask & XCB_CONFIG_WINDOW_HEIGHT) != 0 ?
		event->height : toplevel->height;
	configure_xwayland_frame(toplevel, position.frame_x, position.frame_y,
		width, height);
}

static void xwayland_set_title(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_title);
	update_toplevel_metadata(toplevel, true);
}

static void xwayland_set_class(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_class);
	update_toplevel_metadata(toplevel, false);
}

static void xwayland_set_parent(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_parent);
	update_toplevel_metadata(toplevel, false);
	position_xwayland_transient(toplevel);
}

static void xwayland_set_hints(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_hints);
	if (toplevel->mapped && toplevel->xwayland->hints != NULL &&
			(toplevel->xwayland->hints->flags & XCB_ICCCM_WM_HINT_X_URGENCY) != 0)
		wlr_log(WLR_DEBUG, "X11 window 0x%08" PRIx32 " requests attention",
			toplevel->xwayland->window_id);
}

static void xwayland_set_geometry(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_geometry);
	int previous_x = toplevel->tree != NULL ? toplevel->tree->node.x : 0;
	int previous_y = toplevel->tree != NULL ? toplevel->tree->node.y : 0;
	int previous_width = toplevel->width;
	int previous_height = toplevel->height;
	toplevel->width = toplevel->xwayland->width;
	toplevel->height = toplevel->xwayland->height;
	if (toplevel->tree != NULL) {
		int x = toplevel->xwayland->x;
		int y = toplevel->xwayland->y;
		if (!toplevel->xwayland->override_redirect) {
			x -= toplevel_content_x(toplevel);
			y -= toplevel_content_y(toplevel);
		}
		wlr_scene_node_set_position(&toplevel->tree->node, x, y);
		if (toplevel->mapped && !toplevel->xwayland->override_redirect) {
			toplevel->frame_x = x;
			toplevel->frame_y = y;
			toplevel->frame_positioned = true;
		}
		update_decoration(toplevel);
	}
	if (toplevel->tree != NULL && (toplevel->tree->node.x != previous_x ||
			toplevel->tree->node.y != previous_y ||
			toplevel->width != previous_width ||
			toplevel->height != previous_height))
		test_trace_toplevel_event(toplevel, "configure", "client");
}

static void xwayland_set_override_redirect(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel =
		wl_container_of(listener, toplevel, set_override_redirect);
	if (!toplevel->associated) return;
	bool remap = toplevel->mapped;
	if (remap) unmanage_toplevel(toplevel);
	destroy_xwayland_scene(toplevel);
	toplevel->border_initialized = false;
	initialize_xwayland_border(toplevel);
	if (!create_xwayland_scene(toplevel)) return;
	if (remap) map_xwayland_toplevel(toplevel);
}

static void xwayland_surface_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, destroy);
	if (toplevel->associated) {
		unmanage_toplevel(toplevel);
		test_trace_toplevel_event(toplevel, "destroy", "client");
		wl_list_remove(&toplevel->map.link);
		wl_list_remove(&toplevel->unmap.link);
		wl_list_remove(&toplevel->commit.link);
		destroy_xwayland_scene(toplevel);
	} else test_trace_toplevel_event(toplevel, "destroy", "client");
	if (toplevel->xwayland_sync_idle != NULL)
		wl_event_source_remove(toplevel->xwayland_sync_idle);
	wl_list_remove(&toplevel->associate.link);
	wl_list_remove(&toplevel->dissociate.link);
	wl_list_remove(&toplevel->destroy.link);
	wl_list_remove(&toplevel->request_configure.link);
	wl_list_remove(&toplevel->set_title.link);
	wl_list_remove(&toplevel->set_class.link);
	wl_list_remove(&toplevel->set_parent.link);
	wl_list_remove(&toplevel->set_hints.link);
	wl_list_remove(&toplevel->set_override_redirect.link);
	wl_list_remove(&toplevel->set_geometry.link);
	wl_list_remove(&toplevel->xwayland_link);
	free(toplevel->icon_name);
	toplevel->xwayland->data = NULL;
	free(toplevel);
}

static void new_xwayland_surface(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, xwayland_new_surface);
	struct wlr_xwayland_surface *xwayland = data;
	struct toplevel *toplevel = calloc(1, sizeof(*toplevel));
	if (toplevel == NULL) return;
	toplevel->server = server;
	toplevel->xwayland = xwayland;
	test_trace_assign_id(toplevel);
	toplevel->width = xwayland->width;
	toplevel->height = xwayland->height;
	toplevel->border_width = configured_border_width(server);
	toplevel->title_bar_height = configured_title_bar_height(server);
	wl_list_init(&toplevel->link);
	wl_list_insert(&server->xwayland_views, &toplevel->xwayland_link);
	xwayland->data = toplevel;
	toplevel->associate.notify = xwayland_associate;
	wl_signal_add(&xwayland->events.associate, &toplevel->associate);
	toplevel->dissociate.notify = xwayland_dissociate;
	wl_signal_add(&xwayland->events.dissociate, &toplevel->dissociate);
	toplevel->destroy.notify = xwayland_surface_destroy;
	wl_signal_add(&xwayland->events.destroy, &toplevel->destroy);
	toplevel->request_configure.notify = xwayland_request_configure;
	wl_signal_add(&xwayland->events.request_configure, &toplevel->request_configure);
	toplevel->set_title.notify = xwayland_set_title;
	wl_signal_add(&xwayland->events.set_title, &toplevel->set_title);
	toplevel->set_class.notify = xwayland_set_class;
	wl_signal_add(&xwayland->events.set_class, &toplevel->set_class);
	toplevel->set_parent.notify = xwayland_set_parent;
	wl_signal_add(&xwayland->events.set_parent, &toplevel->set_parent);
	toplevel->set_hints.notify = xwayland_set_hints;
	wl_signal_add(&xwayland->events.set_hints, &toplevel->set_hints);
	toplevel->set_override_redirect.notify = xwayland_set_override_redirect;
	wl_signal_add(&xwayland->events.set_override_redirect,
		&toplevel->set_override_redirect);
	toplevel->set_geometry.notify = xwayland_set_geometry;
	wl_signal_add(&xwayland->events.set_geometry, &toplevel->set_geometry);
}

static struct toplevel *xwayland_toplevel_for_window(struct server *server,
		xcb_window_t window) {
	struct toplevel *toplevel;
	wl_list_for_each(toplevel, &server->xwayland_views, xwayland_link) {
		if (toplevel->xwayland->window_id == window) return toplevel;
	}
	return NULL;
}

static void restack_xwayland_toplevel(struct toplevel *toplevel,
		xcb_window_t sibling_window, uint8_t mode) {
	if (!toplevel->mapped || toplevel->xwayland->override_redirect ||
			(mode != XCB_STACK_MODE_ABOVE && mode != XCB_STACK_MODE_BELOW)) return;
	struct toplevel *sibling = xwayland_toplevel_for_window(
		toplevel->server, sibling_window);
	if (sibling != NULL && (!sibling->mapped || sibling->xwayland->override_redirect))
		sibling = NULL;
	wlr_xwayland_surface_restack(toplevel->xwayland,
		sibling != NULL ? sibling->xwayland : NULL, mode);
	wl_list_remove(&toplevel->link);
	if (sibling == NULL) {
		if (mode == XCB_STACK_MODE_ABOVE) {
			wlr_scene_node_raise_to_top(&toplevel->tree->node);
			wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
		} else {
			wlr_scene_node_lower_to_bottom(&toplevel->tree->node);
			wl_list_insert(toplevel->server->toplevels.prev, &toplevel->link);
		}
	} else if (mode == XCB_STACK_MODE_ABOVE) {
		wlr_scene_node_place_above(&toplevel->tree->node, &sibling->tree->node);
		wl_list_insert(sibling->link.prev, &toplevel->link);
	} else {
		wlr_scene_node_place_below(&toplevel->tree->node, &sibling->tree->node);
		wl_list_insert(&sibling->link, &toplevel->link);
	}
	test_trace_toplevel_event(toplevel, "restack", "frame");
}

static void configure_override_redirect(xcb_connection_t *connection,
		xcb_configure_request_event_t *event) {
	uint32_t values[7];
	size_t length = 0;
	if (event->value_mask & XCB_CONFIG_WINDOW_X) values[length++] = (uint32_t)event->x;
	if (event->value_mask & XCB_CONFIG_WINDOW_Y) values[length++] = (uint32_t)event->y;
	if (event->value_mask & XCB_CONFIG_WINDOW_WIDTH) values[length++] = event->width;
	if (event->value_mask & XCB_CONFIG_WINDOW_HEIGHT) values[length++] = event->height;
	if (event->value_mask & XCB_CONFIG_WINDOW_BORDER_WIDTH)
		values[length++] = event->border_width;
	if (event->value_mask & XCB_CONFIG_WINDOW_SIBLING) values[length++] = event->sibling;
	if (event->value_mask & XCB_CONFIG_WINDOW_STACK_MODE) values[length++] = event->stack_mode;
	if (length != 0)
		xcb_configure_window(connection, event->window, event->value_mask, values);
	xcb_flush(connection);
}

static int xwayland_user_event(struct wlr_xwm *xwm, xcb_generic_event_t *event) {
	(void)xwm;
	struct server *server = xwayland_event_server;
	if (server == NULL || server->xwayland == NULL) return 0;
	uint8_t type = event->response_type & ~UINT8_C(0x80);
	if (type == XCB_PROPERTY_NOTIFY) {
		xcb_property_notify_event_t *property = (xcb_property_notify_event_t *)event;
		struct toplevel *toplevel =
			xwayland_toplevel_for_window(server, property->window);
		if (toplevel == NULL) return 0;
		if (property->atom == server->atom_wm_icon_name)
			read_xwayland_icon_name(toplevel);
		else if (property->atom == server->atom_net_wm_icon)
			read_xwayland_net_wm_icon(toplevel);
		else if (property->atom == server->atom_wm_normal_hints ||
				property->atom == server->atom_wm_protocols ||
				property->atom == server->atom_wm_transient_for)
			schedule_xwayland_sync(toplevel);
		return 0;
	}
	if (type != XCB_CONFIGURE_REQUEST) return 0;
	xcb_configure_request_event_t *configure =
		(xcb_configure_request_event_t *)event;
	struct toplevel *toplevel =
		xwayland_toplevel_for_window(server, configure->window);
	if (toplevel == NULL) return 0;
	toplevel->pending_configure_mask = configure->value_mask;
	if (toplevel->xwayland->override_redirect) {
		xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(server->xwayland);
		if (connection != NULL) configure_override_redirect(connection, configure);
		return 1;
	}
	if (configure->value_mask & XCB_CONFIG_WINDOW_STACK_MODE) {
		xcb_window_t sibling = configure->value_mask & XCB_CONFIG_WINDOW_SIBLING ?
			configure->sibling : XCB_WINDOW_NONE;
		restack_xwayland_toplevel(toplevel, sibling, configure->stack_mode);
	}
	uint16_t geometry = XCB_CONFIG_WINDOW_X | XCB_CONFIG_WINDOW_Y |
		XCB_CONFIG_WINDOW_WIDTH | XCB_CONFIG_WINDOW_HEIGHT;
	return (configure->value_mask & geometry) == 0 ? 1 : 0;
}

static struct popup *popup_from_xdg(struct server *server,
	struct wlr_xdg_popup *xdg) {
	struct popup *popup;
	wl_list_for_each(popup, &server->popups, link) {
		if (popup->xdg == xdg) return popup;
	}
	return NULL;
}

static bool popup_parent_info(struct server *server, struct wlr_surface *surface,
	struct toplevel **root, unsigned *depth) {
	struct wlr_xdg_surface *parent = wlr_xdg_surface_try_from_wlr_surface(surface);
	if (parent == NULL) return false;
	if (parent->role == WLR_XDG_SURFACE_ROLE_TOPLEVEL && parent->toplevel != NULL) {
		struct toplevel *toplevel = toplevel_from_xdg(parent->toplevel);
		if (toplevel == NULL || !toplevel->mapped ||
			parent->data != toplevel->content) return false;
		*root = toplevel;
		*depth = 1;
		return true;
	}
	if (parent->role == WLR_XDG_SURFACE_ROLE_POPUP && parent->popup != NULL) {
		struct popup *popup = popup_from_xdg(server, parent->popup);
		if (popup == NULL || !popup->mapped || popup->root == NULL ||
			!popup->root->mapped || popup->tree == NULL || parent->data != popup->tree)
			return false;
		*root = popup->root;
		*depth = popup->depth + 1;
		return true;
	}
	return false;
}

static bool sync_popup_position(struct popup *popup) {
	struct toplevel *root = popup->root;
	if (popup->tree == NULL || root == NULL || root->xdg == NULL ||
			root->content == NULL) return false;
	int content_x = 0;
	int content_y = 0;
	if (!wlr_scene_node_coords(&root->content->node, &content_x, &content_y))
		return false;
	struct wlr_box root_geometry;
	wlr_xdg_surface_get_geometry(root->xdg->base, &root_geometry);
	int popup_x = 0;
	int popup_y = 0;
	wlr_xdg_popup_get_toplevel_coords(popup->xdg,
		popup->xdg->current.geometry.x, popup->xdg->current.geometry.y,
		&popup_x, &popup_y);
	wlr_scene_node_set_position(&popup->tree->node,
		content_x - root_geometry.x + popup_x,
		content_y - root_geometry.y + popup_y);
	return true;
}

static void sync_toplevel_popups(struct toplevel *toplevel) {
	if (toplevel == NULL || toplevel->xdg == NULL) return;
	struct popup *popup;
	wl_list_for_each(popup, &toplevel->server->popups, link) {
		if (popup->root == toplevel) sync_popup_position(popup);
	}
}

static bool surface_belongs_to_popup(struct wlr_surface *surface,
	struct popup *target) {
	if (surface == NULL) return false;
	surface = wlr_surface_get_root_surface(surface);
	struct wlr_xdg_popup *popup;
	while ((popup = wlr_xdg_popup_try_from_wlr_surface(surface)) != NULL) {
		if (popup == target->xdg) return true;
		if (popup->parent == NULL) return false;
		surface = wlr_surface_get_root_surface(popup->parent);
	}
	return false;
}

static bool popup_constraint_box(struct popup *popup, struct wlr_box *box) {
	struct toplevel *root = popup->root;
	if (root == NULL || !root->mapped || root->content == NULL) return false;
	int geometry_lx = 0, geometry_ly = 0;
	if (!wlr_scene_node_coords(&root->content->node, &geometry_lx, &geometry_ly))
		return false;
	struct wlr_box geometry;
	wlr_xdg_surface_get_geometry(root->xdg->base, &geometry);
	struct wlr_output *output = wlr_output_layout_output_at(
		root->server->output_layout,
		geometry_lx + geometry.width / 2.0,
		geometry_ly + geometry.height / 2.0);
	if (output == NULL)
		output = wlr_output_layout_get_center_output(root->server->output_layout);
	if (output == NULL) return false;
	wlr_output_layout_get_box(root->server->output_layout, output, box);
	int surface_lx = geometry_lx - geometry.x;
	int surface_ly = geometry_ly - geometry.y;
	box->x -= surface_lx;
	box->y -= surface_ly;
	return box->width > 0 && box->height > 0;
}

static void configure_popup(struct popup *popup) {
	struct wlr_box box;
	if (popup_constraint_box(popup, &box))
		wlr_xdg_popup_unconstrain_from_box(popup->xdg, &box);
	else
		wlr_xdg_surface_schedule_configure(popup->xdg->base);
}

static void popup_map(struct wl_listener *listener, void *data) {
	(void)data;
	struct popup *popup = wl_container_of(listener, popup, map);
	popup->mapped = true;
	sync_popup_position(popup);
	wlr_scene_node_raise_to_top(&popup->tree->node);
}

static void popup_unmap(struct wl_listener *listener, void *data) {
	(void)data;
	struct popup *popup = wl_container_of(listener, popup, unmap);
	popup->mapped = false;
	if (surface_belongs_to_popup(
			popup->server->seat->pointer_state.focused_surface, popup))
		wlr_seat_pointer_clear_focus(popup->server->seat);
}

static void popup_commit(struct wl_listener *listener, void *data) {
	(void)data;
	struct popup *popup = wl_container_of(listener, popup, commit);
	if (popup->xdg->base->initial_commit) configure_popup(popup);
	sync_popup_position(popup);
}

static void popup_reposition(struct wl_listener *listener, void *data) {
	(void)data;
	struct popup *popup = wl_container_of(listener, popup, reposition);
	configure_popup(popup);
}

static void popup_scene_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct popup *popup = wl_container_of(listener, popup, scene_destroy);
	if (popup->xdg->base->data == popup->tree) popup->xdg->base->data = NULL;
	popup->tree = NULL;
	wl_list_remove(&popup->scene_destroy.link);
	wl_list_init(&popup->scene_destroy.link);
}

static void popup_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct popup *popup = wl_container_of(listener, popup, destroy);
	popup->mapped = false;
	if (surface_belongs_to_popup(
			popup->server->seat->pointer_state.focused_surface, popup))
		wlr_seat_pointer_clear_focus(popup->server->seat);
	wl_list_remove(&popup->map.link);
	wl_list_remove(&popup->unmap.link);
	wl_list_remove(&popup->commit.link);
	wl_list_remove(&popup->reposition.link);
	wl_list_remove(&popup->destroy.link);
	if (popup->xdg->base->data == popup->tree) popup->xdg->base->data = NULL;
	if (popup->tree != NULL) wlr_scene_node_destroy(&popup->tree->node);
	wl_list_remove(&popup->link);
	free(popup);
}

static void new_popup(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, new_popup);
	struct wlr_xdg_popup *xdg = data;
	struct popup *popup = calloc(1, sizeof(*popup));
	if (popup == NULL) {
		wlr_xdg_popup_destroy(xdg);
		return;
	}
	popup->server = server;
	popup->xdg = xdg;
	wl_list_init(&popup->link);
	wl_list_init(&popup->scene_destroy.link);
	if (!popup_parent_info(server, xdg->parent,
			&popup->root, &popup->depth)) {
		wlr_log(WLR_ERROR, "%s",
			"dismissing xdg popup with an unmanaged parent");
		free(popup);
		wlr_xdg_popup_destroy(xdg);
		return;
	}
	popup->tree = wlr_scene_xdg_surface_create(server->overlay_tree, xdg->base);
	if (popup->tree == NULL) {
		free(popup);
		wlr_xdg_popup_destroy(xdg);
		return;
	}
	popup->tree->node.data = popup->root;
	xdg->base->data = popup->tree;
	sync_popup_position(popup);
	popup->scene_destroy.notify = popup_scene_destroy;
	wl_signal_add(&popup->tree->node.events.destroy, &popup->scene_destroy);
	wl_list_insert(&server->popups, &popup->link);
	popup->map.notify = popup_map;
	wl_signal_add(&xdg->base->surface->events.map, &popup->map);
	popup->unmap.notify = popup_unmap;
	wl_signal_add(&xdg->base->surface->events.unmap, &popup->unmap);
	popup->commit.notify = popup_commit;
	wl_signal_add(&xdg->base->surface->events.commit, &popup->commit);
	popup->reposition.notify = popup_reposition;
	wl_signal_add(&xdg->events.reposition, &popup->reposition);
	popup->destroy.notify = popup_destroy;
	wl_signal_add(&xdg->events.destroy, &popup->destroy);
}

static void decoration_request_mode(struct wl_listener *listener, void *data) {
	(void)data;
	struct decoration *decoration = wl_container_of(listener, decoration, request_mode);
	wlr_xdg_toplevel_decoration_v1_set_mode(decoration->wlr,
		WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
}

static void decoration_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct decoration *decoration = wl_container_of(listener, decoration, destroy);
	wl_list_remove(&decoration->request_mode.link);
	wl_list_remove(&decoration->destroy.link);
	free(decoration);
}

static void new_decoration(struct wl_listener *listener, void *data) {
	(void)listener;
	struct decoration *decoration = calloc(1, sizeof(*decoration));
	if (decoration == NULL) return;
	decoration->wlr = data;
	decoration->request_mode.notify = decoration_request_mode;
	wl_signal_add(&decoration->wlr->events.request_mode, &decoration->request_mode);
	decoration->destroy.notify = decoration_destroy;
	wl_signal_add(&decoration->wlr->events.destroy, &decoration->destroy);
	wlr_xdg_toplevel_decoration_v1_set_mode(decoration->wlr,
		WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
}

#ifdef WTWM_TEST_CONTROL
static const char *toplevel_app_id(const struct toplevel *toplevel) {
	const char *app_id = toplevel->xdg != NULL ? toplevel->xdg->app_id :
		(toplevel->xwayland != NULL ? toplevel->xwayland->class : NULL);
	return app_id != NULL ? app_id : "";
}

static void test_write(struct test_control *control, const char *format, ...) {
	if (control->client_fd < 0) return;
	va_list args;
	va_start(args, format);
	(void)vdprintf(control->client_fd, format, args);
	va_end(args);
}

static void test_write_json_string(struct test_control *control, const char *text) {
	test_write(control, "\"");
	if (text == NULL) text = "";
	for (const unsigned char *c = (const unsigned char *)text; *c != '\0'; ++c) {
		switch (*c) {
		case '\\': test_write(control, "\\\\"); break;
		case '"': test_write(control, "\\\""); break;
		case '\n': test_write(control, "\\n"); break;
		case '\r': test_write(control, "\\r"); break;
		case '\t': test_write(control, "\\t"); break;
		default:
			if (*c < 0x20) test_write(control, "\\u%04x", *c);
			else test_write(control, "%c", *c);
			break;
		}
	}
	test_write(control, "\"");
}

static void test_write_trace(struct test_control *control) {
	uint64_t first_sequence = control->trace_event_count != 0 ?
		control->trace_events[0].sequence : control->trace_next_sequence + 1;
	test_write(control,
		"OK TRACE {\"version\":1,\"first_seq\":%" PRIu64
		",\"next_seq\":%" PRIu64 ",\"dropped\":%" PRIu64 ",\"events\":[",
		first_sequence, control->trace_next_sequence, control->trace_dropped);
	for (size_t i = 0; i < control->trace_event_count; ++i) {
		const struct test_trace_event *event = &control->trace_events[i];
		if (i != 0) test_write(control, ",");
		test_write(control, "{\"seq\":%" PRIu64 ",\"event\":",
			event->sequence);
		test_write_json_string(control, event->event);
		test_write(control, ",\"context\":");
		test_write_json_string(control, event->context);
		test_write(control, ",\"window\":{\"id\":%" PRIu64 ",\"type\":",
			event->window_id);
		test_write_json_string(control, event->type);
		test_write(control, ",\"title\":");
		test_write_json_string(control, event->title);
		test_write(control, ",\"app_id\":");
		test_write_json_string(control, event->app_id);
		test_write(control, ",\"instance\":");
		test_write_json_string(control, event->instance);
		test_write(control, ",\"class\":");
		test_write_json_string(control, event->class_name);
		test_write(control, ",\"icon_name\":");
		test_write_json_string(control, event->icon_name);
		test_write(control,
			"},\"geometry\":{\"client\":{\"x\":%d,\"y\":%d,"
			"\"width\":%d,\"height\":%d},\"frame\":{\"x\":%d,\"y\":%d,"
			"\"width\":%d,\"height\":%d,\"outer_width\":%d,"
			"\"outer_height\":%d,\"border_width\":%d,"
			"\"title_bar_height\":%d,\"title_height\":%d,"
			"\"content_x\":%d,\"content_y\":%d}},"
			"\"state\":{\"mapped\":%s,\"iconified\":%s,\"focused\":%s,"
			"\"stack\":",
			event->client_x, event->client_y,
			event->client_width, event->client_height,
			event->frame_x, event->frame_y,
			event->frame_width, event->frame_height,
			event->outer_width, event->outer_height,
			event->border_width, event->title_bar_height,
			event->title_height, event->content_x, event->content_y,
			event->mapped ? "true" : "false",
			event->iconified ? "true" : "false",
			event->focused ? "true" : "false");
		if (event->stack < 0) test_write(control, "null");
		else test_write(control, "%d", event->stack);
		test_write(control, "}}");
	}
	test_write(control, "]}\n");
}

static void test_trace_clear(struct test_control *control) {
	control->trace_event_count = 0;
	control->trace_next_sequence = 0;
	control->trace_dropped = 0;
}

static void test_write_state(struct test_control *control) {
	struct server *server = control->server;
	struct wlr_surface *focused = server->seat->keyboard_state.focused_surface;
	struct toplevel *focused_toplevel = toplevel_for_surface(focused);
	test_write(control, "OK STATE {\"frame\":%" PRIu64
		",\"animation_ms\":%u,\"placement_seed\":%u,"
		"\"cursor\":{\"x\":%.3f,\"y\":%.3f},\"focus\":",
		server->frame_sequence, control->animation_ms, server->placement_index,
		server->cursor->x, server->cursor->y);
	if (focused_toplevel == NULL) test_write(control, "null");
	else test_write_json_string(control, toplevel_title(focused_toplevel));
	test_write(control, ",\"windows\":[");
	bool first = true;
	unsigned stack = 0;
	struct toplevel *toplevel;
	wl_list_for_each(toplevel, &server->toplevels, link) {
		if (!first) test_write(control, ",");
		first = false;
		struct wtwm_frame_geometry geometry;
		toplevel_geometry(toplevel, &geometry);
		test_write(control, "{\"id\":%" PRIu64 ",\"title\":",
			toplevel->test_id);
		test_write_json_string(control, toplevel_title(toplevel));
		test_write(control, ",\"app_id\":");
		test_write_json_string(control, toplevel_app_id(toplevel));
		test_write(control, ",\"type\":\"%s\",\"instance\":",
			toplevel->xwayland != NULL ? "x11" : "wayland");
		test_write_json_string(control, toplevel->xwayland != NULL ?
			toplevel->xwayland->instance : "");
		test_write(control, ",\"class\":");
		test_write_json_string(control, toplevel->xwayland != NULL ?
			toplevel->xwayland->class : "");
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
			"\"border_width\":%d,\"title_bar_height\":%d,\"title_height\":%d,"
			"\"frame_width\":%d,\"frame_height\":%d,"
			"\"outer_width\":%d,\"outer_height\":%d,"
			"\"content_x\":%d,\"content_y\":%d,"
			"\"stack\":%u,\"mapped\":%s,\"iconified\":%s,"
			"\"decorated\":%s,\"auto_raise\":%s",
			toplevel->tree->node.x, toplevel->tree->node.y,
			toplevel->width, toplevel->height,
			geometry.border_width, geometry.title_bar_height, geometry.title_extent,
			geometry.frame_width, geometry.frame_height,
			geometry.outer_width, geometry.outer_height,
			geometry.content_x, geometry.content_y, stack++,
			toplevel->mapped ? "true" : "false",
			toplevel->iconified ? "true" : "false",
			toplevel->decorated ? "true" : "false",
			toplevel->auto_raise ? "true" : "false");
		if (toplevel->xwayland != NULL) {
			struct wlr_xwayland_surface *xsurface = toplevel->xwayland;
			xcb_icccm_wm_hints_t *hints = xsurface->hints;
			xcb_size_hints_t *size = xsurface->size_hints;
			test_write(control,
				",\"xid\":%" PRIu32 ",\"parent\":%" PRIu32
				",\"client_x\":%d,\"client_y\":%d,\"original_border_width\":%d"
				",\"supports_delete\":%s,\"urgent\":%s,\"input\":%s,"
				"\"icon_pixmap\":%" PRIu32 ",\"icon_mask\":%" PRIu32
				",\"icon_window\":%" PRIu32 ",\"icon_name\":",
				xsurface->window_id,
				xsurface->parent != NULL ? xsurface->parent->window_id : XCB_WINDOW_NONE,
				xsurface->x, xsurface->y, toplevel->original_client_border,
				xwayland_supports_delete(toplevel) ? "true" : "false",
				hints != NULL &&
					(hints->flags & XCB_ICCCM_WM_HINT_X_URGENCY) != 0 ? "true" : "false",
				hints == NULL || hints->input ? "true" : "false",
				hints != NULL ? hints->icon_pixmap : XCB_PIXMAP_NONE,
				hints != NULL ? hints->icon_mask : XCB_PIXMAP_NONE,
				hints != NULL ? hints->icon_window : XCB_WINDOW_NONE);
			test_write_json_string(control, toplevel->icon_name);
			test_write(control,
				",\"net_wm_icon\":{\"count\":%" PRIu32
				",\"width\":%" PRIu32 ",\"height\":%" PRIu32
				",\"checksum\":%" PRIu32 ",\"truncated\":%s},"
				"\"size_hints\":{\"flags\":%" PRIu32
				",\"min_width\":%d,\"min_height\":%d,"
				"\"max_width\":%d,\"max_height\":%d,"
				"\"base_width\":%d,\"base_height\":%d,"
				"\"width_inc\":%d,\"height_inc\":%d,"
				"\"min_aspect_num\":%d,\"min_aspect_den\":%d,"
				"\"max_aspect_num\":%d,\"max_aspect_den\":%d,"
				"\"gravity\":%" PRIu32 "}",
				toplevel->net_wm_icon_count, toplevel->net_wm_icon_width,
				toplevel->net_wm_icon_height, toplevel->net_wm_icon_checksum,
				toplevel->net_wm_icon_truncated ? "true" : "false",
				size != NULL ? size->flags : 0,
				size != NULL ? size->min_width : 0,
				size != NULL ? size->min_height : 0,
				size != NULL ? size->max_width : 0,
				size != NULL ? size->max_height : 0,
				size != NULL ? size->base_width : 0,
				size != NULL ? size->base_height : 0,
				size != NULL ? size->width_inc : 0,
				size != NULL ? size->height_inc : 0,
				size != NULL ? size->min_aspect_num : 0,
				size != NULL ? size->min_aspect_den : 0,
				size != NULL ? size->max_aspect_num : 0,
				size != NULL ? size->max_aspect_den : 0,
				size != NULL ? size->win_gravity : 0);
		} else {
			uint32_t flags = 0;
			if (toplevel->xdg->current.min_width > 0 ||
					toplevel->xdg->current.min_height > 0)
				flags |= WTWM_SIZE_HINT_MIN;
			if (toplevel->xdg->current.max_width > 0 ||
					toplevel->xdg->current.max_height > 0)
				flags |= WTWM_SIZE_HINT_MAX;
			test_write(control,
				",\"size_hints\":{\"flags\":%" PRIu32
				",\"min_width\":%d,\"min_height\":%d,"
				"\"max_width\":%d,\"max_height\":%d}",
				flags, toplevel->xdg->current.min_width,
				toplevel->xdg->current.min_height,
				toplevel->xdg->current.max_width,
				toplevel->xdg->current.max_height);
		}
		test_write(control, "}");
	}
	test_write(control, "],\"xwayland_lifecycle\":[");
	first = true;
	wl_list_for_each(toplevel, &server->xwayland_views, xwayland_link) {
		if (!first) test_write(control, ",");
		first = false;
		test_write(control,
			"{\"xid\":%" PRIu32 ",\"associated\":%s,\"mapped\":%s,"
			"\"has_buffer\":%s,\"override_redirect\":%s}",
			toplevel->xwayland->window_id,
			toplevel->associated ? "true" : "false",
			toplevel->mapped ? "true" : "false",
			toplevel->xwayland->surface != NULL &&
				wlr_surface_has_buffer(toplevel->xwayland->surface) ? "true" : "false",
			toplevel->xwayland->override_redirect ? "true" : "false");
	}
	test_write(control, "],\"icons\":[");
	first = true;
	wl_list_for_each(toplevel, &server->toplevels, link) {
		if (!toplevel->iconified) continue;
		if (!first) test_write(control, ",");
		first = false;
		test_write_json_string(control, toplevel_title(toplevel));
	}
	test_write(control, "],\"override_redirect\":[");
	first = true;
	wl_list_for_each(toplevel, &server->xwayland_views, xwayland_link) {
		if (!toplevel->mapped || !toplevel->xwayland->override_redirect) continue;
		if (!first) test_write(control, ",");
		first = false;
		test_write(control, "{\"xid\":%" PRIu32 ",\"title\":",
			toplevel->xwayland->window_id);
		test_write_json_string(control, toplevel_title(toplevel));
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,\"mapped\":true}",
			toplevel->tree->node.x, toplevel->tree->node.y,
			toplevel->width, toplevel->height);
	}
	test_write(control, "],\"popups\":[");
	first = true;
	struct popup *popup;
	wl_list_for_each(popup, &server->popups, link) {
		if (!first) test_write(control, ",");
		first = false;
		int x = 0, y = 0;
		bool visible = popup->tree != NULL &&
			wlr_scene_node_coords(&popup->tree->node, &x, &y);
		test_write(control,
			"{\"depth\":%u,\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
			"\"mapped\":%s,\"visible\":%s}",
			popup->depth, x, y, popup->xdg->current.geometry.width,
			popup->xdg->current.geometry.height,
			popup->mapped ? "true" : "false", visible ? "true" : "false");
	}
	test_write(control, "],\"interactive\":%s,\"interaction\":",
		server->grabbed != NULL ? "true" : "false");
	if (server->grabbed == NULL) {
		test_write(control, "null");
	} else {
		const char *axis = server->interaction.constrained_axis ==
			WTWM_AXIS_HORIZONTAL ? "horizontal" :
			server->interaction.constrained_axis == WTWM_AXIS_VERTICAL ?
			"vertical" : "none";
		test_write(control,
			"{\"mode\":\"%s\",\"started\":%s,\"moved\":%s,"
			"\"force\":%s,\"opaque\":%s,\"constrained\":%s,"
			"\"axis\":\"%s\",\"edges\":%" PRIu32 ","
			"\"preview\":{\"x\":%d,\"y\":%d,\"width\":%d,"
			"\"height\":%d}}",
			server->cursor_mode == CURSOR_MOVE ? "move" : "resize",
			server->interaction.started ? "true" : "false",
			server->interaction.moved ? "true" : "false",
			server->interaction.force_move ? "true" : "false",
			server->interaction.opaque_move ? "true" : "false",
			server->interaction.constrained_move ? "true" : "false", axis,
			server->interaction.resize_edges,
			server->interaction.preview.x, server->interaction.preview.y,
			server->interaction.preview.width,
			server->interaction.preview.height);
	}
	test_write(control, ",\"menu\":");
	if (server->menu.tree == NULL) {
		test_write(control, "null");
	} else {
		test_write(control, "{\"name\":");
		test_write_json_string(control, server->menu.definition->name);
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"row_height\":%d,\"selected\":%d}",
			server->menu.x, server->menu.y, server->menu.width,
			server->menu.row_height, server->menu.selected);
	}
	test_write(control, "}\n");
}

static bool test_render_stable(struct server *server, unsigned count) {
	if (wl_list_empty(&server->outputs)) return false;
	for (unsigned i = 0; i < count; ++i) {
		struct output *output;
		wl_list_for_each(output, &server->outputs, link) {
			if (!render_output(output)) return false;
		}
	}
	return true;
}

static bool test_capture_ppm(struct server *server, const char *path,
	char *error, size_t error_size) {
	if (wl_list_empty(&server->outputs)) {
		snprintf(error, error_size, "no output");
		return false;
	}
	struct output *output = wl_container_of(server->outputs.next, output, link);
	struct wlr_scene_output *scene_output =
		wlr_scene_get_scene_output(server->scene, output->wlr);
	struct wlr_output_state state;
	wlr_output_state_init(&state);
	if (scene_output == NULL || !wlr_scene_output_build_state(scene_output, &state, NULL) ||
		state.buffer == NULL) {
		snprintf(error, error_size, "unable to render output");
		wlr_output_state_finish(&state);
		return false;
	}
	void *data = NULL;
	uint32_t format = 0;
	size_t stride = 0;
	if (!wlr_buffer_begin_data_ptr_access(state.buffer,
		WLR_BUFFER_DATA_PTR_ACCESS_READ, &data, &format, &stride)) {
		snprintf(error, error_size, "render buffer is not CPU-readable");
		wlr_output_state_finish(&state);
		return false;
	}
	bool red_first = format == DRM_FORMAT_XBGR8888 || format == DRM_FORMAT_ABGR8888;
	bool blue_first = format == DRM_FORMAT_XRGB8888 || format == DRM_FORMAT_ARGB8888;
	if (!red_first && !blue_first) {
		snprintf(error, error_size, "unsupported pixel format 0x%08x", format);
		wlr_buffer_end_data_ptr_access(state.buffer);
		wlr_output_state_finish(&state);
		return false;
	}
	FILE *stream = fopen(path, "wb");
	if (stream == NULL) {
		snprintf(error, error_size, "%s", strerror(errno));
		wlr_buffer_end_data_ptr_access(state.buffer);
		wlr_output_state_finish(&state);
		return false;
	}
	int width = state.buffer->width;
	int height = state.buffer->height;
	bool ok = fprintf(stream, "P6\n%d %d\n255\n", width, height) > 0;
	for (int y = 0; ok && y < height; ++y) {
		const unsigned char *row = (const unsigned char *)data + (size_t)y * stride;
		for (int x = 0; ok && x < width; ++x) {
			const unsigned char *pixel = row + (size_t)x * 4;
			unsigned char rgb[3];
			if (red_first) {
				rgb[0] = pixel[0]; rgb[1] = pixel[1]; rgb[2] = pixel[2];
			} else {
				rgb[0] = pixel[2]; rgb[1] = pixel[1]; rgb[2] = pixel[0];
			}
			ok = fwrite(rgb, sizeof(rgb), 1, stream) == 1;
		}
	}
	if (fclose(stream) != 0) ok = false;
	wlr_buffer_end_data_ptr_access(state.buffer);
	wlr_output_state_finish(&state);
	if (!ok) snprintf(error, error_size, "failed to write capture");
	return ok;
}

static void test_pointer(struct server *server, double x, double y) {
	wlr_cursor_warp_closest(server->cursor, NULL, x, y);
	process_cursor_motion(server, ++server->test_control.input_time_ms);
}

static void test_execute(struct test_control *control,
	const struct wtwm_test_command *command) {
	struct server *server = control->server;
	switch (command->type) {
	case WTWM_TEST_COMMAND_PING:
		test_write(control, "OK WTWM_TEST_CONTROL 1\n");
		break;
	case WTWM_TEST_COMMAND_OUTPUT: {
		if (!wlr_backend_is_headless(server->backend)) {
			test_write(control, "ERROR OUTPUT requires the headless backend\n");
			break;
		}
		struct wlr_output *output = wlr_headless_add_output(server->backend,
			(unsigned)command->first, (unsigned)command->second);
		if (output == NULL) test_write(control, "ERROR unable to create output\n");
		else test_write(control, "OK OUTPUT %s %d %d\n", output->name,
			command->first, command->second);
		break;
	}
	case WTWM_TEST_COMMAND_POINTER:
	case WTWM_TEST_COMMAND_SET_CURSOR:
		test_pointer(server, command->x, command->y);
		test_trace_input_snapshot(server, "pointer");
		test_write(control, "OK CURSOR %.3f %.3f\n", server->cursor->x, server->cursor->y);
		break;
	case WTWM_TEST_COMMAND_BUTTON: {
		struct wlr_pointer_button_event event = {
			.time_msec = ++control->input_time_ms,
			.button = command->code,
			.state = command->pressed ? WL_POINTER_BUTTON_STATE_PRESSED :
				WL_POINTER_BUTTON_STATE_RELEASED,
		};
		cursor_button(&server->cursor_button, &event);
		wlr_seat_pointer_notify_frame(server->seat);
		test_trace_input_snapshot(server, "button");
		test_write(control, "OK BUTTON %u %s\n", command->code,
			command->pressed ? "press" : "release");
		break;
	}
	case WTWM_TEST_COMMAND_KEY: {
		struct wlr_keyboard_key_event event = {
			.time_msec = ++control->input_time_ms,
			.keycode = command->code,
			.update_state = true,
			.state = command->pressed ? WL_KEYBOARD_KEY_STATE_PRESSED :
				WL_KEYBOARD_KEY_STATE_RELEASED,
		};
		wlr_keyboard_notify_key(&control->keyboard, &event);
		test_trace_input_snapshot(server, "key");
		test_write(control, "OK KEY %u %s\n", command->code,
			command->pressed ? "press" : "release");
		break;
	}
	case WTWM_TEST_COMMAND_STATE:
		test_write_state(control);
		break;
	case WTWM_TEST_COMMAND_TRACE:
		if (command->first != 0) {
			test_trace_clear(control);
			test_write(control, "OK TRACE CLEAR\n");
		} else {
			test_write_trace(control);
		}
		break;
	case WTWM_TEST_COMMAND_WAIT:
		if (!test_render_stable(server, (unsigned)command->first))
			test_write(control, "ERROR unable to render stable frame\n");
		else test_write(control, "OK FRAME %" PRIu64 "\n", server->frame_sequence);
		break;
	case WTWM_TEST_COMMAND_CAPTURE: {
		char error[256];
		if (!test_capture_ppm(server, command->text, error, sizeof(error)))
			test_write(control, "ERROR %s\n", error);
		else test_write(control, "OK CAPTURE %s\n", command->text);
		break;
	}
	case WTWM_TEST_COMMAND_SET_ANIMATION_MS:
		control->animation_ms = (unsigned)command->first;
		test_write(control, "OK ANIMATION_MS %u\n", control->animation_ms);
		break;
	case WTWM_TEST_COMMAND_SET_PLACEMENT_SEED:
		server->placement_index = (unsigned)command->first;
		test_write(control, "OK PLACEMENT_SEED %u\n", server->placement_index);
		break;
	case WTWM_TEST_COMMAND_SET_FONT:
		if (strlen(command->text) >= sizeof(server->config.title_font)) {
			test_write(control, "ERROR font description is too long\n");
			break;
		}
		strcpy(server->config.title_font, command->text);
		strcpy(server->config.menu_font, command->text);
		strcpy(server->config.icon_font, command->text);
		hide_menu(server);
		struct toplevel *toplevel;
		wl_list_for_each(toplevel, &server->toplevels, link) {
			update_title_text(toplevel);
			update_decoration(toplevel);
		}
		test_write(control, "OK FONT %s\n", command->text);
		break;
	case WTWM_TEST_COMMAND_QUIT:
		test_write(control, "OK QUIT\n");
		wl_display_terminate(server->display);
		break;
	}
}

static void test_close_client(struct test_control *control) {
	if (control->client_source != NULL) {
		wl_event_source_remove(control->client_source);
		control->client_source = NULL;
	}
	if (control->client_fd >= 0) close(control->client_fd);
	control->client_fd = -1;
	control->input_length = 0;
}

static int test_client_ready(int fd, uint32_t mask, void *data) {
	struct test_control *control = data;
	if (mask & (WL_EVENT_HANGUP | WL_EVENT_ERROR)) {
		test_close_client(control);
		return 0;
	}
	ssize_t count = read(fd, control->input + control->input_length,
		sizeof(control->input) - control->input_length - 1);
	if (count <= 0) {
		test_close_client(control);
		return 0;
	}
	control->input_length += (size_t)count;
	control->input[control->input_length] = '\0';
	char *line = control->input;
	char *newline;
	while ((newline = strchr(line, '\n')) != NULL) {
		*newline = '\0';
		struct wtwm_test_command command;
		char error[256];
		if (!wtwm_test_command_parse(line, &command, error, sizeof(error)))
			test_write(control, "ERROR %s\n", error);
		else test_execute(control, &command);
		line = newline + 1;
	}
	control->input_length = strlen(line);
	memmove(control->input, line, control->input_length + 1);
	if (control->input_length == sizeof(control->input) - 1) {
		test_write(control, "ERROR command is too long\n");
		control->input_length = 0;
	}
	return 0;
}

static int test_accept_client(int fd, uint32_t mask, void *data) {
	(void)mask;
	struct test_control *control = data;
	int client = accept(fd, NULL, NULL);
	if (client < 0) return 0;
	(void)fcntl(client, F_SETFD, FD_CLOEXEC);
	if (control->client_fd >= 0) {
		(void)dprintf(client, "ERROR another control client is active\n");
		close(client);
		return 0;
	}
	control->client_fd = client;
	control->client_source = wl_event_loop_add_fd(
		wl_display_get_event_loop(control->server->display), client,
		WL_EVENT_READABLE, test_client_ready, control);
	if (control->client_source == NULL) {
		test_close_client(control);
		return 0;
	}
	test_write(control, "OK WTWM_TEST_CONTROL 1\n");
	return 0;
}

static bool test_control_start(struct server *server, const char *path) {
	struct test_control *control = &server->test_control;
	control->server = server;
	if (strlen(path) >= sizeof(control->path)) {
		wlr_log(WLR_ERROR, "%s", "test control path is too long");
		return false;
	}
	strcpy(control->path, path);
	control->listen_fd = socket(AF_UNIX, SOCK_STREAM, 0);
	if (control->listen_fd < 0) return false;
	(void)fcntl(control->listen_fd, F_SETFD, FD_CLOEXEC);
	struct sockaddr_un address = {.sun_family = AF_UNIX};
	strcpy(address.sun_path, path);
	unlink(path);
	if (bind(control->listen_fd, (struct sockaddr *)&address, sizeof(address)) < 0 ||
		listen(control->listen_fd, 1) < 0) {
		close(control->listen_fd);
		control->listen_fd = -1;
		unlink(path);
		return false;
	}
	control->listen_source = wl_event_loop_add_fd(
		wl_display_get_event_loop(server->display), control->listen_fd,
		WL_EVENT_READABLE, test_accept_client, control);
	if (control->listen_source == NULL) {
		close(control->listen_fd);
		control->listen_fd = -1;
		unlink(path);
		return false;
	}
	return true;
}

static void test_control_finish(struct server *server) {
	struct test_control *control = &server->test_control;
	test_close_client(control);
	if (control->listen_source != NULL) wl_event_source_remove(control->listen_source);
	if (control->listen_fd >= 0) close(control->listen_fd);
	if (control->path[0] != '\0') unlink(control->path);
	if (control->keyboard_initialized) wlr_keyboard_finish(&control->keyboard);
	free(control->trace_events);
	control->trace_events = NULL;
}
#endif

static void usage(FILE *stream, const char *program) {
	fprintf(stream, "usage: %s [-d] [-f twmrc] [-s startup-command]", program);
#ifdef WTWM_TEST_CONTROL
	fprintf(stream, " [--test-control path] [--test-socket name]"
		" [--test-backend auto|headless|wayland]");
#endif
	fprintf(stream, "\n");
}

int main(int argc, char **argv) {
	const char *config_path = NULL;
	const char *startup = NULL;
#ifdef WTWM_TEST_CONTROL
	const char *test_control_path = NULL;
	const char *test_socket = NULL;
	const char *test_backend = "auto";
	enum { OPTION_TEST_CONTROL = 256, OPTION_TEST_SOCKET, OPTION_TEST_BACKEND };
	static const struct option options[] = {
		{"debug", no_argument, NULL, 'd'},
		{"config", required_argument, NULL, 'f'},
		{"help", no_argument, NULL, 'h'},
		{"startup", required_argument, NULL, 's'},
		{"test-control", required_argument, NULL, OPTION_TEST_CONTROL},
		{"test-socket", required_argument, NULL, OPTION_TEST_SOCKET},
		{"test-backend", required_argument, NULL, OPTION_TEST_BACKEND},
		{NULL, 0, NULL, 0},
	};
#else
	static const struct option options[] = {
		{"debug", no_argument, NULL, 'd'},
		{"config", required_argument, NULL, 'f'},
		{"help", no_argument, NULL, 'h'},
		{"startup", required_argument, NULL, 's'},
		{NULL, 0, NULL, 0},
	};
#endif
	enum wlr_log_importance log_level = WLR_INFO;
	int option;
	while ((option = getopt_long(argc, argv, "df:hs:", options, NULL)) != -1) {
		switch (option) {
		case 'd': log_level = WLR_DEBUG; break;
		case 'f': config_path = optarg; break;
		case 's': startup = optarg; break;
		case 'h': usage(stdout, argv[0]); return 0;
#ifdef WTWM_TEST_CONTROL
		case OPTION_TEST_CONTROL: test_control_path = optarg; break;
		case OPTION_TEST_SOCKET: test_socket = optarg; break;
		case OPTION_TEST_BACKEND: test_backend = optarg; break;
#endif
		default: usage(stderr, argv[0]); return 2;
		}
	}
#ifdef WTWM_TEST_CONTROL
	if (strcmp(test_backend, "auto") != 0 && strcmp(test_backend, "headless") != 0 &&
		strcmp(test_backend, "wayland") != 0) {
		fprintf(stderr, "wtwm: invalid test backend: %s\n", test_backend);
		return 2;
	}
#endif
	wlr_log_init(log_level, NULL);
	if (signal(SIGCHLD, SIG_DFL) == SIG_ERR) {
		wlr_log_errno(WLR_ERROR, "%s", "failed to restore SIGCHLD handling");
		return 1;
	}
#ifdef WTWM_TEST_CONTROL
	signal(SIGPIPE, SIG_IGN);
#endif
	struct server server = {0};
#ifdef WTWM_TEST_CONTROL
	server.test_control.listen_fd = -1;
	server.test_control.client_fd = -1;
	server.test_control.input_time_ms = 1000;
#endif
	wtwm_config_init(&server.config);
	char config_error[1024];
	if (!wtwm_config_load(&server.config, config_path, config_error, sizeof(config_error))) {
		fprintf(stderr, "wtwm: %s\n", config_error);
		wtwm_config_finish(&server.config);
		return 1;
	}
	if (server.config.warning_count)
		wlr_log(WLR_INFO, "%zu twm directives accepted but not effective; run wtwm-config for details",
			server.config.warning_count);
	server.display = wl_display_create();
#ifdef WTWM_TEST_CONTROL
	if (strcmp(test_backend, "headless") == 0) {
		server.backend = wlr_headless_backend_create(
			wl_display_get_event_loop(server.display));
	} else {
		if (strcmp(test_backend, "wayland") == 0)
			setenv("WLR_BACKENDS", "wayland", true);
		server.backend = wlr_backend_autocreate(
			wl_display_get_event_loop(server.display), NULL);
	}
#else
	server.backend = wlr_backend_autocreate(wl_display_get_event_loop(server.display), NULL);
#endif
	if (server.backend == NULL) goto fail_display;
	server.renderer = wlr_renderer_autocreate(server.backend);
	if (server.renderer == NULL) goto fail_backend;
	wlr_renderer_init_wl_display(server.renderer, server.display);
	server.allocator = wlr_allocator_autocreate(server.backend, server.renderer);
	if (server.allocator == NULL) goto fail_renderer;
	server.compositor = wlr_compositor_create(server.display, 5, server.renderer);
	if (server.compositor == NULL) {
		wlr_allocator_destroy(server.allocator);
		goto fail_renderer;
	}
	wlr_subcompositor_create(server.display);
	wlr_data_device_manager_create(server.display);
	wlr_primary_selection_v1_device_manager_create(server.display);
	server.output_layout = wlr_output_layout_create(server.display);
	wl_list_init(&server.outputs);
	server.new_output.notify = new_output;
	wl_signal_add(&server.backend->events.new_output, &server.new_output);
	server.scene = wlr_scene_create();
	server.scene_layout = wlr_scene_attach_output_layout(server.scene, server.output_layout);
	server.view_tree = wlr_scene_tree_create(&server.scene->tree);
	server.overlay_tree = wlr_scene_tree_create(&server.scene->tree);
	server.menu_tree = wlr_scene_tree_create(&server.scene->tree);
	wl_list_init(&server.toplevels);
	wl_list_init(&server.xwayland_views);
	wl_list_init(&server.popups);
	server.xdg_shell = wlr_xdg_shell_create(server.display, 6);
	server.new_toplevel.notify = new_toplevel;
	wl_signal_add(&server.xdg_shell->events.new_toplevel, &server.new_toplevel);
	server.new_popup.notify = new_popup;
	wl_signal_add(&server.xdg_shell->events.new_popup, &server.new_popup);
	server.decoration_manager = wlr_xdg_decoration_manager_v1_create(server.display);
	server.new_decoration.notify = new_decoration;
	wl_signal_add(&server.decoration_manager->events.new_toplevel_decoration,
		&server.new_decoration);
	server.cursor = wlr_cursor_create();
	wlr_cursor_attach_output_layout(server.cursor, server.output_layout);
	server.cursor_manager = wlr_xcursor_manager_create(NULL, 24);
	server.cursor_motion.notify = cursor_motion;
	wl_signal_add(&server.cursor->events.motion, &server.cursor_motion);
	server.cursor_motion_absolute.notify = cursor_motion_absolute;
	wl_signal_add(&server.cursor->events.motion_absolute, &server.cursor_motion_absolute);
	server.cursor_button.notify = cursor_button;
	wl_signal_add(&server.cursor->events.button, &server.cursor_button);
	server.cursor_axis.notify = cursor_axis;
	wl_signal_add(&server.cursor->events.axis, &server.cursor_axis);
	server.cursor_frame.notify = cursor_frame;
	wl_signal_add(&server.cursor->events.frame, &server.cursor_frame);
	wl_list_init(&server.keyboards);
	server.seat = wlr_seat_create(server.display, "seat0");
	server.new_input.notify = new_input;
	wl_signal_add(&server.backend->events.new_input, &server.new_input);
	server.request_cursor.notify = request_cursor;
	wl_signal_add(&server.seat->events.request_set_cursor, &server.request_cursor);
	server.request_selection.notify = request_selection;
	wl_signal_add(&server.seat->events.request_set_selection, &server.request_selection);
	server.request_primary_selection.notify = request_primary_selection;
	wl_signal_add(&server.seat->events.request_set_primary_selection,
		&server.request_primary_selection);
#ifdef WTWM_TEST_CONTROL
	static const struct wlr_keyboard_impl test_keyboard_impl = {
		.name = "wtwm-test-keyboard",
	};
	wlr_keyboard_init(&server.test_control.keyboard, &test_keyboard_impl,
		"wtwm-test-keyboard");
	server.test_control.keyboard_initialized = true;
	new_keyboard(&server, &server.test_control.keyboard.base);
	/* Test control injects both key and pointer events without backend input
	 * devices, so advertise the matching seat resources to test clients. */
	wlr_seat_set_capabilities(server.seat,
		WL_SEAT_CAPABILITY_KEYBOARD | WL_SEAT_CAPABILITY_POINTER);
	const char *socket = test_socket;
	if (socket != NULL && wl_display_add_socket(server.display, socket) < 0) socket = NULL;
	else if (socket == NULL) socket = wl_display_add_socket_auto(server.display);
#else
	const char *socket = wl_display_add_socket_auto(server.display);
#endif
	if (socket == NULL || !wlr_backend_start(server.backend)) goto fail_runtime;
#ifdef WTWM_TEST_CONTROL
	if (test_control_path != NULL && !test_control_start(&server, test_control_path)) {
		wlr_log(WLR_ERROR, "failed to create test control socket at %s: %s",
			test_control_path, strerror(errno));
		goto fail_runtime;
	}
#endif
	setenv("WAYLAND_DISPLAY", socket, true);
	(void)xwayland_start(&server);
	if (startup != NULL) spawn_shell(startup);
	wlr_log(WLR_INFO, "wtwm running on WAYLAND_DISPLAY=%s", socket);
	wl_display_run(server.display);
	xwayland_finish(&server);
	wl_display_destroy_clients(server.display);
#ifdef WTWM_TEST_CONTROL
	test_control_finish(&server);
#endif
	wlr_scene_node_destroy(&server.scene->tree.node);
	wlr_xcursor_manager_destroy(server.cursor_manager);
	wlr_cursor_destroy(server.cursor);
	wlr_allocator_destroy(server.allocator);
	wlr_renderer_destroy(server.renderer);
	wlr_backend_destroy(server.backend);
	wl_display_destroy(server.display);
	wtwm_config_finish(&server.config);
#ifdef WTWM_TEST_CONTROL
	pango_cairo_font_map_set_default(NULL);
	FcFini();
#endif
	return 0;

fail_runtime:
	xwayland_finish(&server);
#ifdef WTWM_TEST_CONTROL
	test_control_finish(&server);
#endif
	wlr_scene_node_destroy(&server.scene->tree.node);
	wlr_xcursor_manager_destroy(server.cursor_manager);
	wlr_cursor_destroy(server.cursor);
	wlr_allocator_destroy(server.allocator);
fail_renderer:
	wlr_renderer_destroy(server.renderer);
fail_backend:
	wlr_backend_destroy(server.backend);
fail_display:
	wl_display_destroy(server.display);
	wtwm_config_finish(&server.config);
	return 1;
}
