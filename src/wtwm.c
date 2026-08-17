/* SPDX-License-Identifier: MIT
 *
 * wtwm is built on wlroots' public 0.18 scene and xdg-shell APIs.  The small
 * compositor core follows the same event-driven shape as wlroots/tinywl, with
 * server-side decorations and twm actions kept in this project.
 */
#define _POSIX_C_SOURCE 200809L
#define WLR_USE_UNSTABLE

#include "wtwm/config.h"
#include "wtwm/bindings.h"
#include "wtwm/actions.h"
#include "wtwm/command.h"
#include "wtwm/color.h"
#include "wtwm/focus_stack.h"
#include "wtwm/geometry.h"
#include "wtwm/icon_layout.h"
#include "wtwm/icon_manager.h"
#include "wtwm/interaction.h"
#include "wtwm/placement.h"
#include "wtwm/visual.h"
#include "text.h"
#ifdef WTWM_TEST_CONTROL
#include "test_control.h"
#endif

#include <errno.h>
#include <ctype.h>
#include <fcntl.h>
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

enum interaction_intent {
	INTERACTION_DRAG,
	INTERACTION_MENU_POSITION,
	INTERACTION_INITIAL_POSITION,
	INTERACTION_INITIAL_CONFIRM,
	INTERACTION_INITIAL_RESIZE,
};

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
	char placement[12];
	bool mapped;
	bool iconified;
	bool focused;
	bool active;
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
	struct wlr_scene_buffer *frame_pattern;
	struct wlr_scene_tree *title_tree;
	struct wlr_scene_rect *title;
	struct wlr_scene_buffer *focus_mark;
	struct title_button_view *title_buttons;
	size_t title_button_count;
	struct wlr_scene_buffer *title_text;
	struct wlr_scene_tree *icon_tree;
	struct wlr_scene_rect *icon_border;
	struct wlr_scene_rect *icon_background;
	struct wlr_scene_buffer *icon_bitmap;
	struct wlr_scene_buffer *icon_text;
	int icon_x;
	int icon_y;
	int icon_width;
	int icon_height;
	int title_text_height;
	int title_text_width;
	int title_font_ascent;
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
	bool placement_pending;
	bool placement_start_iconified;
	uint64_t placement_order;
	bool iconified;
	bool decorated;
	bool associated;
	bool rules_initialized;
	bool xwayland_map_requested;
	bool start_iconified_match;
	bool auto_raise;
	bool iconify_by_unmapping;
	bool icon_region_allocated;
	bool icon_moved;
	uint64_t icon_identity;
	uint64_t icon_manager_identity;
	char *xwayland_direct_name;
	char *xwayland_direct_instance;
	char *xwayland_direct_class;
	struct wlr_buffer *icon_manager_text_buffer;
	char *icon_manager_text_label;
	char *icon_manager_text_font;
	float icon_manager_text_color[4];
	int icon_manager_text_width;
	int icon_manager_text_height;
	struct wlr_buffer *icon_manager_marker_buffer;
	float icon_manager_marker_color[4];
	int icon_manager_marker_size;
	char icon_source[16];
	struct wtwm_zoom_state zoom;
	enum wtwm_placement_kind placement_kind;
	char *icon_name;
	uint32_t net_wm_icon_width;
	uint32_t net_wm_icon_height;
	uint32_t net_wm_icon_count;
	uint32_t net_wm_icon_checksum;
	bool net_wm_icon_truncated;
	uint32_t *net_wm_icon_pixels;
	unsigned char *wm_hints_icon_bits;
	unsigned int wm_hints_icon_width;
	unsigned int wm_hints_icon_height;
	unsigned int wm_hints_icon_window_width;
	unsigned int wm_hints_icon_window_height;
	struct wl_event_source *xwayland_sync_idle;
#ifdef WTWM_TEST_CONTROL
	uint64_t test_id;
	char test_title[TEST_TRACE_IDENTITY_MAX];
	char test_app_id[TEST_TRACE_IDENTITY_MAX];
	char test_instance[TEST_TRACE_IDENTITY_MAX];
	char test_class_name[TEST_TRACE_IDENTITY_MAX];
	char test_icon_name[TEST_TRACE_IDENTITY_MAX];
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

struct title_button_view {
	struct wlr_scene_rect *border;
	struct wlr_scene_rect *background;
	struct wlr_scene_buffer *bitmap_node;
	struct wtwm_action action;
	char bitmap[WTWM_NAME_MAX];
	bool right_side;
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
	struct wlr_scene_rect *background;
	struct wl_listener background_destroy;
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
	struct menu_view *parent;
	struct wlr_scene_tree *tree;
	struct menu_row_view *rows;
	size_t row_count;
	const struct wtwm_menu *definition;
	struct toplevel *target;
	int x;
	int y;
	int width;
	int height;
	int row_height;
	int selected;
};

struct menu_row_view {
	struct wlr_scene_rect *normal_background;
	struct wlr_scene_rect *highlight_background;
	struct wlr_scene_buffer *normal_text;
	struct wlr_scene_buffer *highlight_text;
	struct wlr_scene_buffer *pull_normal;
	struct wlr_scene_buffer *pull_highlight;
	struct wlr_scene_rect *separator_top;
	struct wlr_scene_rect *separator_bottom;
};

struct menu_row_palette {
	struct wtwm_color foreground;
	struct wtwm_color background;
	struct wtwm_color highlight_foreground;
	struct wtwm_color highlight_background;
	bool user_colors;
};

struct icon_manager_view {
	uint64_t identity;
	struct wlr_scene_tree *tree;
	int x;
	int y;
	int width;
	int height;
	int row_height;
};

struct icon_animation {
	struct wlr_scene_tree *tree;
	struct wlr_scene_rect *top;
	struct wlr_scene_rect *bottom;
	struct wlr_scene_rect *left;
	struct wlr_scene_rect *right;
	struct wl_event_source *timer;
	struct wtwm_interaction_box from;
	struct wtwm_interaction_box to;
	unsigned step;
	unsigned steps;
	unsigned interval_ms;
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
	enum interaction_intent intent;
	uint32_t confirming_button;
	bool force_move;
	bool opaque_move;
	bool constrained_move;
	bool started;
	bool moved;
	bool raised;
	bool icon_move;
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
	bool from_key;
	bool active;
};

struct server {
	struct wtwm_config config;
	enum wtwm_color_mode color_mode;
	struct wl_display *display;
	struct wlr_backend *backend;
	struct wlr_renderer *renderer;
	struct wlr_allocator *allocator;
	struct wlr_compositor *compositor;
	struct wlr_scene *scene;
	struct wlr_scene_tree *view_tree;
	struct wlr_scene_tree *overlay_tree;
	struct wlr_scene_tree *menu_tree;
	struct wlr_scene_tree *icon_manager_tree;
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
	uint64_t placement_order_next;
	struct wtwm_random_placement random_placement;
	struct menu_view menu;
	struct wtwm_icon_layout *icon_layout;
	struct wtwm_icon_manager_state icon_managers;
	struct icon_manager_view icon_manager_views[WTWM_ICON_MANAGER_MAX_MANAGERS];
	size_t icon_manager_view_count;
	struct icon_animation icon_animation;
	uint64_t next_icon_identity;
	struct wtwm_menu windows_menu;
	struct toplevel **windows_menu_targets;
	struct wlr_cursor *cursor;
	struct wlr_xcursor_manager *cursor_manager;
	struct wlr_buffer *configured_cursor_buffer;
	char cursor_role[16];
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
	xcb_atom_t atom_wm_take_focus;
	xcb_atom_t atom_wm_delete_window;
	xcb_atom_t atom_wm_save_yourself;
	xcb_atom_t atom_cut_buffer0;
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
	struct wtwm_action deferred_root_action;
	bool deferred_root_action_active;
	uint32_t current_input_time_ms;
	uint32_t last_move_time_ms;
	bool last_interaction_moved;
	bool action_from_key;
	uint64_t frame_sequence;
	struct toplevel *focus;
	struct toplevel *xwayland_input_focus;
	struct toplevel *pointer_toplevel;
	uint32_t pointer_context;
	uint64_t icon_manager_down_identity;
	bool focus_root;
	const char *config_path;
	int argc;
	char **argv;
	int previous_output_index;
	struct toplevel *ring_leader;
	bool restart_requested;
#ifdef WTWM_TEST_CONTROL
	struct test_control test_control;
#endif
};

static void new_xwayland_surface(struct wl_listener *listener, void *data);
static int xwayland_user_event(struct wlr_xwm *xwm, xcb_generic_event_t *event);
static void resume_action_continuation(struct server *server);
static void process_cursor_motion(struct server *server, uint32_t time_msec);
static void suspend_toplevel(struct toplevel *toplevel, bool suspended);
static void clear_keyboard_focus(struct server *server);
static void set_xwayland_input_focus(struct server *server,
	struct toplevel *toplevel);
static void finish_initial_placement(struct server *server);
static void cancel_initial_placement(struct toplevel *toplevel);
static void start_next_initial_placement(struct server *server);
static void update_title_text(struct toplevel *toplevel);
static void update_decoration(struct toplevel *toplevel);
static void refresh_icon_managers(struct server *server);
static void sync_icon_manager_toplevel(struct toplevel *toplevel);
static void rebuild_icon_layout(struct server *server);
static void finish_icon_animation(struct server *server);
static void manage_bufferless_start_iconified(struct toplevel *toplevel);
static bool icon_selector_matches(const struct wtwm_client_identity *identity,
	const char *selector, unsigned int pass);
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
		wtwm_text_set_x11_connection(connection);
		server->atom_wm_protocols = xwayland_atom(connection, "WM_PROTOCOLS");
		server->atom_wm_take_focus = xwayland_atom(connection, "WM_TAKE_FOCUS");
		server->atom_wm_delete_window = xwayland_atom(connection, "WM_DELETE_WINDOW");
		server->atom_wm_save_yourself = xwayland_atom(connection,
			"WM_SAVE_YOURSELF");
		server->atom_cut_buffer0 = xwayland_atom(connection, "CUT_BUFFER0");
		server->atom_wm_normal_hints = xwayland_atom(connection, "WM_NORMAL_HINTS");
		server->atom_wm_transient_for = xwayland_atom(connection, "WM_TRANSIENT_FOR");
		server->atom_wm_icon_name = xwayland_atom(connection, "WM_ICON_NAME");
		server->atom_net_wm_icon = xwayland_atom(connection, "_NET_WM_ICON");
		set_xwayland_input_focus(server, NULL);
		struct toplevel *toplevel;
		wl_list_for_each(toplevel, &server->toplevels, link) {
			update_title_text(toplevel);
			update_decoration(toplevel);
		}
	}
	wlr_log(WLR_INFO, "Xwayland ready on DISPLAY=%s", server->xwayland->display_name);
}

static void xwayland_finish(struct server *server) {
	if (server->xwayland != NULL) {
		wtwm_text_set_x11_connection(NULL);
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
	bool on_title_button;
	size_t title_button_index;
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

static void finish_surface_frame(struct wlr_surface *surface) {
	if (surface == NULL || !wlr_surface_has_buffer(surface)) return;
	struct timespec now;
	if (clock_gettime(CLOCK_MONOTONIC, &now) == 0)
		wlr_surface_send_frame_done(surface, &now);
}

static const char *xwayland_identity_value(const char *primary,
		const char *direct) {
	return primary != NULL && primary[0] != '\0' ? primary : direct;
}

static const char *toplevel_title(const struct toplevel *toplevel) {
	const char *title = toplevel->xdg != NULL ? toplevel->xdg->title : NULL;
	if (toplevel->xwayland != NULL)
		title = xwayland_identity_value(toplevel->xwayland->title,
			toplevel->xwayland_direct_name);
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

static struct wtwm_client_identity toplevel_identity(
		const struct toplevel *toplevel) {
	if (toplevel == NULL) return (struct wtwm_client_identity){0};
	if (toplevel->xwayland != NULL)
		return (struct wtwm_client_identity){
			.name = xwayland_identity_value(toplevel->xwayland->title,
				toplevel->xwayland_direct_name),
			.resource_name = xwayland_identity_value(toplevel->xwayland->instance,
				toplevel->xwayland_direct_instance),
			.resource_class = xwayland_identity_value(toplevel->xwayland->class,
				toplevel->xwayland_direct_class),
		};
	return (struct wtwm_client_identity){
		.title = toplevel->xdg != NULL ? toplevel->xdg->title : NULL,
		.app_id = toplevel->xdg != NULL ? toplevel->xdg->app_id : NULL,
	};
}

static bool xwayland_color(struct server *server, const char *name,
		struct wtwm_color *color) {
	if (server->xwayland == NULL || name == NULL || strlen(name) > UINT16_MAX)
		return false;
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(server->xwayland);
	if (connection == NULL) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(connection));
	if (screens.rem == 0) return false;
	xcb_lookup_color_reply_t *reply = xcb_lookup_color_reply(connection,
		xcb_lookup_color(connection, screens.data->default_colormap,
			(uint16_t)strlen(name), name), NULL);
	if (reply == NULL) return false;
	*color = (struct wtwm_color){reply->exact_red, reply->exact_green,
		reply->exact_blue};
	free(reply);
	return true;
}

static struct wtwm_color color_result(struct server *server, const char *name) {
	struct wtwm_color parsed = {0, 0, 0};
	if (!wtwm_color_parse_literal(name, &parsed) &&
		!xwayland_color(server, name, &parsed)) {
		wlr_log(WLR_ERROR, "unable to resolve X11 color '%s'",
			name != NULL ? name : "");
	}
	if (server->color_mode == WTWM_COLOR_MODE_GRAYSCALE)
		parsed = wtwm_color_grayscale(parsed);
	else if (server->color_mode == WTWM_COLOR_MODE_MONOCHROME)
		parsed = wtwm_color_monochrome(parsed);
	return parsed;
}

static struct wtwm_color configured_color_result(struct server *server,
		const char *setting, const char *fallback,
		const struct toplevel *toplevel) {
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	const char *value = wtwm_config_color_value(&server->config, setting,
		server->color_mode, toplevel != NULL ? &identity : NULL);
	return color_result(server, value != NULL ? value : fallback);
}

static void configured_color(struct server *server, const char *setting,
		const char *fallback, const struct toplevel *toplevel,
		float color[static 4]) {
	struct wtwm_color parsed = configured_color_result(server, setting, fallback,
		toplevel);
	wtwm_color_to_float(&parsed, color);
}

static bool toplevel_matches(const struct wtwm_string_list *patterns,
		const struct toplevel *toplevel) {
	if (toplevel->xwayland != NULL) {
		struct wtwm_client_identity identity = toplevel_identity(toplevel);
		return wtwm_config_match_x11(patterns, identity.name,
			identity.resource_name, identity.resource_class);
	}
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

static bool window_list_rule(const struct wtwm_config *config,
		const char *directive, const struct wtwm_client_identity *identity,
		bool *bare) {
	bool matched = false;
	if (bare != NULL) *bare = false;
	for (size_t i = 0; i < config->window_list_count; ++i) {
		const struct wtwm_window_list *list = &config->window_lists[i];
		if (strcasecmp(list->directive, directive) != 0) continue;
		if (list->bare) {
			if (bare != NULL) *bare = true;
			matched = true;
		} else if (wtwm_config_match_client(&list->names, identity)) {
			matched = true;
		}
	}
	return matched;
}

static bool should_iconify_by_unmapping(const struct toplevel *toplevel) {
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	bool bare = false;
	bool named = false;
	for (size_t i = 0; i < toplevel->server->config.window_list_count; ++i) {
		const struct wtwm_window_list *list =
			&toplevel->server->config.window_lists[i];
		if (strcasecmp(list->directive, "IconifyByUnmapping") != 0) continue;
		if (list->bare) bare = true;
		else if (wtwm_config_match_client(&list->names, &identity)) named = true;
	}
	if (named) return true;
	if (!bare) return false;
	bool excluded = window_list_rule(&toplevel->server->config,
		"DontIconifyByUnmapping", &identity, NULL);
	return !excluded;
}

static bool initialize_toplevel_rules(struct toplevel *toplevel) {
	if (toplevel->rules_initialized || (toplevel->xwayland != NULL &&
			toplevel->xwayland->override_redirect)) return false;
	toplevel->auto_raise = toplevel->server->config.auto_raise ||
		toplevel_matches(&toplevel->server->config.auto_raise_windows, toplevel);
	toplevel->iconify_by_unmapping = should_iconify_by_unmapping(toplevel);
	toplevel->rules_initialized = true;
	return true;
}

static bool should_start_iconified(const struct toplevel *toplevel,
		bool initial_rules) {
	return initial_rules && (toplevel->start_iconified_match ||
		toplevel_matches(&toplevel->server->config.start_iconified_windows,
			toplevel));
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

static void test_trace_snapshot_identity(struct toplevel *toplevel) {
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	test_trace_copy(toplevel->test_title, toplevel_title(toplevel));
	const char *app_id = toplevel->xdg != NULL ? toplevel->xdg->app_id :
		identity.resource_class;
	test_trace_copy(toplevel->test_app_id, app_id);
	test_trace_copy(toplevel->test_instance, identity.resource_name);
	test_trace_copy(toplevel->test_class_name, identity.resource_class);
	test_trace_copy(toplevel->test_icon_name, toplevel->icon_name);
}

static int test_trace_stack_index(const struct toplevel *toplevel) {
	if (!toplevel->mapped || toplevel->placement_pending ||
			(toplevel->xwayland != NULL &&
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
	/* wlroots resets xdg-toplevel metadata before emitting its destroy signal.
	 * Retain the last pre-destroy snapshot so the final event keeps the stable
	 * protocol identity observed throughout the rest of the ledger. */
	if (strcmp(event, "destroy") != 0) test_trace_snapshot_identity(toplevel);
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
	test_trace_copy(trace->title, toplevel->test_title);
	test_trace_copy(trace->app_id, toplevel->test_app_id);
	test_trace_copy(trace->instance, toplevel->test_instance);
	test_trace_copy(trace->class_name, toplevel->test_class_name);
	test_trace_copy(trace->icon_name, toplevel->test_icon_name);
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
	(void)snprintf(trace->placement, sizeof(trace->placement), "%s",
		wtwm_placement_kind_name(toplevel->placement_kind));
	trace->mapped = toplevel->mapped && !toplevel->placement_pending;
	trace->iconified = toplevel->iconified;
	trace->focused = surface_belongs_to_toplevel(
		toplevel->server->seat->keyboard_state.focused_surface, toplevel);
	trace->active = toplevel->server->focus == toplevel;
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

static struct wtwm_visual_config visual_config(const struct toplevel *toplevel) {
	struct wtwm_visual_config visual = wtwm_visual_config_defaults();
	visual.border_width = toplevel != NULL ? toplevel->border_width : 0;
	const struct wtwm_config *config = toplevel != NULL ?
		&toplevel->server->config : NULL;
	if (config != NULL) {
		visual.frame_padding = config->frame_padding;
		visual.title_padding = config->title_padding;
		visual.button_indent = config->button_indent;
		visual.title_button_border_width = config->title_button_border_width;
		visual.menu_border_width = config->menu_border_width;
		visual.menu_shadows = !config->no_menu_shadows;
	}
	return visual;
}

static bool load_visual_xbm(const struct server *server, const char *name,
		struct wtwm_xbm *bitmap) {
	if (name == NULL || name[0] == '\0' || name[0] == ':') return false;
	char expanded[4096];
	const char *candidate = name;
	if (name[0] == '~' && name[1] == '/') {
		const char *home = getenv("HOME");
		if (home != NULL && snprintf(expanded, sizeof(expanded), "%s/%s", home,
			name + 2) > 0) candidate = expanded;
	}
	char error[512];
	if (wtwm_xbm_load(bitmap, candidate, error, sizeof(error))) return true;
	if (name[0] != '/' && server->config.icon_directory[0] != '\0') {
		char directory[2048];
		const char *base = server->config.icon_directory;
		if (base[0] == '~' && base[1] == '/') {
			const char *home = getenv("HOME");
			if (home != NULL && snprintf(directory, sizeof(directory), "%s/%s",
				home, base + 2) > 0) base = directory;
		}
		if (snprintf(expanded, sizeof(expanded), "%s/%s", base, name) > 0 &&
			wtwm_xbm_load(bitmap, expanded, error, sizeof(error))) return true;
	}
	wlr_log(WLR_ERROR, "unable to load XBM '%s': %s", name, error);
	return false;
}

static bool cursor_role_matches(const char *configured, const char *role) {
	if (strcasecmp(configured, role) == 0) return true;
	return (strcasecmp(role, "Frame") == 0 && strcasecmp(configured, "F") == 0) ||
		(strcasecmp(role, "Title") == 0 && strcasecmp(configured, "T") == 0) ||
		(strcasecmp(role, "Icon") == 0 && strcasecmp(configured, "I") == 0);
}

static const char *default_cursor_name(const char *role) {
	if (strcasecmp(role, "Move") == 0 || strcasecmp(role, "Resize") == 0)
		return "fleur";
	if (strcasecmp(role, "Menu") == 0) return "sb_left_arrow";
	if (strcasecmp(role, "Button") == 0) return "hand2";
	if (strcasecmp(role, "Wait") == 0) return "watch";
	if (strcasecmp(role, "Select") == 0) return "dot";
	if (strcasecmp(role, "Destroy") == 0) return "pirate";
	return "top_left_arrow";
}

static const struct wtwm_cursor *configured_cursor(const struct server *server,
		const char *role) {
	for (size_t i = server->config.cursor_count; i > 0; --i)
		if (cursor_role_matches(server->config.cursors[i - 1].role, role))
			return &server->config.cursors[i - 1];
	return NULL;
}

static void set_cursor_role(struct server *server, const char *role) {
	if (strcmp(server->cursor_role, role) == 0) return;
	const struct wtwm_cursor *cursor = configured_cursor(server, role);
	if (cursor != NULL && cursor->mask[0] != '\0') {
		struct wtwm_xbm source;
		struct wtwm_xbm mask;
		wtwm_xbm_init(&source);
		wtwm_xbm_init(&mask);
		if (load_visual_xbm(server, cursor->source, &source) &&
				load_visual_xbm(server, cursor->mask, &mask)) {
			float foreground[4], background[4];
			configured_color(server, "PointerForeground", "black", NULL,
				foreground);
			configured_color(server, "PointerBackground", "white", NULL,
				background);
			struct wlr_buffer *buffer = wtwm_render_xbm_cursor(&source, &mask,
				foreground, background);
			if (buffer != NULL) {
				int hotspot_x = source.x_hot >= 0 ? source.x_hot : 0;
				int hotspot_y = source.y_hot >= 0 ? source.y_hot : 0;
				wlr_cursor_set_buffer(server->cursor, buffer, hotspot_x, hotspot_y,
					1.0f);
				if (server->configured_cursor_buffer != NULL)
					wlr_buffer_drop(server->configured_cursor_buffer);
				server->configured_cursor_buffer = buffer;
				(void)snprintf(server->cursor_role, sizeof(server->cursor_role),
					"%s", role);
				wtwm_xbm_finish(&mask);
				wtwm_xbm_finish(&source);
				return;
			}
		}
		wtwm_xbm_finish(&mask);
		wtwm_xbm_finish(&source);
	}
	const char *name = cursor != NULL && cursor->mask[0] == '\0' ?
		cursor->source : default_cursor_name(role);
	wlr_cursor_set_xcursor(server->cursor, server->cursor_manager, name);
	if (server->configured_cursor_buffer != NULL) {
		wlr_buffer_drop(server->configured_cursor_buffer);
		server->configured_cursor_buffer = NULL;
	}
	(void)snprintf(server->cursor_role, sizeof(server->cursor_role), "%s", role);
}

static bool create_title_buttons(struct toplevel *toplevel) {
	struct server *server = toplevel->server;
	size_t defaults = server->config.no_defaults ? 0 : 2;
	toplevel->title_button_count = server->config.title_button_count + defaults;
	if (toplevel->title_button_count == 0) return true;
	toplevel->title_buttons = calloc(toplevel->title_button_count,
		sizeof(*toplevel->title_buttons));
	if (toplevel->title_buttons == NULL) return false;
	float border[4], background[4];
	configured_color(server, "TitleForeground", "black", toplevel, border);
	configured_color(server, "TitleBackground", "white", toplevel, background);
	size_t output = 0;
	if (!server->config.no_defaults) {
		toplevel->title_buttons[output].right_side = false;
		(void)snprintf(toplevel->title_buttons[output].bitmap, WTWM_NAME_MAX,
			":iconify");
		toplevel->title_buttons[output].action.type = WTWM_ACTION_ICONIFY;
		++output;
	}
	for (size_t side = 0; side < 2; ++side)
		for (size_t i = 0; i < server->config.title_button_count; ++i) {
			const struct wtwm_title_button *configured =
				&server->config.title_buttons[i];
			if (configured->right_side != (side != 0)) continue;
			struct title_button_view *button = &toplevel->title_buttons[output++];
			button->right_side = configured->right_side;
			button->action = configured->action;
			(void)snprintf(button->bitmap, sizeof(button->bitmap), "%s",
				configured->bitmap);
		}
	if (!server->config.no_defaults) {
		struct title_button_view *button = &toplevel->title_buttons[output++];
		button->right_side = true;
		(void)snprintf(button->bitmap, sizeof(button->bitmap), ":resize");
		button->action.type = WTWM_ACTION_RESIZE;
	}
	for (size_t i = 0; i < output; ++i) {
		struct title_button_view *button = &toplevel->title_buttons[i];
		button->border = wlr_scene_rect_create(toplevel->title_tree, 1, 1, border);
		button->background = wlr_scene_rect_create(toplevel->title_tree, 1, 1,
			background);
		button->bitmap_node = wlr_scene_buffer_create(toplevel->title_tree, NULL);
		if (button->border == NULL || button->background == NULL ||
				button->bitmap_node == NULL) return false;
	}
	return output == toplevel->title_button_count;
}

static bool create_title_scene(struct toplevel *toplevel) {
	float title[4];
	configured_color(toplevel->server, "TitleBackground", "white", toplevel,
		title);
	toplevel->title_tree = wlr_scene_tree_create(toplevel->tree);
	if (toplevel->title_tree == NULL) return false;
	toplevel->title = wlr_scene_rect_create(toplevel->title_tree, 1, 1, title);
	toplevel->focus_mark = wlr_scene_buffer_create(toplevel->title_tree, NULL);
	toplevel->title_text = wlr_scene_buffer_create(toplevel->title_tree, NULL);
	return toplevel->title != NULL && toplevel->focus_mark != NULL &&
		toplevel->title_text != NULL && create_title_buttons(toplevel);
}

static const char *title_highlight_bitmap(const struct server *server) {
	for (size_t i = server->config.pixmap_count; i > 0; --i)
		if (strcasecmp(server->config.pixmaps[i - 1].name,
				"TitleHighlight") == 0)
			return server->config.pixmaps[i - 1].value;
	return NULL;
}

static void update_title_text(struct toplevel *toplevel) {
	if (toplevel->title_text == NULL) return;
	int font_height = 1;
	int font_ascent = 1;
	(void)wtwm_measure_font_metrics(toplevel->server->config.title_font,
		&font_height, &font_ascent);
	toplevel->title_bar_height = wtwm_title_bar_height(font_height,
		toplevel->server->config.frame_padding);
	float foreground[4];
	configured_color(toplevel->server, "TitleForeground", "black", toplevel,
		foreground);
	int width = 0, height = 0;
	struct wlr_buffer *buffer = wtwm_render_text(toplevel_title(toplevel),
		toplevel->server->config.title_font, foreground, &width, &height);
	if (buffer == NULL) return;
	toplevel->title_text_width = width;
	toplevel->title_text_height = height;
	toplevel->title_font_ascent = font_ascent;
	wlr_scene_buffer_set_buffer(toplevel->title_text, buffer);
	wlr_buffer_drop(buffer);
}

static void update_decoration(struct toplevel *toplevel) {
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	toplevel->title_height = geometry.title_extent;
	int border = geometry.border_width;
	float border_color[4], title_color[4], foreground[4];
	configured_color(toplevel->server, "BorderColor", "black", toplevel,
		border_color);
	configured_color(toplevel->server, "TitleBackground", "white", toplevel,
		title_color);
	configured_color(toplevel->server, "TitleForeground", "black", toplevel,
		foreground);
	wlr_scene_rect_set_color(toplevel->frame, border_color);
	float tile_foreground[4], tile_background[4];
	configured_color(toplevel->server, "BorderTileForeground", "black", toplevel,
		tile_foreground);
	configured_color(toplevel->server, "BorderTileBackground", "white", toplevel,
		tile_background);
	wlr_scene_rect_set_color(toplevel->title, title_color);
	unsigned int left_count = 0;
	unsigned int right_count = 0;
	for (size_t i = 0; i < toplevel->title_button_count; ++i) {
		if (toplevel->title_buttons[i].right_side) ++right_count;
		else ++left_count;
	}
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	bool has_title_highlight = !wtwm_config_window_list_matches(
		&toplevel->server->config, "NoTitleHighlight", &identity);
	struct wtwm_visual_config visual = visual_config(toplevel);
	int font_height = toplevel->title_text_height > 0 ?
		toplevel->title_text_height : wtwm_measure_font_height(
			toplevel->server->config.title_font);
	int font_ascent = toplevel->title_font_ascent > 0 ?
		toplevel->title_font_ascent : font_height;
	struct wtwm_title_layout layout;
	wtwm_title_layout_compute(&visual, geometry.client_width, font_height,
		font_ascent, toplevel->title_text_width, left_count, right_count,
		has_title_highlight, &layout);
	int title_width = geometry.client_width;
	int title_x = border;
	struct wtwm_squeeze_rule squeeze;
	if (wtwm_config_squeeze_rule(&toplevel->server->config, &identity,
			&squeeze)) {
		title_width = layout.squeezed_title_width;
		enum wtwm_title_justification justification =
			squeeze.justification == WTWM_SQUEEZE_CENTER ?
				WTWM_TITLE_JUSTIFY_CENTER :
			(squeeze.justification == WTWM_SQUEEZE_RIGHT ?
				WTWM_TITLE_JUSTIFY_RIGHT : WTWM_TITLE_JUSTIFY_LEFT);
		int reference_x = wtwm_title_squeeze_x(geometry.client_width,
			title_width, border, justification, squeeze.numerator,
			squeeze.denominator);
		title_x = 2 * border + reference_x;
		wtwm_title_layout_compute(&visual, title_width, font_height,
			font_ascent, toplevel->title_text_width, left_count, right_count,
			has_title_highlight, &layout);
	}
	wlr_scene_rect_set_size(toplevel->frame,
		geometry.outer_width, geometry.outer_height);
	static const unsigned char border_bits[] = {0x02, 0x01};
	struct wlr_buffer *frame_pattern = wtwm_render_pattern(
		geometry.outer_width, geometry.outer_height, border_bits, 2, 2,
		tile_foreground, tile_background);
	if (frame_pattern != NULL) {
		wlr_scene_buffer_set_buffer(toplevel->frame_pattern, frame_pattern);
		wlr_buffer_drop(frame_pattern);
	}
	bool border_highlight = !wtwm_config_window_list_matches(
		&toplevel->server->config, "NoHighlight", &identity);
	wlr_scene_node_set_enabled(&toplevel->frame_pattern->node,
		border_highlight && toplevel->server->focus != toplevel &&
		toplevel_has_frame(toplevel));
	wlr_scene_rect_set_size(toplevel->title,
		layout.title.width, layout.title.height > 0 ? layout.title.height : 1);
	wlr_scene_node_set_position(&toplevel->title_tree->node, title_x, border);
	static const unsigned char gray_bits[] = {0x02, 0x01};
	const unsigned char *highlight_bits = gray_bits;
	unsigned int highlight_width = 2;
	unsigned int highlight_height = 2;
	struct wtwm_xbm highlight_bitmap;
	wtwm_xbm_init(&highlight_bitmap);
	const char *highlight_name = title_highlight_bitmap(toplevel->server);
	if (highlight_name != NULL && load_visual_xbm(toplevel->server,
			highlight_name, &highlight_bitmap)) {
		highlight_bits = highlight_bitmap.data;
		highlight_width = highlight_bitmap.width;
		highlight_height = highlight_bitmap.height;
	}
	struct wlr_buffer *highlight = wtwm_render_pattern(
		layout.focus_highlight.width, layout.focus_highlight.height,
		highlight_bits, highlight_width, highlight_height, foreground, title_color);
	if (highlight != NULL) {
		wlr_scene_buffer_set_buffer(toplevel->focus_mark, highlight);
		wlr_buffer_drop(highlight);
	}
	wtwm_xbm_finish(&highlight_bitmap);
	wlr_scene_node_set_position(&toplevel->focus_mark->node,
		layout.focus_highlight.x, layout.focus_highlight.y);
	wlr_scene_node_set_enabled(&toplevel->focus_mark->node,
		toplevel->server->focus == toplevel && toplevel->decorated &&
		layout.focus_highlight_visible);
	unsigned int left_index = 0;
	unsigned int right_index = 0;
	for (size_t i = 0; i < toplevel->title_button_count; ++i) {
		struct title_button_view *button = &toplevel->title_buttons[i];
		struct wtwm_visual_box box;
		unsigned int index = button->right_side ? right_index++ : left_index++;
		bool valid = wtwm_title_button_box(&layout, button->right_side, index,
			&box);
		wlr_scene_node_set_enabled(&button->border->node,
			valid && toplevel->decorated);
		wlr_scene_node_set_enabled(&button->background->node,
			valid && toplevel->decorated);
		wlr_scene_node_set_enabled(&button->bitmap_node->node,
			valid && toplevel->decorated);
		if (!valid) continue;
		wlr_scene_rect_set_color(button->border, foreground);
		wlr_scene_rect_set_color(button->background, title_color);
		wlr_scene_rect_set_size(button->border, box.width, box.height);
		wlr_scene_rect_set_size(button->background, layout.button_inner_size,
			layout.button_inner_size);
		wlr_scene_node_set_position(&button->border->node, box.x, box.y);
		wlr_scene_node_set_position(&button->background->node,
			box.x + layout.button_border_width,
			box.y + layout.button_border_width);
		wlr_scene_node_set_position(&button->bitmap_node->node,
			box.x + layout.button_border_width,
			box.y + layout.button_border_width);
		struct wlr_buffer *button_bitmap = NULL;
		if (button->bitmap[0] == ':')
			button_bitmap = wtwm_render_builtin_title(button->bitmap,
				layout.button_inner_size, foreground);
		else {
			struct wtwm_xbm bitmap;
			wtwm_xbm_init(&bitmap);
			if (load_visual_xbm(toplevel->server, button->bitmap, &bitmap))
				button_bitmap = wtwm_render_xbm_title(&bitmap,
					layout.button_inner_size, foreground);
			wtwm_xbm_finish(&bitmap);
			if (button_bitmap == NULL)
				button_bitmap = wtwm_render_builtin_title(":question",
					layout.button_inner_size, foreground);
		}
		if (button_bitmap != NULL) {
			wlr_scene_buffer_set_buffer(button->bitmap_node, button_bitmap);
			wlr_buffer_drop(button_bitmap);
		}
	}
	int clipped_text_width = layout.title.width - layout.text.x;
	if (clipped_text_width > toplevel->title_text_width)
		clipped_text_width = toplevel->title_text_width;
	if (clipped_text_width < 0) clipped_text_width = 0;
	if (clipped_text_width > 0) {
		struct wlr_fbox text_source = {
			.width = clipped_text_width,
			.height = toplevel->title_text_height,
		};
		wlr_scene_buffer_set_source_box(toplevel->title_text, &text_source);
		wlr_scene_buffer_set_dest_size(toplevel->title_text, clipped_text_width,
			toplevel->title_text_height);
	}
	wlr_scene_node_set_enabled(&toplevel->title_text->node,
		toplevel->decorated && clipped_text_width > 0);
	wlr_scene_node_set_position(&toplevel->title_text->node,
		layout.text.x, layout.text.y);
	if (toplevel->content != NULL)
		wlr_scene_node_set_position(&toplevel->content->node,
			geometry.content_x, geometry.content_y);
	sync_toplevel_popups(toplevel);
}

static void set_decorated(struct toplevel *toplevel, bool enabled) {
	toplevel->decorated = enabled;
	if (toplevel->title == NULL) return;
	wlr_scene_node_set_enabled(&toplevel->frame->node, toplevel_has_frame(toplevel));
	wlr_scene_node_set_enabled(&toplevel->title_tree->node, enabled);
	wlr_scene_node_set_enabled(&toplevel->focus_mark->node, false);
	update_decoration(toplevel);
}

static struct toplevel *icon_manager_toplevel(struct server *server,
		uint64_t identity) {
	struct toplevel *toplevel;
	wl_list_for_each(toplevel, &server->toplevels, link)
		if (toplevel->icon_identity == identity) return toplevel;
	return NULL;
}

static const char *icon_manager_label(const struct toplevel *toplevel) {
	return toplevel->icon_name != NULL && toplevel->icon_name[0] != '\0' ?
		toplevel->icon_name : toplevel_title(toplevel);
}

static bool icon_manager_transient(const struct toplevel *toplevel) {
	return toplevel->xwayland != NULL ? toplevel->xwayland->parent != NULL :
		(toplevel->xdg != NULL && toplevel->xdg->parent != NULL);
}

static bool icon_manager_shows_toplevel(const struct toplevel *toplevel) {
	struct server *server = toplevel->server;
	if (server->config.no_icon_managers || icon_manager_transient(toplevel) ||
			(toplevel->xwayland != NULL &&
			toplevel->xwayland->override_redirect)) return false;
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	bool hidden = window_list_rule(&server->config,
		"IconManagerDontShow", &identity, NULL);
	bool shown = window_list_rule(&server->config,
		"IconManagerShow", &identity, NULL);
	return !hidden || shown;
}

static uint64_t icon_manager_for_toplevel(const struct toplevel *toplevel) {
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	for (unsigned pass = 0; pass < 3; ++pass)
		for (size_t i = 0; i < toplevel->server->config.icon_manager_count; ++i)
			if (icon_selector_matches(&identity,
					toplevel->server->config.icon_managers[i].window_name, pass)) {
				uint64_t candidate = (uint64_t)i + 2;
				if (wtwm_icon_manager_find(&toplevel->server->icon_managers,
						candidate) != NULL) return candidate;
			}
	return 1;
}

static const char *icon_manager_geometry(const struct server *server,
		uint64_t identity) {
	if (identity == 1) return server->config.icon_manager_geometry;
	size_t index = (size_t)(identity - 2);
	return index < server->config.icon_manager_count ?
		server->config.icon_managers[index].geometry : "";
}

static bool parse_manager_number(const char **cursor, long *value) {
	if (!isdigit((unsigned char)**cursor)) return false;
	errno = 0;
	char *end = NULL;
	long result = strtol(*cursor, &end, 10);
	if (errno != 0 || end == *cursor) return false;
	*cursor = end;
	*value = result;
	return true;
}

static void icon_manager_box(const struct server *server, uint64_t identity,
		int packed_width, int packed_height, int *x, int *y, int *width) {
	const char *cursor = icon_manager_geometry(server, identity);
	int requested_width = 150;
	long geometry_width = 0;
	long ignored_height = 0;
	long offset_x = 0;
	long offset_y = 0;
	bool negative_x = false;
	bool negative_y = false;
	if (cursor != NULL && *cursor == '=') ++cursor;
	if (cursor != NULL && parse_manager_number(&cursor, &geometry_width) &&
			(*cursor == 'x' || *cursor == 'X')) {
		++cursor;
		if (!parse_manager_number(&cursor, &ignored_height)) cursor = "";
		else if (geometry_width > 0 && geometry_width <= INT_MAX)
			requested_width = (int)geometry_width;
	}
	if (cursor != NULL && (*cursor == '+' || *cursor == '-')) {
		negative_x = *cursor++ == '-';
		if (!parse_manager_number(&cursor, &offset_x)) offset_x = 0;
		if (*cursor == '+' || *cursor == '-') {
			negative_y = *cursor++ == '-';
			if (!parse_manager_number(&cursor, &offset_y)) offset_y = 0;
		}
	}
	struct wlr_box layout = {0};
	wlr_output_layout_get_box(server->output_layout, NULL, &layout);
	if (layout.width <= 0) layout.width = 800;
	if (layout.height <= 0) layout.height = 600;
	*width = packed_width > 0 ? packed_width : requested_width;
	*x = negative_x ? layout.x + layout.width - *width - (int)offset_x :
		layout.x + (int)offset_x;
	*y = negative_y ? layout.y + layout.height - packed_height - (int)offset_y :
		layout.y + (int)offset_y;
}

static void clear_icon_manager_text_cache(struct toplevel *toplevel) {
	if (toplevel->icon_manager_text_buffer != NULL)
		wlr_buffer_drop(toplevel->icon_manager_text_buffer);
	toplevel->icon_manager_text_buffer = NULL;
	free(toplevel->icon_manager_text_label);
	toplevel->icon_manager_text_label = NULL;
	free(toplevel->icon_manager_text_font);
	toplevel->icon_manager_text_font = NULL;
	toplevel->icon_manager_text_width = 0;
	toplevel->icon_manager_text_height = 0;
}

static void clear_icon_manager_render_cache(struct toplevel *toplevel) {
	clear_icon_manager_text_cache(toplevel);
	if (toplevel->icon_manager_marker_buffer != NULL)
		wlr_buffer_drop(toplevel->icon_manager_marker_buffer);
	toplevel->icon_manager_marker_buffer = NULL;
	toplevel->icon_manager_marker_size = 0;
}

static struct wlr_buffer *cached_icon_manager_text(struct toplevel *toplevel,
		const char *label, const float color[4], int *width, int *height) {
	const char *font = toplevel->server->config.icon_manager_font;
	if (toplevel->icon_manager_text_buffer == NULL ||
			toplevel->icon_manager_text_label == NULL ||
			toplevel->icon_manager_text_font == NULL ||
			strcmp(toplevel->icon_manager_text_label, label) != 0 ||
			strcmp(toplevel->icon_manager_text_font, font) != 0 ||
			memcmp(toplevel->icon_manager_text_color, color,
				sizeof(toplevel->icon_manager_text_color)) != 0) {
		clear_icon_manager_text_cache(toplevel);
		toplevel->icon_manager_text_buffer = wtwm_render_text(label, font, color,
			&toplevel->icon_manager_text_width,
			&toplevel->icon_manager_text_height);
		if (toplevel->icon_manager_text_buffer != NULL) {
			toplevel->icon_manager_text_label = strdup(label);
			toplevel->icon_manager_text_font = strdup(font);
			memcpy(toplevel->icon_manager_text_color, color,
				sizeof(toplevel->icon_manager_text_color));
		}
	}
	*width = toplevel->icon_manager_text_width;
	*height = toplevel->icon_manager_text_height;
	return toplevel->icon_manager_text_buffer;
}

static struct wlr_buffer *cached_icon_manager_marker(struct toplevel *toplevel,
		int size, const float color[4]) {
	if (toplevel->icon_manager_marker_buffer == NULL ||
			toplevel->icon_manager_marker_size != size ||
			memcmp(toplevel->icon_manager_marker_color, color,
				sizeof(toplevel->icon_manager_marker_color)) != 0) {
		if (toplevel->icon_manager_marker_buffer != NULL)
			wlr_buffer_drop(toplevel->icon_manager_marker_buffer);
		toplevel->icon_manager_marker_buffer = wtwm_render_builtin_title(
			":iconify", size, color);
		toplevel->icon_manager_marker_size = size;
		memcpy(toplevel->icon_manager_marker_color, color,
			sizeof(toplevel->icon_manager_marker_color));
	}
	return toplevel->icon_manager_marker_buffer;
}

static void refresh_icon_managers(struct server *server) {
	for (size_t i = 0; i < server->icon_manager_view_count; ++i) {
		if (server->icon_manager_views[i].tree != NULL)
			wlr_scene_node_destroy(&server->icon_manager_views[i].tree->node);
	}
	memset(server->icon_manager_views, 0, sizeof(server->icon_manager_views));
	server->icon_manager_view_count = server->icon_managers.manager_count;
	if (server->icon_manager_tree == NULL) return;
	int font_height = 1;
	int font_ascent = 1;
	(void)wtwm_measure_font_metrics(server->config.icon_manager_font,
		&font_height, &font_ascent);
	int row_height = font_height + 10;
	if (row_height < 12) row_height = 12;
	for (size_t index = 0; index < server->icon_managers.manager_count; ++index) {
		const struct wtwm_icon_manager_model *manager =
			&server->icon_managers.managers[index];
		struct icon_manager_view *view = &server->icon_manager_views[index];
		view->identity = manager->identity;
		view->row_height = row_height;
		int requested_width = 150;
		int ignored_x = 0;
		int ignored_y = 0;
		icon_manager_box(server, manager->identity, 0, row_height,
			&ignored_x, &ignored_y, &requested_width);
		size_t columns = manager->current_columns > 0 ?
			manager->current_columns : 1;
		int packed_width = requested_width;
		if (manager->entry_count > 0 && columns < manager->columns)
			packed_width = requested_width * (int)columns / (int)manager->columns;
		if (packed_width < (int)columns) packed_width = (int)columns;
		view->height = (int)(manager->current_rows > 0 ? manager->current_rows : 1) *
			row_height;
		icon_manager_box(server, manager->identity, packed_width, view->height,
			&view->x, &view->y, &view->width);
		view->tree = wlr_scene_tree_create(server->icon_manager_tree);
		if (view->tree == NULL) continue;
		float foreground[4], background[4];
		configured_color(server, "IconManagerForeground", "black", NULL,
			foreground);
		configured_color(server, "IconManagerBackground", "white", NULL,
			background);
		wlr_scene_rect_create(view->tree, view->width, view->height, foreground);
		struct wlr_scene_rect *inside = wlr_scene_rect_create(view->tree,
			view->width > 2 ? view->width - 2 : 1,
			view->height > 2 ? view->height - 2 : 1, background);
		if (inside != NULL) wlr_scene_node_set_position(&inside->node, 1, 1);
		int cell_width = view->width / (int)columns;
		if (cell_width < 1) cell_width = 1;
		for (size_t position = 0; position < manager->entry_count; ++position) {
			const struct wtwm_icon_manager_entry *entry = wtwm_icon_manager_entry_at(
				&server->icon_managers, manager->identity, position);
			struct toplevel *toplevel = entry != NULL ?
				icon_manager_toplevel(server, entry->identity) : NULL;
			if (entry == NULL || toplevel == NULL) continue;
			struct wlr_scene_tree *row = wlr_scene_tree_create(view->tree);
			if (row == NULL) continue;
			row->node.data = toplevel;
			wlr_scene_node_set_position(&row->node,
				(int)entry->column * cell_width,
				(int)entry->row * row_height);
			float row_background[4], row_border[4], row_foreground[4];
			configured_color(server, "IconManagerBackground", "white", toplevel,
				row_background);
			configured_color(server, "IconManagerForeground", "black", toplevel,
				row_foreground);
			if (server->icon_managers.active_entry_identity == entry->identity)
				configured_color(server, "IconManagerHighlight", "black", toplevel,
					row_border);
			else memcpy(row_border, row_foreground, sizeof(row_border));
			wlr_scene_rect_create(row, cell_width, row_height, row_border);
			int inset = server->icon_manager_down_identity == entry->identity ? 2 : 1;
			struct wlr_scene_rect *row_inside = wlr_scene_rect_create(row,
				cell_width > 2 * inset ? cell_width - 2 * inset : 1,
				row_height > 2 * inset ? row_height - 2 * inset : 1,
				row_background);
			if (row_inside != NULL)
				wlr_scene_node_set_position(&row_inside->node, inset, inset);
			int button_size = row_height - 6;
			if (button_size < 4) button_size = 4;
			if (toplevel->iconified) {
				struct wlr_buffer *marker = cached_icon_manager_marker(toplevel,
					button_size, row_foreground);
				if (marker != NULL) {
					struct wlr_scene_buffer *button = wlr_scene_buffer_create(row,
						marker);
					if (button != NULL)
						wlr_scene_node_set_position(&button->node, 3, 3);
				}
			}
			int text_width = 0;
			int text_height = 0;
			struct wlr_buffer *text = cached_icon_manager_text(toplevel,
				entry->label, row_foreground,
				&text_width, &text_height);
			if (text != NULL) {
				struct wlr_scene_buffer *node = wlr_scene_buffer_create(row, text);
				if (node != NULL) {
					int text_x = button_size + 6;
					int available = cell_width - text_x - 2;
					if (available > 0 && available < text_width) {
						struct wlr_fbox source = {.width = available,
							.height = text_height};
						wlr_scene_buffer_set_source_box(node, &source);
						wlr_scene_buffer_set_dest_size(node, available, text_height);
					}
					wlr_scene_node_set_position(&node->node, text_x,
						(row_height - font_height) / 2 + font_ascent - font_ascent);
				}
			}
		}
		wlr_scene_node_set_position(&view->tree->node, view->x, view->y);
		wlr_scene_node_set_enabled(&view->tree->node,
			manager->visible && manager->entry_count > 0);
		if (manager->visible) wlr_scene_node_raise_to_top(&view->tree->node);
	}
}

static void initialize_icon_managers(struct server *server) {
	wtwm_icon_manager_state_init(&server->icon_managers);
	if (server->config.no_icon_managers) return;
	size_t columns = server->config.icon_manager_columns > 0 ?
		(size_t)server->config.icon_manager_columns : 1;
	if (columns > WTWM_ICON_MANAGER_MAX_ENTRIES)
		columns = WTWM_ICON_MANAGER_MAX_ENTRIES;
	(void)wtwm_icon_manager_add(&server->icon_managers, 1, "TWM Icons",
		columns, server->config.sort_icon_manager,
		server->config.show_icon_manager);
	(void)wtwm_icon_manager_set_case_sensitive(&server->icon_managers, 1,
		server->config.case_sensitive);
	for (size_t i = 0; i < server->config.icon_manager_count &&
			server->icon_managers.manager_count < WTWM_ICON_MANAGER_MAX_MANAGERS;
			++i) {
		columns = server->config.icon_managers[i].columns > 0 ?
			(size_t)server->config.icon_managers[i].columns : 1;
		if (columns > WTWM_ICON_MANAGER_MAX_ENTRIES)
			columns = WTWM_ICON_MANAGER_MAX_ENTRIES;
		uint64_t identity = (uint64_t)i + 2;
		(void)wtwm_icon_manager_add(&server->icon_managers, identity,
			server->config.icon_managers[i].window_name, columns,
			server->config.sort_icon_manager, true);
		(void)wtwm_icon_manager_set_case_sensitive(&server->icon_managers,
			identity, server->config.case_sensitive);
	}
	refresh_icon_managers(server);
}

static void remove_icon_manager_toplevel(struct toplevel *toplevel) {
	if (toplevel->icon_manager_identity == 0) return;
	(void)wtwm_icon_manager_entry_remove(&toplevel->server->icon_managers,
		toplevel->icon_identity);
	toplevel->icon_manager_identity = 0;
	refresh_icon_managers(toplevel->server);
}

static void sync_icon_manager_toplevel(struct toplevel *toplevel) {
	if (!toplevel->mapped || !icon_manager_shows_toplevel(toplevel)) {
		remove_icon_manager_toplevel(toplevel);
		return;
	}
	uint64_t manager_identity = icon_manager_for_toplevel(toplevel);
	const char *label = icon_manager_label(toplevel);
	const struct wtwm_icon_manager_entry *entry = wtwm_icon_manager_entry_find(
		&toplevel->server->icon_managers, toplevel->icon_identity);
	if (entry == NULL) {
		if (wtwm_icon_manager_entry_add(&toplevel->server->icon_managers,
				manager_identity, toplevel->icon_identity, label) !=
				WTWM_ICON_MANAGER_APPLIED) return;
	} else {
		(void)wtwm_icon_manager_entry_update(&toplevel->server->icon_managers,
			toplevel->icon_identity, manager_identity, label);
	}
	toplevel->icon_manager_identity = manager_identity;
	refresh_icon_managers(toplevel->server);
}

static void reserve_icon_manager_toplevel(struct toplevel *toplevel) {
	if (toplevel->icon_manager_identity != 0 ||
			!icon_manager_shows_toplevel(toplevel)) return;
	uint64_t manager_identity = icon_manager_for_toplevel(toplevel);
	if (wtwm_icon_manager_entry_add(&toplevel->server->icon_managers,
			manager_identity, toplevel->icon_identity,
			icon_manager_label(toplevel)) != WTWM_ICON_MANAGER_APPLIED) return;
	toplevel->icon_manager_identity = manager_identity;
}

static bool icon_selector_matches(const struct wtwm_client_identity *identity,
		const char *selector, unsigned int pass) {
	const char *value = NULL;
	if (identity->name != NULL || identity->resource_name != NULL ||
			identity->resource_class != NULL) {
		if (pass == 0) value = identity->name;
		else if (pass == 1) value = identity->resource_name;
		else if (pass == 2) value = identity->resource_class;
	} else {
		if (pass == 0) value = identity->title;
		else if (pass == 1) value = identity->app_id;
	}
	return value != NULL && strcmp(value, selector) == 0;
}

static const char *configured_icon_bitmap(const struct toplevel *toplevel) {
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	for (unsigned int pass = 0; pass < 3; ++pass)
		for (size_t i = 0; i < toplevel->server->config.icon_count; ++i)
			if (icon_selector_matches(&identity,
					toplevel->server->config.icons[i].window_name, pass))
				return toplevel->server->config.icons[i].bitmap;
	return NULL;
}

static bool create_icon_scene(struct toplevel *toplevel) {
	if (toplevel->icon_tree != NULL) return true;
	float border[4], background[4], foreground[4];
	configured_color(toplevel->server, "IconBorderColor", "black", toplevel,
		border);
	configured_color(toplevel->server, "IconBackground", "white", toplevel,
		background);
	configured_color(toplevel->server, "IconForeground", "black", toplevel,
		foreground);
	const char *label = toplevel->icon_name != NULL &&
		toplevel->icon_name[0] != '\0' ? toplevel->icon_name :
		toplevel_title(toplevel);
	int text_width = 0;
	int text_height = 0;
	struct wlr_buffer *text = wtwm_render_text(label,
		toplevel->server->config.icon_font, foreground, &text_width, &text_height);
	struct wtwm_xbm bitmap;
	wtwm_xbm_init(&bitmap);
	const char *bitmap_name = configured_icon_bitmap(toplevel);
	bool has_bitmap = false;
	bool has_client_bitmap = false;
	bool has_wm_hints_bitmap = false;
	strcpy(toplevel->icon_source, "none");
	if (toplevel->server->config.force_icons && bitmap_name != NULL &&
			load_visual_xbm(toplevel->server, bitmap_name, &bitmap)) {
		has_bitmap = true;
		strcpy(toplevel->icon_source, "configured");
	}
	bool has_client_icon_window = !has_bitmap &&
		toplevel->wm_hints_icon_window_width > 0 &&
		toplevel->wm_hints_icon_window_height > 0;
	if (has_client_icon_window) {
		strcpy(toplevel->icon_source, "icon_window");
		toplevel->icon_width = (int)toplevel->wm_hints_icon_window_width;
		toplevel->icon_height = (int)toplevel->wm_hints_icon_window_height;
		toplevel->icon_tree = wlr_scene_tree_create(toplevel->server->view_tree);
		if (toplevel->icon_tree == NULL) {
			if (text != NULL) wlr_buffer_drop(text);
			wtwm_xbm_finish(&bitmap);
			return false;
		}
		toplevel->icon_tree->node.data = toplevel;
		toplevel->icon_background = wlr_scene_rect_create(toplevel->icon_tree,
			toplevel->icon_width, toplevel->icon_height, background);
		if (toplevel->icon_background == NULL) {
			wlr_scene_node_destroy(&toplevel->icon_tree->node);
			toplevel->icon_tree = NULL;
			if (text != NULL) wlr_buffer_drop(text);
			wtwm_xbm_finish(&bitmap);
			return false;
		}
		struct wlr_buffer *image = NULL;
		if (toplevel->wm_hints_icon_bits != NULL)
			image = wtwm_render_pattern((int)toplevel->wm_hints_icon_width,
				(int)toplevel->wm_hints_icon_height,
				toplevel->wm_hints_icon_bits, toplevel->wm_hints_icon_width,
				toplevel->wm_hints_icon_height, foreground, background);
		else if (toplevel->net_wm_icon_pixels != NULL)
			image = wtwm_render_argb_icon((int)toplevel->net_wm_icon_width,
				(int)toplevel->net_wm_icon_height,
				toplevel->net_wm_icon_pixels);
		if (image != NULL) {
			toplevel->icon_bitmap = wlr_scene_buffer_create(toplevel->icon_tree,
				image);
			if (toplevel->icon_bitmap != NULL)
				wlr_scene_buffer_set_dest_size(toplevel->icon_bitmap,
					toplevel->icon_width, toplevel->icon_height);
			wlr_buffer_drop(image);
		}
		if (text != NULL) wlr_buffer_drop(text);
		wtwm_xbm_finish(&bitmap);
		wlr_scene_node_set_enabled(&toplevel->icon_tree->node, false);
		return true;
	}
	if (!has_bitmap && toplevel->wm_hints_icon_bits != NULL) {
		has_wm_hints_bitmap = true;
		strcpy(toplevel->icon_source, "wm_hints");
	}
	if (!has_bitmap && !has_wm_hints_bitmap &&
			toplevel->net_wm_icon_pixels != NULL) {
		has_client_bitmap = true;
		strcpy(toplevel->icon_source, "client");
	}
	if (!has_bitmap && !has_wm_hints_bitmap && !has_client_bitmap &&
			bitmap_name != NULL &&
			load_visual_xbm(toplevel->server, bitmap_name, &bitmap)) {
		has_bitmap = true;
		strcpy(toplevel->icon_source, "configured");
	}
	if (!has_bitmap && !has_wm_hints_bitmap && !has_client_bitmap &&
			toplevel->server->config.unknown_icon[0] != '\0' &&
			load_visual_xbm(toplevel->server,
				toplevel->server->config.unknown_icon, &bitmap)) {
		has_bitmap = true;
		strcpy(toplevel->icon_source, "unknown");
	}
	int bitmap_width = has_wm_hints_bitmap ?
		(int)toplevel->wm_hints_icon_width :
		(has_client_bitmap ? (int)toplevel->net_wm_icon_width :
		(has_bitmap ? (int)bitmap.width : 0));
	int bitmap_height = has_wm_hints_bitmap ?
		(int)toplevel->wm_hints_icon_height :
		(has_client_bitmap ? (int)toplevel->net_wm_icon_height :
		(has_bitmap ? (int)bitmap.height : 0));
	int inner_width = text_width + 6;
	if (inner_width < bitmap_width) inner_width = bitmap_width;
	if (inner_width < 1) inner_width = 1;
	int font_height = 1;
	int font_ascent = 1;
	(void)wtwm_measure_font_metrics(toplevel->server->config.icon_font,
		&font_height, &font_ascent);
	if (font_height < 1) font_height = text_height > 0 ? text_height : 1;
	int inner_height = bitmap_height + font_height + 4;
	int border_width = toplevel->server->config.icon_border_width;
	if (border_width < 0) border_width = 0;
	toplevel->icon_width = inner_width + 2 * border_width;
	toplevel->icon_height = inner_height + 2 * border_width;
	toplevel->icon_tree = wlr_scene_tree_create(toplevel->server->view_tree);
	if (toplevel->icon_tree == NULL) {
		if (text != NULL) wlr_buffer_drop(text);
		wtwm_xbm_finish(&bitmap);
		return false;
	}
	toplevel->icon_tree->node.data = toplevel;
	toplevel->icon_border = wlr_scene_rect_create(toplevel->icon_tree,
		toplevel->icon_width, toplevel->icon_height, border);
	toplevel->icon_background = wlr_scene_rect_create(toplevel->icon_tree,
		inner_width, inner_height, background);
	if (toplevel->icon_border == NULL || toplevel->icon_background == NULL) {
		wlr_scene_node_destroy(&toplevel->icon_tree->node);
		toplevel->icon_tree = NULL;
		if (text != NULL) wlr_buffer_drop(text);
		wtwm_xbm_finish(&bitmap);
		return false;
	}
	wlr_scene_node_set_position(&toplevel->icon_background->node, border_width,
		border_width);
	if (has_bitmap || has_wm_hints_bitmap || has_client_bitmap) {
		struct wlr_buffer *image = has_wm_hints_bitmap ?
			wtwm_render_pattern(bitmap_width, bitmap_height,
				toplevel->wm_hints_icon_bits,
				toplevel->wm_hints_icon_width,
				toplevel->wm_hints_icon_height, foreground, background) :
			(has_client_bitmap ?
			wtwm_render_argb_icon(bitmap_width, bitmap_height,
				toplevel->net_wm_icon_pixels) :
			wtwm_render_pattern(bitmap_width, bitmap_height,
				bitmap.data, bitmap.width, bitmap.height, foreground, background));
		if (image != NULL) {
			toplevel->icon_bitmap = wlr_scene_buffer_create(toplevel->icon_tree,
				image);
			if (toplevel->icon_bitmap != NULL)
				wlr_scene_node_set_position(&toplevel->icon_bitmap->node,
					border_width + (inner_width - bitmap_width) / 2, border_width);
			wlr_buffer_drop(image);
		}
	}
	if (text != NULL) {
		toplevel->icon_text = wlr_scene_buffer_create(toplevel->icon_tree, text);
		if (toplevel->icon_text != NULL)
			wlr_scene_node_set_position(&toplevel->icon_text->node,
				border_width + (inner_width - text_width) / 2,
				border_width + bitmap_height + font_height - font_ascent);
		wlr_buffer_drop(text);
	}
	wtwm_xbm_finish(&bitmap);
	wlr_scene_node_set_enabled(&toplevel->icon_tree->node, false);
	return true;
}

static void destroy_icon_scene(struct toplevel *toplevel) {
	if (toplevel->icon_region_allocated && toplevel->server->icon_layout != NULL)
		(void)wtwm_icon_layout_release(toplevel->server->icon_layout,
			toplevel->icon_identity);
	toplevel->icon_region_allocated = false;
	if (toplevel->icon_tree != NULL)
		wlr_scene_node_destroy(&toplevel->icon_tree->node);
	toplevel->icon_tree = NULL;
	toplevel->icon_border = NULL;
	toplevel->icon_background = NULL;
	toplevel->icon_bitmap = NULL;
	toplevel->icon_text = NULL;
}

static void place_toplevel_icon(struct toplevel *toplevel, int fallback_x,
		int fallback_y, bool use_fallback) {
	if (toplevel->xwayland != NULL && toplevel->xwayland->hints != NULL &&
			(toplevel->xwayland->hints->flags &
			XCB_ICCCM_WM_HINT_ICON_POSITION) != 0) {
		toplevel->icon_x = toplevel->xwayland->hints->icon_x;
		toplevel->icon_y = toplevel->xwayland->hints->icon_y;
		toplevel->icon_moved = false;
	} else if (toplevel->icon_moved) {
		int64_t center_x = (int64_t)toplevel->icon_x + toplevel->icon_width / 2;
		int64_t center_y = (int64_t)toplevel->icon_y + toplevel->icon_height / 2;
		bool inside = center_x >= INT_MIN && center_x <= INT_MAX &&
			center_y >= INT_MIN && center_y <= INT_MAX &&
			wtwm_icon_layout_contains_point(toplevel->server->icon_layout,
				(int)center_x, (int)center_y);
		if (inside) {
			struct wtwm_icon_layout_placement placement;
			if (wtwm_icon_layout_allocate(toplevel->server->icon_layout,
					toplevel->icon_identity, toplevel->icon_width,
					toplevel->icon_height, &placement) == WTWM_ICON_LAYOUT_OK) {
				toplevel->icon_region_allocated = true;
				toplevel->icon_moved = false;
				toplevel->icon_x = placement.x;
				toplevel->icon_y = placement.y;
			}
		}
	} else {
		if (toplevel->server->icon_layout != NULL) {
			struct wtwm_icon_layout_placement placement;
			if (wtwm_icon_layout_allocate(toplevel->server->icon_layout,
					toplevel->icon_identity, toplevel->icon_width,
					toplevel->icon_height, &placement) == WTWM_ICON_LAYOUT_OK) {
				toplevel->icon_region_allocated = true;
				toplevel->icon_x = placement.x;
				toplevel->icon_y = placement.y;
			} else if (use_fallback) {
				toplevel->icon_x = fallback_x;
				toplevel->icon_y = fallback_y;
			}
		} else if (use_fallback) {
			toplevel->icon_x = fallback_x;
			toplevel->icon_y = fallback_y;
		}
	}
	struct wlr_box layout = {0};
	wlr_output_layout_get_box(toplevel->server->output_layout, NULL, &layout);
	if (layout.width > 0 && layout.height > 0) {
		int64_t right = (int64_t)layout.x + layout.width;
		int64_t bottom = (int64_t)layout.y + layout.height;
		if ((int64_t)toplevel->icon_x > right)
			toplevel->icon_x = (int)(right - toplevel->icon_width);
		if ((int64_t)toplevel->icon_y > bottom)
			toplevel->icon_y = (int)(bottom - toplevel->icon_height);
	}
	wlr_scene_node_set_position(&toplevel->icon_tree->node,
		toplevel->icon_x, toplevel->icon_y);
}

static void rebuild_icon_layout(struct server *server) {
	struct toplevel *toplevel;
	wl_list_for_each(toplevel, &server->toplevels, link)
		toplevel->icon_region_allocated = false;
	wtwm_icon_layout_destroy(server->icon_layout);
	server->icon_layout = NULL;
	if (server->config.icon_region_count == 0) return;
	struct wlr_box layout = {0};
	wlr_output_layout_get_box(server->output_layout, NULL, &layout);
	if (layout.width <= 0 || layout.height <= 0) return;
	struct wtwm_icon_layout_region *regions = calloc(
		server->config.icon_region_count, sizeof(*regions));
	if (regions == NULL) return;
	size_t count = 0;
	for (size_t i = 0; i < server->config.icon_region_count; ++i) {
		struct wtwm_icon_layout_region region;
		if (!wtwm_icon_layout_region_from_config(&server->config.icon_regions[i],
				layout.width, layout.height, &region)) {
			wlr_log(WLR_ERROR, "invalid IconRegion geometry '%s'",
				server->config.icon_regions[i].geometry);
			continue;
		}
		region.x += layout.x;
		region.y += layout.y;
		regions[count++] = region;
	}
	server->icon_layout = wtwm_icon_layout_create(regions, count);
	free(regions);
	if (server->icon_layout == NULL) return;
	wl_list_for_each(toplevel, &server->toplevels, link) {
		if (!toplevel->iconified || toplevel->icon_tree == NULL) continue;
		place_toplevel_icon(toplevel, toplevel->icon_x, toplevel->icon_y, false);
	}
}

static void refresh_toplevel_icon(struct toplevel *toplevel) {
	bool recreate = toplevel->icon_tree != NULL;
	bool visible = toplevel->mapped && toplevel->tree != NULL &&
		toplevel->iconified && !toplevel->iconify_by_unmapping;
	if (!recreate && !visible) return;
	destroy_icon_scene(toplevel);
	if (!visible || !create_icon_scene(toplevel)) return;
	place_toplevel_icon(toplevel, toplevel->icon_x, toplevel->icon_y, false);
	wlr_scene_node_set_enabled(&toplevel->icon_tree->node, true);
}

static void icon_animation_outline(struct icon_animation *animation,
		const struct wtwm_interaction_box *box) {
	int width = box->width > 0 ? box->width : 1;
	int height = box->height > 0 ? box->height : 1;
	wlr_scene_rect_set_size(animation->top, width, 1);
	wlr_scene_rect_set_size(animation->bottom, width, 1);
	wlr_scene_rect_set_size(animation->left, 1, height);
	wlr_scene_rect_set_size(animation->right, 1, height);
	wlr_scene_node_set_position(&animation->top->node, box->x, box->y);
	wlr_scene_node_set_position(&animation->bottom->node,
		box->x, box->y + height - 1);
	wlr_scene_node_set_position(&animation->left->node, box->x, box->y);
	wlr_scene_node_set_position(&animation->right->node,
		box->x + width - 1, box->y);
}

static void finish_icon_animation(struct server *server) {
	if (server->icon_animation.timer != NULL)
		wl_event_source_remove(server->icon_animation.timer);
	if (server->icon_animation.tree != NULL)
		wlr_scene_node_destroy(&server->icon_animation.tree->node);
	memset(&server->icon_animation, 0, sizeof(server->icon_animation));
}

static int icon_animation_tick(void *data) {
	struct server *server = data;
	struct icon_animation *animation = &server->icon_animation;
	if (animation->tree == NULL || animation->steps == 0) return 0;
	if (animation->step < animation->steps) ++animation->step;
	int numerator = (int)animation->step;
	int denominator = (int)animation->steps;
	struct wtwm_interaction_box box = {
		.x = animation->from.x +
			(animation->to.x - animation->from.x) * numerator / denominator,
		.y = animation->from.y +
			(animation->to.y - animation->from.y) * numerator / denominator,
		.width = animation->from.width +
			(animation->to.width - animation->from.width) * numerator / denominator,
		.height = animation->from.height +
			(animation->to.height - animation->from.height) * numerator / denominator,
	};
	icon_animation_outline(animation, &box);
	if (animation->step == animation->steps) {
		finish_icon_animation(server);
		return 0;
	}
	wl_event_source_timer_update(animation->timer, (int)animation->interval_ms);
	return 0;
}

static void start_icon_animation(struct toplevel *toplevel, bool iconifying,
		const struct wtwm_interaction_box *window_box,
		const struct wtwm_interaction_box *icon_box) {
	struct server *server = toplevel->server;
	if (!server->config.zoom || server->config.zoom_count <= 0 ||
			icon_box == NULL) return;
	finish_icon_animation(server);
	struct icon_animation *animation = &server->icon_animation;
	animation->steps = (unsigned)server->config.zoom_count;
	animation->from = iconifying ? *window_box : *icon_box;
	animation->to = iconifying ? *icon_box : *window_box;
	animation->interval_ms = 16;
#ifdef WTWM_TEST_CONTROL
	if (server->test_control.animation_ms > 0) {
		animation->interval_ms = server->test_control.animation_ms /
			animation->steps;
		if (animation->interval_ms == 0) animation->interval_ms = 1;
	}
#endif
	animation->tree = wlr_scene_tree_create(server->overlay_tree);
	if (animation->tree == NULL) return;
	float color[4];
	configured_color(server, "DefaultForeground", "black", NULL, color);
	animation->top = wlr_scene_rect_create(animation->tree, 1, 1, color);
	animation->bottom = wlr_scene_rect_create(animation->tree, 1, 1, color);
	animation->left = wlr_scene_rect_create(animation->tree, 1, 1, color);
	animation->right = wlr_scene_rect_create(animation->tree, 1, 1, color);
	if (animation->top == NULL || animation->bottom == NULL ||
			animation->left == NULL || animation->right == NULL) {
		finish_icon_animation(server);
		return;
	}
	icon_animation_outline(animation, &animation->from);
	animation->timer = wl_event_loop_add_timer(
		wl_display_get_event_loop(server->display), icon_animation_tick, server);
	if (animation->timer == NULL) {
		finish_icon_animation(server);
		return;
	}
	wl_event_source_timer_update(animation->timer, (int)animation->interval_ms);
	test_trace_toplevel_event(toplevel, "animation", "icon");
}

static struct wlr_scene_node *toplevel_visible_node(struct toplevel *toplevel) {
	return toplevel->iconified && toplevel->icon_tree != NULL ?
		&toplevel->icon_tree->node : &toplevel->tree->node;
}

static void sync_toplevel_scene_stack(struct toplevel *toplevel) {
	struct wlr_scene_node *node = toplevel_visible_node(toplevel);
	if (toplevel->link.prev == &toplevel->server->toplevels) {
		wlr_scene_node_raise_to_top(node);
		return;
	}
	struct toplevel *above = wl_container_of(toplevel->link.prev, above, link);
	wlr_scene_node_place_below(node, toplevel_visible_node(above));
}

static void set_toplevel_iconified_one(struct toplevel *toplevel, bool iconified,
		bool group_member, int fallback_x, int fallback_y) {
	if (toplevel == NULL || !toplevel->mapped) return;
	if (toplevel->iconified == iconified) {
		if (group_member && iconified && toplevel->icon_tree != NULL)
			wlr_scene_node_set_enabled(&toplevel->icon_tree->node, false);
		return;
	}
	bool show_icon = !group_member && (!toplevel->iconify_by_unmapping ||
		icon_manager_transient(toplevel));
	bool had_icon = toplevel->icon_tree != NULL;
	if (iconified && show_icon &&
			!create_icon_scene(toplevel)) return;
	if (iconified && show_icon && toplevel->icon_tree != NULL)
		place_toplevel_icon(toplevel, fallback_x, fallback_y, !had_icon);
	if (iconified && toplevel->server->focus == toplevel) {
		toplevel->server->focus_root = true;
		clear_keyboard_focus(toplevel->server);
	}
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	struct wtwm_interaction_box window_box = {
		.x = toplevel->tree->node.x,
		.y = toplevel->tree->node.y,
		.width = geometry.outer_width,
		.height = geometry.outer_height,
	};
	struct wtwm_interaction_box icon_box = {
		.x = toplevel->icon_x,
		.y = toplevel->icon_y,
		.width = toplevel->icon_width,
		.height = toplevel->icon_height,
	};
	if (!group_member)
		start_icon_animation(toplevel, iconified, &window_box,
			show_icon && toplevel->icon_tree != NULL ? &icon_box : NULL);
	toplevel->iconified = iconified;
	wlr_scene_node_set_enabled(&toplevel->tree->node, !iconified);
	if (toplevel->icon_tree != NULL)
		wlr_scene_node_set_enabled(&toplevel->icon_tree->node,
			iconified && show_icon);
	if (!iconified && toplevel->icon_region_allocated &&
			toplevel->server->icon_layout != NULL) {
		(void)wtwm_icon_layout_release(toplevel->server->icon_layout,
			toplevel->icon_identity);
		toplevel->icon_region_allocated = false;
	}
	sync_toplevel_scene_stack(toplevel);
	suspend_toplevel(toplevel, iconified);
	/* Hidden scene nodes do not receive output frame callbacks.  Complete the
	 * pending Xwayland callback when minimizing so one iconified client cannot
	 * stall surface creation and updates for unrelated X11 windows. */
	if (iconified && toplevel->xwayland != NULL)
		finish_surface_frame(toplevel->xwayland->surface);
	refresh_icon_managers(toplevel->server);
	test_trace_toplevel_event(toplevel,
		iconified ? "iconify" : "deiconify", "icon");
}

static bool toplevel_is_transient_for(const struct toplevel *child,
		const struct toplevel *owner) {
	if (child == owner) return false;
	if (child->xwayland != NULL && owner->xwayland != NULL)
		return child->xwayland->parent == owner->xwayland;
	if (child->xdg != NULL && owner->xdg != NULL)
		return child->xdg->parent == owner->xdg;
	return false;
}

static void set_toplevel_iconified_at(struct toplevel *toplevel, bool iconified,
		int fallback_x, int fallback_y) {
	if (toplevel == NULL) return;
	struct toplevel *child;
	if (iconified) {
		wl_list_for_each(child, &toplevel->server->toplevels, link)
			if (toplevel_is_transient_for(child, toplevel))
				set_toplevel_iconified_one(child, true, true,
					fallback_x, fallback_y);
		set_toplevel_iconified_one(toplevel, true, false,
			fallback_x, fallback_y);
	} else {
		set_toplevel_iconified_one(toplevel, false, false,
			fallback_x, fallback_y);
		wl_list_for_each(child, &toplevel->server->toplevels, link)
			if (toplevel_is_transient_for(child, toplevel))
				set_toplevel_iconified_one(child, false, true,
					fallback_x, fallback_y);
	}
}

static void set_toplevel_iconified(struct toplevel *toplevel, bool iconified) {
	set_toplevel_iconified_at(toplevel, iconified, 0, 0);
}

static void set_focused_marker(struct server *server, struct toplevel *focused) {
	(void)focused;
	struct toplevel *item;
	wl_list_for_each(item, &server->toplevels, link) {
		if (item->focus_mark != NULL) update_decoration(item);
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

static bool xwayland_supports_protocol(const struct toplevel *toplevel,
		xcb_atom_t protocol) {
	if (toplevel->xwayland == NULL || protocol == XCB_ATOM_NONE) return false;
	for (size_t i = 0; i < toplevel->xwayland->protocols_len; ++i)
		if (toplevel->xwayland->protocols[i] == protocol) return true;
	return false;
}

static bool xwayland_input_hint_true(const struct toplevel *toplevel) {
	return toplevel->xwayland != NULL && toplevel->xwayland->hints != NULL &&
		toplevel->xwayland->hints->input;
}

static bool xwayland_accepts_input(const struct toplevel *toplevel) {
	return toplevel->xwayland != NULL &&
		(toplevel->xwayland->hints == NULL ||
		toplevel->xwayland->hints->input);
}

static void send_xwayland_take_focus(struct toplevel *toplevel, uint32_t time) {
	struct server *server = toplevel->server;
	if (!xwayland_supports_protocol(toplevel, server->atom_wm_take_focus)) return;
	xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(server->xwayland);
	if (connection == NULL) return;
	xcb_client_message_event_t event = {
		.response_type = XCB_CLIENT_MESSAGE,
		.format = 32,
		.sequence = 0,
		.window = toplevel->xwayland->window_id,
		.type = server->atom_wm_protocols,
	};
	event.data.data32[0] = server->atom_wm_take_focus;
	event.data.data32[1] = time;
	xcb_send_event(connection, false, event.window, XCB_EVENT_MASK_NO_EVENT,
		(const char *)&event);
	xcb_flush(connection);
	test_trace_toplevel_event(toplevel, "take_focus", "client");
}

static void set_xwayland_input_focus(struct server *server,
		struct toplevel *toplevel) {
	if (server->xwayland == NULL) return;
	xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(server->xwayland);
	if (connection == NULL) return;
	xcb_window_t focus = toplevel != NULL ? toplevel->xwayland->window_id :
		XCB_INPUT_FOCUS_POINTER_ROOT;
	/* Wayland input times aren't guaranteed to share the X server's timestamp
	 * domain. wlroots' XWM uses CurrentTime for the same X core request. */
	xcb_set_input_focus(connection, XCB_INPUT_FOCUS_POINTER_ROOT, focus,
		XCB_CURRENT_TIME);
	xcb_flush(connection);
}

static bool sync_xwayland_input_focus(struct server *server,
		struct toplevel *toplevel) {
	if (server->xwayland_input_focus == toplevel) return false;
	/* wlroots gates X11 selection transfers on its XWM focus record.  Keep
	 * that private bookkeeping aligned only with direct X input focus; the
	 * caller immediately reasserts wtwm's exact client/PointerRoot target. */
	if (toplevel != NULL) {
		wlr_xwayland_surface_activate(toplevel->xwayland, true);
	} else if (server->xwayland_input_focus != NULL) {
		wlr_xwayland_surface_activate(
			server->xwayland_input_focus->xwayland, false);
	}
	server->xwayland_input_focus = toplevel;
	return toplevel != NULL;
}

static void suspend_toplevel(struct toplevel *toplevel, bool suspended) {
	if (toplevel->xdg != NULL)
		wlr_xdg_toplevel_set_suspended(toplevel->xdg, suspended);
	else
		wlr_xwayland_surface_set_minimized(toplevel->xwayland, suspended);
}

static void focus_toplevel(struct toplevel *toplevel, bool set_input_focus,
		bool send_take_focus, const char *context) {
	if (toplevel == NULL || toplevel->iconified || !toplevel->mapped) return;
	struct server *server = toplevel->server;
	struct wlr_surface *surface = toplevel_surface(toplevel);
	if (surface == NULL || (toplevel->xwayland != NULL &&
			toplevel->xwayland->override_redirect)) return;
	struct toplevel *old = server->focus;
	bool changed = old != toplevel;
	if (changed && old != NULL) {
		if (old->xdg != NULL) wlr_xdg_toplevel_set_activated(old->xdg, false);
		test_trace_toplevel_event(old, "unfocus", "client");
	}
	server->focus = toplevel;
	if (toplevel->xdg != NULL) wlr_xdg_toplevel_set_activated(toplevel->xdg, true);
	set_focused_marker(server, toplevel);
	bool xwm_sent_take_focus = false;
	if (set_input_focus) {
		if (toplevel->xwayland != NULL) {
			xwm_sent_take_focus = sync_xwayland_input_focus(server, toplevel);
			set_xwayland_input_focus(server, toplevel);
		} else {
			sync_xwayland_input_focus(server, NULL);
			set_xwayland_input_focus(server, NULL);
		}
		struct wlr_keyboard *keyboard = wlr_seat_get_keyboard(server->seat);
		if (keyboard != NULL) {
			wlr_seat_keyboard_notify_enter(server->seat, surface, keyboard->keycodes,
				keyboard->num_keycodes, &keyboard->modifiers);
		}
	}
	if (send_take_focus && !xwm_sent_take_focus)
		send_xwayland_take_focus(toplevel, server->current_input_time_ms);
	if (changed) {
		if (strcmp(context, "client") == 0)
			test_trace_toplevel_event(toplevel, "focus", "client");
		else test_trace_toplevel_event(toplevel, "focus", context);
	}
}

static void clear_focus(struct server *server, bool clear_input_focus) {
	struct toplevel *old = server->focus;
	if (old != NULL) {
		if (old->xdg != NULL) wlr_xdg_toplevel_set_activated(old->xdg, false);
	}
	server->focus = NULL;
	if (clear_input_focus) {
		sync_xwayland_input_focus(server, NULL);
		set_xwayland_input_focus(server, NULL);
		wlr_seat_keyboard_clear_focus(server->seat);
	}
	set_focused_marker(server, NULL);
	if (old != NULL) test_trace_toplevel_event(old, "unfocus", "client");
}

static void clear_keyboard_focus(struct server *server) {
	clear_focus(server, true);
}

static void lower_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped) return;
	struct wlr_scene_node *node = toplevel_visible_node(toplevel);
	wlr_scene_node_lower_to_bottom(node);
	if (toplevel->xwayland != NULL && !toplevel->iconified)
		wlr_xwayland_surface_restack(toplevel->xwayland, NULL, XCB_STACK_MODE_BELOW);
	wl_list_remove(&toplevel->link);
	wl_list_insert(toplevel->server->toplevels.prev, &toplevel->link);
	if (toplevel->iconified)
		test_trace_toplevel_event(toplevel, "lower", "icon");
	else test_trace_toplevel_event(toplevel, "lower", "frame");
}

static void raise_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped) return;
	struct wlr_scene_node *node = toplevel_visible_node(toplevel);
	wlr_scene_node_raise_to_top(node);
	wl_list_remove(&toplevel->link);
	wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
	if (toplevel->xwayland != NULL && !toplevel->iconified)
		wlr_xwayland_surface_restack(toplevel->xwayland, NULL, XCB_STACK_MODE_ABOVE);
	if (toplevel->iconified)
		test_trace_toplevel_event(toplevel, "raise", "icon");
	else test_trace_toplevel_event(toplevel, "raise", "frame");
}

static void raise_toplevel_group(struct toplevel *toplevel) {
	if (toplevel == NULL) return;
	size_t child_count = 0;
	struct toplevel *child;
	wl_list_for_each(child, &toplevel->server->toplevels, link)
		if (toplevel_is_transient_for(child, toplevel)) ++child_count;
	struct toplevel **children = child_count > 0 ?
		calloc(child_count, sizeof(*children)) : NULL;
	if (child_count > 0 && children == NULL) {
		raise_toplevel(toplevel);
		return;
	}
	size_t index = 0;
	wl_list_for_each(child, &toplevel->server->toplevels, link)
		if (toplevel_is_transient_for(child, toplevel)) children[index++] = child;
	raise_toplevel(toplevel);
	for (size_t i = 0; i < child_count; ++i) raise_toplevel(children[i]);
	free(children);
}

static struct wtwm_stack_box toplevel_stack_box(const struct toplevel *toplevel) {
	if (toplevel->iconified) return (struct wtwm_stack_box){
		.x = toplevel->icon_x,
		.y = toplevel->icon_y,
		.width = toplevel->icon_width,
		.height = toplevel->icon_height,
		.visible = toplevel->mapped && toplevel->icon_tree != NULL,
	};
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	return (struct wtwm_stack_box){
		.x = toplevel->tree->node.x,
		.y = toplevel->tree->node.y,
		.width = geometry.outer_width,
		.height = geometry.outer_height,
		.visible = toplevel->mapped && !toplevel->placement_pending,
	};
}

static struct toplevel **stack_snapshot(struct server *server,
		struct wtwm_stack_box **boxes, size_t *count) {
	*boxes = NULL;
	*count = 0;
	struct toplevel *item;
	wl_list_for_each(item, &server->toplevels, link) ++*count;
	if (*count == 0) return NULL;
	struct toplevel **items = calloc(*count, sizeof(*items));
	*boxes = calloc(*count, sizeof(**boxes));
	if (items == NULL || *boxes == NULL) {
		free(items);
		free(*boxes);
		*boxes = NULL;
		*count = 0;
		return NULL;
	}
	size_t index = 0;
	wl_list_for_each(item, &server->toplevels, link) {
		items[index] = item;
		(*boxes)[index++] = toplevel_stack_box(item);
	}
	return items;
}

static void raise_lower_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped) return;
	struct wtwm_stack_box *boxes = NULL;
	size_t count = 0, index = 0;
	struct toplevel **items = stack_snapshot(toplevel->server, &boxes, &count);
	if (items == NULL) return;
	while (index < count && items[index] != toplevel) ++index;
	enum wtwm_stack_action action = wtwm_raise_lower_action(boxes, count, index,
		toplevel->server->last_interaction_moved);
	free(boxes);
	free(items);
	if (action == WTWM_STACK_RAISE) raise_toplevel(toplevel);
	else if (action == WTWM_STACK_LOWER) lower_toplevel(toplevel);
}

static void circulate_toplevels(struct server *server, bool up) {
	struct wtwm_stack_box *boxes = NULL;
	size_t count = 0;
	struct toplevel **items = stack_snapshot(server, &boxes, &count);
	if (items == NULL) return;
	ptrdiff_t candidate = up ? wtwm_circle_up_candidate(boxes, count) :
		wtwm_circle_down_candidate(boxes, count);
	free(boxes);
	if (candidate >= 0) {
		if (up) raise_toplevel(items[candidate]);
		else lower_toplevel(items[candidate]);
	}
	free(items);
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
	int outer_width = server->interaction.icon_move ?
		server->interaction.preview.width : geometry.outer_width;
	int outer_height = server->interaction.icon_move ?
		server->interaction.preview.height : geometry.outer_height;
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
		outer_width, 1);
	wlr_scene_rect_set_size(server->interaction.outline_bottom,
		outer_width, 1);
	wlr_scene_rect_set_size(server->interaction.outline_left,
		1, outer_height);
	wlr_scene_rect_set_size(server->interaction.outline_right,
		1, outer_height);
	wlr_scene_node_set_position(&server->interaction.outline_bottom->node,
		0, outer_height > 0 ? outer_height - 1 : 0);
	wlr_scene_node_set_position(&server->interaction.outline_right->node,
		outer_width > 0 ? outer_width - 1 : 0, 0);
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
	if (toplevel == NULL || !toplevel->mapped ||
			(toplevel->iconified && mode != CURSOR_MOVE)) return;
	struct server *server = toplevel->server;
	if (server->grabbed != NULL) return;
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	server->grabbed = toplevel;
	server->cursor_mode = mode;
	set_cursor_role(server, mode == CURSOR_MOVE ? "Move" : "Resize");
	server->last_interaction_moved = false;
	server->interaction = (struct interaction_session){
		.original = {
			.x = toplevel->iconified ? toplevel->icon_x : toplevel->tree->node.x,
			.y = toplevel->iconified ? toplevel->icon_y : toplevel->tree->node.y,
			.width = toplevel->iconified ? toplevel->icon_width : toplevel->width,
			.height = toplevel->iconified ? toplevel->icon_height : toplevel->height,
		},
		.preview = {
			.x = toplevel->iconified ? toplevel->icon_x : toplevel->tree->node.x,
			.y = toplevel->iconified ? toplevel->icon_y : toplevel->tree->node.y,
			.width = toplevel->iconified ? toplevel->icon_width : toplevel->width,
			.height = toplevel->iconified ? toplevel->icon_height : toplevel->height,
		},
		.pointer_start_x = server->cursor->x,
		.pointer_start_y = server->cursor->y,
		.force_move = force_move,
		.opaque_move = mode == CURSOR_MOVE && server->config.opaque_move,
		.started = server->config.move_delta <= 0,
		.intent = INTERACTION_DRAG,
		.icon_move = toplevel->iconified,
	};
	if (mode == CURSOR_MOVE) {
		uint32_t elapsed = time_msec - server->last_move_time_ms;
		if (wtwm_constrained_move_entry(server->config.constrained_move_time,
				elapsed)) {
			server->interaction.constrained_move = true;
			server->interaction.constrained_axis = WTWM_AXIS_NONE;
			double center_x = server->interaction.original.x +
				(toplevel->iconified ? server->interaction.original.width / 2.0 :
				geometry.border_width + geometry.frame_width / 2.0);
			double center_y = server->interaction.original.y +
				(toplevel->iconified ? server->interaction.original.height / 2.0 :
				geometry.border_width + geometry.frame_height / 2.0);
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

static void begin_menu_position(struct toplevel *toplevel, bool force_move,
		uint32_t time_msec) {
	begin_interactive(toplevel, CURSOR_MOVE, 0, force_move, false, time_msec);
	if (toplevel == NULL || toplevel->server->grabbed != toplevel) return;
	struct server *server = toplevel->server;
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	int width = server->interaction.icon_move ?
		server->interaction.original.width : geometry.frame_width;
	int height = server->interaction.icon_move ?
		server->interaction.original.height : geometry.frame_height;
	double center_x = server->interaction.original.x + width / 2.0;
	double center_y = server->interaction.original.y + height / 2.0;
	wlr_cursor_warp_closest(server->cursor, NULL, center_x, center_y);
	set_cursor_role(server, "Move");
	server->interaction.intent = INTERACTION_MENU_POSITION;
	server->interaction.pointer_start_x = server->cursor->x;
	server->interaction.pointer_start_y = server->cursor->y;
	server->interaction.grab_x = width / 2.0;
	server->interaction.grab_y = height / 2.0;
	server->interaction.started = server->config.move_delta <= 0;
	server->interaction.moved = false;
	server->interaction.preview = server->interaction.original;
	if (!server->interaction.opaque_move && server->interaction.started)
		show_interaction_outline(server);
}

static void finish_interactive(struct server *server, bool aborted) {
	struct toplevel *toplevel = server->grabbed;
	if (toplevel == NULL) return;
	if (server->interaction.intent == INTERACTION_INITIAL_POSITION ||
			server->interaction.intent == INTERACTION_INITIAL_CONFIRM ||
			server->interaction.intent == INTERACTION_INITIAL_RESIZE) {
		if (aborted) cancel_initial_placement(toplevel);
		else finish_initial_placement(server);
		return;
	}
	struct interaction_session interaction = server->interaction;
	enum cursor_mode mode = server->cursor_mode;
	clear_interaction_outline(server);
	if (aborted) {
		if (mode == CURSOR_MOVE && interaction.opaque_move) {
			if (interaction.icon_move) {
				toplevel->icon_x = interaction.original.x;
				toplevel->icon_y = interaction.original.y;
				wlr_scene_node_set_position(&toplevel->icon_tree->node,
					toplevel->icon_x, toplevel->icon_y);
			} else {
				set_toplevel_position(toplevel,
					interaction.original.x, interaction.original.y);
			}
		}
		test_trace_toplevel_event_at(toplevel, "abort",
			mode == CURSOR_MOVE ? "move" : "resize",
			interaction.original.x, interaction.original.y,
			interaction.original.width, interaction.original.height);
	} else if (mode == CURSOR_MOVE) {
		if (!interaction.opaque_move && interaction.started) {
			if (interaction.icon_move) {
				toplevel->icon_x = interaction.preview.x;
				toplevel->icon_y = interaction.preview.y;
				wlr_scene_node_set_position(&toplevel->icon_tree->node,
					toplevel->icon_x, toplevel->icon_y);
			} else {
				set_toplevel_position(toplevel,
					interaction.preview.x, interaction.preview.y);
			}
			if (!server->config.no_raise_on_move) raise_toplevel(toplevel);
		}
		if (interaction.icon_move && interaction.moved)
			toplevel->icon_moved = true;
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

static bool spawn_command(const char *command) {
	struct wtwm_command_plan plan;
	enum wtwm_command_result result = wtwm_command_plan_create(command, &plan);
	if (result == WTWM_COMMAND_EMPTY) return true;
	if (result != WTWM_COMMAND_OK) {
		wlr_log(WLR_ERROR, "cannot execute command: %s",
			wtwm_command_result_message(result));
		return false;
	}
	pid_t intermediate = fork();
	if (intermediate < 0) {
		wlr_log_errno(WLR_ERROR, "%s", "failed to fork command launcher");
		wtwm_command_plan_destroy(&plan);
		return false;
	}
	if (intermediate == 0) {
		pid_t child = fork();
		if (child < 0) _exit(EXIT_FAILURE);
		if (child == 0) {
			if (plan.mode == WTWM_COMMAND_DIRECT)
				execvp(plan.argv[0], plan.argv);
			else
				execl("/bin/sh", "/bin/sh", "-c", plan.command, (void *)NULL);
			_exit(127);
		}
		_exit(EXIT_SUCCESS);
	}
	wtwm_command_plan_destroy(&plan);

	int status;
	while (waitpid(intermediate, &status, 0) < 0) {
		if (errno == EINTR) continue;
		wlr_log_errno(WLR_ERROR, "%s", "failed to reap command launcher");
		return false;
	}
	if (!WIFEXITED(status) || WEXITSTATUS(status) != EXIT_SUCCESS) {
		wlr_log(WLR_ERROR, "%s", "failed to launch command");
		return false;
	}
	return true;
}

static void hide_menu(struct server *server) {
	struct menu_view current = server->menu;
	while (current.tree != NULL) {
		wlr_scene_node_destroy(&current.tree->node);
		free(current.rows);
		struct menu_view *parent = current.parent;
		if (parent == NULL) break;
		current = *parent;
		free(parent);
	}
	memset(&server->menu, 0, sizeof(server->menu));
	server->menu.selected = -1;
}

static bool pop_menu(struct server *server) {
	struct menu_view *parent = server->menu.parent;
	if (parent == NULL) return false;
	if (server->menu.tree != NULL)
		wlr_scene_node_destroy(&server->menu.tree->node);
	free(server->menu.rows);
	server->menu = *parent;
	free(parent);
	return true;
}

static unsigned menu_depth(const struct menu_view *menu) {
	unsigned depth = menu->tree != NULL ? 1 : 0;
	for (const struct menu_view *parent = menu->parent; parent != NULL;
			parent = parent->parent) ++depth;
	return depth;
}

static void menu_palettes(struct server *server, const struct wtwm_menu *menu,
		struct menu_row_palette *palettes) {
	struct wtwm_color normal_foreground = configured_color_result(server,
		"MenuForeground", "black", NULL);
	struct wtwm_color normal_background = configured_color_result(server,
		"MenuBackground", "white", NULL);
	struct wtwm_color title_foreground = configured_color_result(server,
		"MenuTitleForeground", "black", NULL);
	struct wtwm_color title_background = configured_color_result(server,
		"MenuTitleBackground", "white", NULL);
	bool root_highlight = server->color_mode == WTWM_COLOR_MODE_COLOR &&
		menu->foreground[0] != '\0';
	struct wtwm_color root_highlight_foreground = root_highlight ?
		color_result(server, menu->foreground) : (struct wtwm_color){0, 0, 0};
	struct wtwm_color root_highlight_background = root_highlight ?
		color_result(server, menu->background) : (struct wtwm_color){0, 0, 0};
	for (size_t i = 0; i < menu->item_count; ++i) {
		bool title = menu->items[i].action.type == WTWM_ACTION_TITLE;
		bool user = server->color_mode == WTWM_COLOR_MODE_COLOR &&
			menu->items[i].foreground[0] != '\0';
		palettes[i].foreground = user ?
			color_result(server, menu->items[i].foreground) :
			(title ? title_foreground : normal_foreground);
		palettes[i].background = user ?
			color_result(server, menu->items[i].background) :
			(title ? title_background : normal_background);
		palettes[i].highlight_foreground = root_highlight ?
			root_highlight_foreground : palettes[i].background;
		palettes[i].highlight_background = root_highlight ?
			root_highlight_background : palettes[i].foreground;
		palettes[i].user_colors = user;
	}
	if (server->color_mode != WTWM_COLOR_MODE_COLOR ||
			!server->config.interpolate_menu_colors) return;
	for (size_t start = 0; start < menu->item_count;) {
		while (start < menu->item_count && !palettes[start].user_colors) ++start;
		if (start == menu->item_count) break;
		size_t end = start + 1;
		while (end < menu->item_count && !palettes[end].user_colors) ++end;
		if (end == menu->item_count) break;
		unsigned steps = (unsigned)(end - start);
		for (size_t i = start + 1; i < end; ++i) {
			unsigned index = (unsigned)(i - start);
			palettes[i].foreground = wtwm_color_interpolate(
				palettes[start].foreground, palettes[end].foreground,
				index, steps);
			palettes[i].background = wtwm_color_interpolate(
				palettes[start].background, palettes[end].background,
				index, steps);
			palettes[i].highlight_background = palettes[i].foreground;
			palettes[i].highlight_foreground = palettes[i].background;
			palettes[i].user_colors = true;
		}
		start = end;
	}
}

static bool build_windows_menu(struct server *server) {
	free(server->windows_menu.items);
	free(server->windows_menu_targets);
	memset(&server->windows_menu, 0, sizeof(server->windows_menu));
	server->windows_menu_targets = NULL;
	size_t count = 0;
	struct toplevel *item;
	wl_list_for_each_reverse(item, &server->toplevels, link)
		if (item->mapped && !item->placement_pending) ++count;
	server->windows_menu.items = calloc(count + 1,
		sizeof(*server->windows_menu.items));
	server->windows_menu_targets = calloc(count + 1,
		sizeof(*server->windows_menu_targets));
	if (server->windows_menu.items == NULL ||
			server->windows_menu_targets == NULL) {
		free(server->windows_menu.items);
		free(server->windows_menu_targets);
		memset(&server->windows_menu, 0, sizeof(server->windows_menu));
		server->windows_menu_targets = NULL;
		return false;
	}
	(void)snprintf(server->windows_menu.name, sizeof(server->windows_menu.name),
		"%s", "TwmWindows");
	(void)snprintf(server->windows_menu.items[0].label,
		sizeof(server->windows_menu.items[0].label), "%s", "Twm Windows");
	server->windows_menu.items[0].action.type = WTWM_ACTION_TITLE;
	size_t index = 1;
	wl_list_for_each_reverse(item, &server->toplevels, link) {
		if (!item->mapped || item->placement_pending) continue;
		(void)snprintf(server->windows_menu.items[index].label,
			sizeof(server->windows_menu.items[index].label), "%s",
			toplevel_title(item));
		server->windows_menu.items[index].action.type = WTWM_ACTION_NOP;
		server->windows_menu_targets[index] = item;
		++index;
	}
	server->windows_menu.item_count = count + 1;
	return true;
}

static void show_menu_at(struct server *server, const char *name,
		struct toplevel *target, bool submenu, int requested_x, int requested_y) {
	const struct wtwm_menu *menu = NULL;
	if (strcmp(name, "TwmWindows") == 0 && build_windows_menu(server)) {
		menu = &server->windows_menu;
	} else {
		for (size_t i = 0; i < server->config.menu_count; ++i) {
			if (strcmp(server->config.menus[i].name, name) == 0) {
				menu = &server->config.menus[i];
				break;
			}
		}
	}
	if (menu == NULL || menu->item_count == 0) {
		wlr_log(WLR_ERROR, "menu '%s' is not defined", name);
		return;
	}
	if (submenu && (server->menu.tree == NULL || menu_depth(&server->menu) >= 10))
		return;
	int *widths = calloc(menu->item_count, sizeof(*widths));
	int *heights = calloc(menu->item_count, sizeof(*heights));
	struct menu_row_palette *palettes = calloc(menu->item_count,
		sizeof(*palettes));
	if (widths == NULL || heights == NULL || palettes == NULL) {
		free(widths); free(heights); free(palettes); return;
	}
	menu_palettes(server, menu, palettes);
	int content_width = 1;
	bool has_pull_entry = false;
	for (size_t i = 0; i < menu->item_count; ++i) {
		float color[4];
		wtwm_color_to_float(&palettes[i].foreground, color);
		struct wlr_buffer *measure = wtwm_render_text(menu->items[i].label,
			server->config.menu_font, color, &widths[i], &heights[i]);
		if (measure != NULL) wlr_buffer_drop(measure);
		if (widths[i] > content_width) content_width = widths[i];
		if (menu->items[i].action.type == WTWM_ACTION_MENU)
			has_pull_entry = true;
	}
	int font_height = 1;
	int font_ascent = 1;
	(void)wtwm_measure_font_metrics(server->config.menu_font, &font_height,
		&font_ascent);
	struct wtwm_visual_config visual = wtwm_visual_config_defaults();
	visual.menu_border_width = server->config.menu_border_width;
	visual.menu_shadows = !server->config.no_menu_shadows;
	struct wtwm_menu_layout layout;
	wtwm_menu_layout_compute(&visual, font_height, font_ascent, content_width,
		(unsigned int)menu->item_count, has_pull_entry, &layout);
	float border[4], shadow[4];
	configured_color(server, "MenuBorderColor", "black", NULL, border);
	configured_color(server, "MenuShadowColor", "black", NULL, shadow);
	struct wlr_scene_tree *tree = wlr_scene_tree_create(server->menu_tree);
	if (tree == NULL) {
		free(widths); free(heights); free(palettes); return;
	}
	if (layout.shadow_visible) {
		struct wlr_scene_rect *shadow_rect = wlr_scene_rect_create(tree,
			layout.shadow.width, layout.shadow.height, shadow);
		if (shadow_rect != NULL) wlr_scene_node_set_position(&shadow_rect->node,
			layout.shadow.x, layout.shadow.y);
	}
	wlr_scene_rect_create(tree, layout.outer.width, layout.outer.height, border);
	struct menu_row_view *rows = calloc(menu->item_count, sizeof(*rows));
	if (rows == NULL) {
		wlr_scene_node_destroy(&tree->node);
		free(widths); free(heights); free(palettes); return;
	}
	for (size_t i = 0; i < menu->item_count; ++i) {
		struct wtwm_visual_box row_box;
		(void)wtwm_menu_row_box(&layout, (unsigned int)i, &row_box);
		float normal_background[4], highlight_background[4];
		float normal_foreground[4], highlight_foreground[4];
		wtwm_color_to_float(&palettes[i].background, normal_background);
		wtwm_color_to_float(&palettes[i].highlight_background,
			highlight_background);
		wtwm_color_to_float(&palettes[i].foreground, normal_foreground);
		wtwm_color_to_float(&palettes[i].highlight_foreground,
			highlight_foreground);
		rows[i].normal_background = wlr_scene_rect_create(tree, row_box.width,
			row_box.height, normal_background);
		rows[i].highlight_background = wlr_scene_rect_create(tree, row_box.width,
			row_box.height, highlight_background);
		if (rows[i].normal_background != NULL)
			wlr_scene_node_set_position(&rows[i].normal_background->node,
				row_box.x, row_box.y);
		if (rows[i].highlight_background != NULL) {
			wlr_scene_node_set_position(&rows[i].highlight_background->node,
				row_box.x, row_box.y);
			wlr_scene_node_set_enabled(&rows[i].highlight_background->node, false);
		}
		struct wlr_buffer *normal = wtwm_render_text(menu->items[i].label,
			server->config.menu_font, normal_foreground, &widths[i], &heights[i]);
		int highlight_width = 0;
		int highlight_height = 0;
		struct wlr_buffer *highlight = wtwm_render_text(menu->items[i].label,
			server->config.menu_font, highlight_foreground, &highlight_width,
			&highlight_height);
		int text_x = 0;
		int baseline = 0;
		(void)wtwm_menu_text_origin(&layout, (unsigned int)i, widths[i],
			menu->items[i].action.type == WTWM_ACTION_TITLE, &text_x, &baseline);
		if (normal != NULL) {
			rows[i].normal_text = wlr_scene_buffer_create(tree, normal);
			if (rows[i].normal_text != NULL)
				wlr_scene_node_set_position(&rows[i].normal_text->node, text_x,
					baseline - font_ascent);
			wlr_buffer_drop(normal);
		}
		if (highlight != NULL) {
			rows[i].highlight_text = wlr_scene_buffer_create(tree, highlight);
			if (rows[i].highlight_text != NULL) {
				wlr_scene_node_set_position(&rows[i].highlight_text->node, text_x,
					baseline - font_ascent);
				wlr_scene_node_set_enabled(&rows[i].highlight_text->node, false);
			}
			wlr_buffer_drop(highlight);
		}
		if (menu->items[i].action.type == WTWM_ACTION_TITLE) {
			rows[i].separator_bottom = wlr_scene_rect_create(tree,
				row_box.width, 1, normal_foreground);
			if (rows[i].separator_bottom != NULL)
				wlr_scene_node_set_position(&rows[i].separator_bottom->node,
					row_box.x, row_box.y + row_box.height - 1);
			if (i != 0) {
				rows[i].separator_top = wlr_scene_rect_create(tree,
					row_box.width, 1, normal_foreground);
				if (rows[i].separator_top != NULL)
					wlr_scene_node_set_position(&rows[i].separator_top->node,
						row_box.x, row_box.y);
			}
		}
		if (menu->items[i].action.type == WTWM_ACTION_MENU) {
			int pull_size = font_height > 0 ? font_height : 1;
			struct wlr_buffer *pull = wtwm_render_builtin_title(":menu",
				pull_size, normal_foreground);
			struct wlr_buffer *pull_hi = wtwm_render_builtin_title(":menu",
				pull_size, highlight_foreground);
			int pull_x = layout.content.x + layout.content.width - pull_size - 5;
			int pull_y = row_box.y + (row_box.height - pull_size) / 2;
			if (pull != NULL) {
				rows[i].pull_normal = wlr_scene_buffer_create(tree, pull);
				if (rows[i].pull_normal != NULL)
					wlr_scene_node_set_position(&rows[i].pull_normal->node,
						pull_x, pull_y);
				wlr_buffer_drop(pull);
			}
			if (pull_hi != NULL) {
				rows[i].pull_highlight = wlr_scene_buffer_create(tree, pull_hi);
				if (rows[i].pull_highlight != NULL) {
					wlr_scene_node_set_position(&rows[i].pull_highlight->node,
						pull_x, pull_y);
					wlr_scene_node_set_enabled(&rows[i].pull_highlight->node, false);
				}
				wlr_buffer_drop(pull_hi);
			}
		}
	}
	free(widths); free(heights); free(palettes);
	struct wlr_box output = {0};
	wlr_output_layout_get_box(server->output_layout, NULL, &output);
	int menu_x = submenu ? requested_x : (int)server->cursor->x;
	int menu_y = submenu ? requested_y : (int)server->cursor->y;
	if (menu_x + layout.outer.width > output.x + output.width)
		menu_x = output.x + output.width - layout.outer.width;
	if (menu_y + layout.outer.height > output.y + output.height)
		menu_y = output.y + output.height - layout.outer.height;
	if (menu_x < output.x) menu_x = output.x;
	if (menu_y < output.y) menu_y = output.y;
	struct menu_view *parent = NULL;
	if (submenu) {
		parent = malloc(sizeof(*parent));
		if (parent == NULL) {
			wlr_scene_node_destroy(&tree->node);
			free(rows);
			return;
		}
		*parent = server->menu;
	} else {
		hide_menu(server);
	}
	server->menu = (struct menu_view){
		.parent = parent,
		.tree = tree,
		.rows = rows,
		.row_count = menu->item_count,
		.definition = menu,
		.target = target,
		.x = menu_x,
		.y = menu_y,
		.width = layout.outer.width,
		.height = layout.outer.height,
		.row_height = layout.row_height,
		.selected = -1,
	};
	wlr_scene_node_set_position(&tree->node, server->menu.x, server->menu.y);
}

static void show_menu(struct server *server, const char *name,
		struct toplevel *target) {
	show_menu_at(server, name, target, false, 0, 0);
}

static bool menu_contains(const struct menu_view *menu, double x, double y) {
	return menu->tree != NULL && x >= menu->x && x < menu->x + menu->width &&
		y >= menu->y && y < menu->y + menu->height;
}

static int menu_item_at(struct server *server) {
	if (server->menu.tree == NULL) return -1;
	int border = server->config.menu_border_width;
	if (border < 0) border = 0;
	int x = (int)server->cursor->x - server->menu.x;
	int y = (int)server->cursor->y - server->menu.y - border;
	if (x < border || x >= server->menu.width - border || y < 0) return -1;
	int item = y / server->menu.row_height;
	return item >= 0 && (size_t)item < server->menu.definition->item_count ? item : -1;
}

static void update_menu_selection(struct server *server) {
	int selected = menu_item_at(server);
	if (selected >= 0 && server->menu.definition->items[selected].action.type ==
			WTWM_ACTION_TITLE) selected = -1;
	for (size_t i = 0; i < server->menu.row_count; ++i) {
		bool active = selected >= 0 && (size_t)selected == i;
		struct menu_row_view *row = &server->menu.rows[i];
		if (row->normal_background != NULL)
			wlr_scene_node_set_enabled(&row->normal_background->node, !active);
		if (row->highlight_background != NULL)
			wlr_scene_node_set_enabled(&row->highlight_background->node, active);
		if (row->normal_text != NULL)
			wlr_scene_node_set_enabled(&row->normal_text->node, !active);
		if (row->highlight_text != NULL)
			wlr_scene_node_set_enabled(&row->highlight_text->node, active);
		if (row->pull_normal != NULL)
			wlr_scene_node_set_enabled(&row->pull_normal->node, !active);
		if (row->pull_highlight != NULL)
			wlr_scene_node_set_enabled(&row->pull_highlight->node, active);
	}
	server->menu.selected = selected;
	if (selected >= 0 &&
			server->menu.definition->items[selected].action.type == WTWM_ACTION_MENU &&
			server->cursor->x >= server->menu.x + server->menu.width / 2.0) {
		const struct wtwm_action *pull =
			&server->menu.definition->items[selected].action;
		show_menu_at(server, pull->argument, server->menu.target, true,
			server->menu.x + server->menu.width / 2,
			server->menu.y + server->config.menu_border_width +
				selected * server->menu.row_height);
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

static bool ring_bell(struct server *server) {
	if (server->xwayland == NULL) return false;
	xcb_connection_t *connection =
		wlr_xwayland_get_xwm_connection(server->xwayland);
	if (connection == NULL) return false;
	xcb_bell(connection, 0);
	xcb_flush(connection);
	return true;
}

static void delete_toplevel(struct toplevel *toplevel) {
	if (toplevel->xdg != NULL) {
		wlr_xdg_toplevel_send_close(toplevel->xdg);
		return;
	}
	if (!xwayland_supports_delete(toplevel)) {
		wlr_log(WLR_INFO, "X11 window 0x%08" PRIx32
			" does not advertise WM_DELETE_WINDOW", toplevel->xwayland->window_id);
		(void)ring_bell(toplevel->server);
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
		bool previous_from_key = server->action_from_key;
		server->action_from_key = continuation->from_key;
		execute_action(server, continuation->toplevel, action,
			continuation->context);
		server->action_from_key = previous_from_key;
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
	server->continuation.from_key = server->action_from_key;
	server->continuation.active = true;
	if (!push_action_frame(&server->continuation, function)) {
		memset(&server->continuation, 0, sizeof(server->continuation));
		return;
	}
	resume_action_continuation(server);
}

static void toggle_click_focus(struct server *server, struct toplevel *toplevel) {
	if (toplevel == NULL) return;
	enum wtwm_focus_toggle_result result = wtwm_focus_toggle(server->focus_root,
		server->focus == toplevel, toplevel->iconified);
	if (result == WTWM_FOCUS_POINTER_ROOT) {
		server->focus_root = true;
		clear_keyboard_focus(server);
	} else if (result == WTWM_FOCUS_CLICK_LOCKED) {
		server->focus_root = false;
		bool input = toplevel->xwayland == NULL ||
			xwayland_accepts_input(toplevel);
		focus_toplevel(toplevel, input, false, "client");
	}
}

static bool action_needs_toplevel(enum wtwm_action_type type) {
	switch (type) {
	case WTWM_ACTION_MOVE:
	case WTWM_ACTION_FORCEMOVE:
	case WTWM_ACTION_RESIZE:
	case WTWM_ACTION_RAISE:
	case WTWM_ACTION_LOWER:
	case WTWM_ACTION_RAISELOWER:
	case WTWM_ACTION_ICONIFY:
	case WTWM_ACTION_DEICONIFY:
	case WTWM_ACTION_FOCUS:
	case WTWM_ACTION_DESTROY:
	case WTWM_ACTION_DELETE:
	case WTWM_ACTION_WINREFRESH:
	case WTWM_ACTION_ZOOM:
	case WTWM_ACTION_HORIZOOM:
	case WTWM_ACTION_FULLZOOM:
	case WTWM_ACTION_LEFTZOOM:
	case WTWM_ACTION_RIGHTZOOM:
	case WTWM_ACTION_TOPZOOM:
	case WTWM_ACTION_BOTTOMZOOM:
	case WTWM_ACTION_AUTORAISE:
	case WTWM_ACTION_IDENTIFY:
	case WTWM_ACTION_SAVEYOURSELF:
		return true;
	default:
		return false;
	}
}

static void schedule_refresh(struct server *server) {
	struct output *output;
	wl_list_for_each(output, &server->outputs, link)
		wlr_output_schedule_frame(output->wlr);
}

static void apply_zoom(struct toplevel *toplevel,
		enum wtwm_action_type type) {
	if (toplevel == NULL) return;
	struct wlr_box layout = {0};
	wlr_output_layout_get_box(toplevel->server->output_layout, NULL, &layout);
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	struct wtwm_interaction_box output = {
		.x = layout.x,
		.y = layout.y,
		.width = layout.width,
		.height = layout.height,
	};
	struct wtwm_interaction_box current = {
		.x = toplevel->frame_x,
		.y = toplevel->frame_y,
		.width = toplevel->width,
		.height = toplevel->height,
	};
	struct wtwm_interaction_box next = wtwm_action_zoom(type, &output,
		geometry.outer_width - toplevel->width,
		geometry.outer_height - toplevel->height, &current, &toplevel->zoom);
	constrain_toplevel_size(toplevel, &next.width, &next.height);
	set_toplevel_box(toplevel, next.x, next.y, next.width, next.height);
	if (!toplevel->server->config.no_raise_on_resize) raise_toplevel(toplevel);
	test_trace_toplevel_event_at(toplevel, "commit", "zoom", next.x, next.y,
		next.width, next.height);
}

static void warp_to_toplevel(struct server *server, struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped || toplevel->placement_pending)
		return;
	if (toplevel->iconified) {
		if (!server->config.warp_unmapped) return;
		set_toplevel_iconified(toplevel, false);
	}
	if (!server->config.no_raise_on_warp) raise_toplevel(toplevel);
	server->focus_root = false;
	focus_toplevel(toplevel, toplevel->xwayland == NULL ||
		xwayland_accepts_input(toplevel), false, "client");
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	wlr_cursor_warp_closest(server->cursor, NULL,
		toplevel->frame_x + geometry.outer_width / 2.0,
		toplevel->frame_y + geometry.outer_height / 2.0);
	process_cursor_motion(server, server->current_input_time_ms);
}

static bool prefix_category_matches(const struct toplevel *toplevel,
		const char *selector, unsigned category) {
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	const char *value = category == 0 ?
		(identity.name != NULL ? identity.name : identity.title) :
		(category == 1 ? (identity.resource_name != NULL ? identity.resource_name :
		identity.app_id) : identity.resource_class);
	return value != NULL && strncmp(value, selector, strlen(selector)) == 0;
}

static void warp_to_name(struct server *server, const char *selector) {
	if (selector == NULL) return;
	for (unsigned category = 0; category < 3; ++category) {
		struct toplevel *item;
		wl_list_for_each(item, &server->toplevels, link) {
			if (prefix_category_matches(item, selector, category)) {
				warp_to_toplevel(server, item);
				return;
			}
		}
	}
}

static struct icon_manager_view *icon_manager_view_for(struct server *server,
		uint64_t identity) {
	for (size_t i = 0; i < server->icon_manager_view_count; ++i)
		if (server->icon_manager_views[i].identity == identity)
			return &server->icon_manager_views[i];
	return NULL;
}

static void activate_icon_manager_entry(struct server *server,
		uint64_t identity, bool warp) {
	const struct wtwm_icon_manager_entry *entry = wtwm_icon_manager_entry_find(
		&server->icon_managers, identity);
	if (entry == NULL) return;
	(void)wtwm_icon_manager_select(&server->icon_managers, identity);
	refresh_icon_managers(server);
	if (!warp) return;
	const struct wtwm_icon_manager_model *manager = wtwm_icon_manager_find(
		&server->icon_managers, entry->manager_identity);
	struct icon_manager_view *view = icon_manager_view_for(server,
		entry->manager_identity);
	if (manager == NULL) return;
	if (view == NULL || !manager->visible || manager->current_columns == 0) {
		struct toplevel *toplevel = icon_manager_toplevel(server, identity);
		if (toplevel == NULL) return;
		if (toplevel->iconified && toplevel->icon_tree != NULL)
			wlr_cursor_warp_closest(server->cursor, NULL,
				toplevel->icon_x + toplevel->icon_width / 2.0,
				toplevel->icon_y + toplevel->icon_height / 2.0);
		else {
			struct wtwm_frame_geometry geometry;
			toplevel_geometry(toplevel, &geometry);
			wlr_cursor_warp_closest(server->cursor, NULL,
				toplevel->frame_x + geometry.outer_width / 2.0,
				toplevel->frame_y + geometry.border_width +
					geometry.title_extent / 2.0);
		}
		process_cursor_motion(server, server->current_input_time_ms);
		return;
	}
	int cell_width = view->width / (int)manager->current_columns;
	wlr_cursor_warp_closest(server->cursor, NULL,
		view->x + (int)entry->column * cell_width + cell_width / 2.0,
		view->y + (int)entry->row * view->row_height + view->row_height / 2.0);
	process_cursor_motion(server, server->current_input_time_ms);
}

static void warp_to_icon_manager(struct server *server,
		struct toplevel *toplevel, const char *selector) {
	if (selector != NULL && selector[0] != '\0') {
		for (size_t i = 0; i < server->icon_managers.manager_count; ++i) {
			const struct wtwm_icon_manager_model *manager =
				&server->icon_managers.managers[i];
			if (!manager->visible) continue;
			for (size_t position = 0; position < manager->entry_count; ++position) {
				const struct wtwm_icon_manager_entry *entry =
					wtwm_icon_manager_entry_at(&server->icon_managers,
						manager->identity, position);
				if (entry != NULL && strncmp(entry->label, selector,
						strlen(selector)) == 0) {
					activate_icon_manager_entry(server, entry->identity, true);
					return;
				}
			}
		}
		return;
	}
	if (toplevel != NULL) {
		activate_icon_manager_entry(server, toplevel->icon_identity, true);
		return;
	}
	uint64_t identity = server->icon_managers.active_entry_identity;
	if (identity == 0) {
		const struct wtwm_icon_manager_model *manager = wtwm_icon_manager_find(
			&server->icon_managers, 1);
		if (manager != NULL) identity = manager->selected_entry_identity;
	}
	if (identity != 0) activate_icon_manager_entry(server, identity, true);
}

static uint64_t action_icon_manager_identity(struct server *server,
		const struct toplevel *toplevel) {
	if (toplevel != NULL && toplevel->icon_manager_identity != 0)
		return toplevel->icon_manager_identity;
	if (server->icon_managers.active_manager_identity != 0)
		return server->icon_managers.active_manager_identity;
	return 1;
}

static void move_icon_manager_selection(struct server *server,
		enum wtwm_action_type action) {
	uint64_t identity = 0;
	enum wtwm_icon_manager_result result = WTWM_ICON_MANAGER_INVALID;
	if (action == WTWM_ACTION_ICONMGR_NEXT)
		result = wtwm_icon_manager_next(&server->icon_managers, &identity);
	else if (action == WTWM_ACTION_ICONMGR_PREVIOUS)
		result = wtwm_icon_manager_previous(&server->icon_managers, &identity);
	else {
		enum wtwm_icon_manager_direction direction = WTWM_ICON_MANAGER_FORWARD;
		switch (action) {
		case WTWM_ACTION_ICONMGR_UP: direction = WTWM_ICON_MANAGER_UP; break;
		case WTWM_ACTION_ICONMGR_DOWN: direction = WTWM_ICON_MANAGER_DOWN; break;
		case WTWM_ACTION_ICONMGR_LEFT: direction = WTWM_ICON_MANAGER_LEFT; break;
		case WTWM_ACTION_ICONMGR_RIGHT: direction = WTWM_ICON_MANAGER_RIGHT; break;
		case WTWM_ACTION_ICONMGR_BACKWARD:
			direction = WTWM_ICON_MANAGER_BACKWARD; break;
		default: direction = WTWM_ICON_MANAGER_FORWARD; break;
		}
		result = wtwm_icon_manager_move(&server->icon_managers, direction,
			&identity);
	}
	if (result != WTWM_ICON_MANAGER_INVALID && identity != 0)
		activate_icon_manager_entry(server, identity, true);
	else if (action == WTWM_ACTION_ICONMGR_NEXT ||
			action == WTWM_ACTION_ICONMGR_PREVIOUS)
		(void)ring_bell(server);
}

static void warp_cycle(struct server *server, bool forward, bool ring_only) {
	size_t count = 0;
	struct toplevel *item;
	wl_list_for_each_reverse(item, &server->toplevels, link) {
		struct wtwm_client_identity identity = toplevel_identity(item);
		if (item->mapped && !item->placement_pending &&
				(!item->iconified || server->config.warp_unmapped) &&
				(!ring_only || wtwm_config_window_list_matches(&server->config,
				"WindowRing", &identity))) ++count;
	}
	if (count == 0) return;
	struct toplevel **items = calloc(count, sizeof(*items));
	if (items == NULL) return;
	size_t index = 0;
	int current = -1;
	wl_list_for_each_reverse(item, &server->toplevels, link) {
		struct wtwm_client_identity identity = toplevel_identity(item);
		if (!item->mapped || item->placement_pending ||
				(item->iconified && !server->config.warp_unmapped) ||
				(ring_only && !wtwm_config_window_list_matches(&server->config,
				"WindowRing", &identity))) continue;
		items[index] = item;
		if ((!ring_only && item == server->focus) ||
				(ring_only && item == server->ring_leader)) current = (int)index;
		++index;
	}
	int target = wtwm_action_cycle_index((int)count, current, forward);
	if (target >= 0) {
		warp_to_toplevel(server, items[target]);
		if (ring_only) server->ring_leader = items[target];
	}
	free(items);
}

static void warp_to_screen(struct server *server, const char *argument) {
	int count = (int)wl_list_length(&server->outputs);
	if (count <= 0) return;
	int current = 0;
	int index = 0;
	struct output *output;
	wl_list_for_each(output, &server->outputs, link) {
		struct wlr_box box = {0};
		wlr_output_layout_get_box(server->output_layout, output->wlr, &box);
		if (server->cursor->x >= box.x && server->cursor->x < box.x + box.width &&
				server->cursor->y >= box.y && server->cursor->y < box.y + box.height)
			current = index;
		++index;
	}
	int target = wtwm_action_screen_target(argument, current,
		server->previous_output_index, count);
	if (target < 0 || target == current) return;
	struct output *from = NULL;
	struct output *to = NULL;
	index = 0;
	wl_list_for_each(output, &server->outputs, link) {
		if (index == current) from = output;
		if (index == target) to = output;
		++index;
	}
	if (from == NULL || to == NULL) return;
	struct wlr_box from_box = {0};
	struct wlr_box to_box = {0};
	wlr_output_layout_get_box(server->output_layout, from->wlr, &from_box);
	wlr_output_layout_get_box(server->output_layout, to->wlr, &to_box);
	double x = to_box.x + (server->cursor->x - from_box.x);
	double y = to_box.y + (server->cursor->y - from_box.y);
	wlr_cursor_warp_closest(server->cursor, NULL, x, y);
	server->previous_output_index = current;
	process_cursor_motion(server, server->current_input_time_ms);
}

static bool send_save_yourself(struct toplevel *toplevel) {
	if (toplevel == NULL || toplevel->xwayland == NULL ||
			toplevel->server->atom_wm_save_yourself == XCB_ATOM_NONE ||
			!xwayland_supports_protocol(toplevel,
			toplevel->server->atom_wm_save_yourself)) return false;
	xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(
		toplevel->server->xwayland);
	if (connection == NULL) return false;
	xcb_client_message_event_t event = {
		.response_type = XCB_CLIENT_MESSAGE,
		.format = 32,
		.window = toplevel->xwayland->window_id,
		.type = toplevel->server->atom_wm_protocols,
	};
	event.data.data32[0] = toplevel->server->atom_wm_save_yourself;
	event.data.data32[1] = XCB_CURRENT_TIME;
	xcb_send_event(connection, false, toplevel->xwayland->window_id,
		XCB_EVENT_MASK_NO_EVENT, (const char *)&event);
	xcb_flush(connection);
	return true;
}

static bool xwayland_root(struct server *server,
		xcb_connection_t **connection, xcb_window_t *root) {
	if (server->xwayland == NULL || server->atom_cut_buffer0 == XCB_ATOM_NONE)
		return false;
	*connection = wlr_xwayland_get_xwm_connection(server->xwayland);
	if (*connection == NULL) return false;
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(
		xcb_get_setup(*connection));
	if (screens.rem == 0) return false;
	*root = screens.data->root;
	return true;
}

static bool store_cut_buffer(struct server *server, const char *bytes,
		size_t length) {
	xcb_connection_t *connection = NULL;
	xcb_window_t root = XCB_WINDOW_NONE;
	if (!xwayland_root(server, &connection, &root) || length > UINT32_MAX)
		return false;
	xcb_change_property(connection, XCB_PROP_MODE_REPLACE, root,
		server->atom_cut_buffer0, XCB_ATOM_STRING, 8, (uint32_t)length, bytes);
	xcb_flush(connection);
	return true;
}

static char *fetch_cut_buffer(struct server *server) {
	xcb_connection_t *connection = NULL;
	xcb_window_t root = XCB_WINDOW_NONE;
	if (!xwayland_root(server, &connection, &root)) return NULL;
	xcb_get_property_reply_t *reply = xcb_get_property_reply(connection,
		xcb_get_property(connection, false, root, server->atom_cut_buffer0,
			XCB_GET_PROPERTY_TYPE_ANY, 0, 1024), NULL);
	if (reply == NULL) return NULL;
	int length = xcb_get_property_value_length(reply);
	char *value = length > 0 ? malloc((size_t)length + 1) : NULL;
	if (value != NULL) {
		memcpy(value, xcb_get_property_value(reply), (size_t)length);
		value[length] = '\0';
	}
	free(reply);
	return value;
}

static char *expand_filename(const char *name) {
	if (name == NULL) return NULL;
	if (name[0] != '~') return strdup(name);
	const char *home = getenv("HOME");
	if (home == NULL) return NULL;
	size_t length = strlen(home) + strlen(name) + 2;
	char *expanded = malloc(length);
	if (expanded != NULL)
		(void)snprintf(expanded, length, "%s/%s", home, name + 1);
	return expanded;
}

static bool file_to_cut_buffer(struct server *server, const char *name) {
	char *expanded = expand_filename(name);
	if (expanded == NULL) return false;
	int descriptor = open(expanded, O_RDONLY);
	if (descriptor < 0) {
		wlr_log_errno(WLR_ERROR, "unable to open cut-buffer file %s", expanded);
		free(expanded);
		return false;
	}
	char bytes[4095];
	ssize_t count = read(descriptor, bytes, sizeof(bytes));
	close(descriptor);
	free(expanded);
	return count > 0 && store_cut_buffer(server, bytes, (size_t)count);
}

static void cut_text(struct server *server, const char *text) {
	if (text == NULL) text = "";
	size_t length = strlen(text);
	char *line = malloc(length + 2);
	if (line == NULL) return;
	memcpy(line, text, length);
	line[length] = '\n';
	line[length + 1] = '\0';
	if (!store_cut_buffer(server, line, length + 1))
		wlr_log(WLR_DEBUG, "%s",
			"f.cut has no native Wayland cut-buffer equivalent");
	free(line);
}

static void execute_action(struct server *server, struct toplevel *toplevel,
		const struct wtwm_action *action, uint32_t context) {
	/* Reference twm refuses f.resize from a key binding and on an icon before
	 * it enters the select-a-window path. */
	if (action->type == WTWM_ACTION_RESIZE &&
			(server->action_from_key || context == WTWM_CONTEXT_ICON)) return;
	if (toplevel == NULL && context == WTWM_CONTEXT_ROOT &&
			action_needs_toplevel(action->type)) {
		server->deferred_root_action = *action;
		server->deferred_root_action_active = true;
		return;
	}
	switch (action->type) {
	case WTWM_ACTION_NOP:
	case WTWM_ACTION_TITLE:
	case WTWM_ACTION_DELTASTOP:
		break;
	case WTWM_ACTION_BEEP:
		if (!ring_bell(server))
			wlr_log(WLR_DEBUG, "%s", "f.beep has no native Wayland bell protocol");
		break;
	case WTWM_ACTION_MOVE: case WTWM_ACTION_FORCEMOVE:
		begin_interactive(toplevel, CURSOR_MOVE, 0,
			action->type == WTWM_ACTION_FORCEMOVE,
			context == WTWM_CONTEXT_TITLE, server->current_input_time_ms); break;
	case WTWM_ACTION_RESIZE:
		begin_interactive(toplevel, CURSOR_RESIZE, 0, false,
			context == WTWM_CONTEXT_TITLE, server->current_input_time_ms); break;
	case WTWM_ACTION_RAISE:
		raise_toplevel(toplevel);
		break;
	case WTWM_ACTION_LOWER:
		lower_toplevel(toplevel); break;
	case WTWM_ACTION_RAISELOWER:
		if (!server->last_interaction_moved) raise_lower_toplevel(toplevel);
		break;
	case WTWM_ACTION_CIRCLEUP:
		circulate_toplevels(server, true);
		break;
	case WTWM_ACTION_CIRCLEDOWN:
		circulate_toplevels(server, false);
		break;
	case WTWM_ACTION_ICONIFY:
		if (toplevel != NULL && toplevel->iconified) {
			set_toplevel_iconified(toplevel, false);
			if (!server->config.no_raise_on_deiconify)
				raise_toplevel_group(toplevel);
		} else {
			set_toplevel_iconified_at(toplevel, true,
				(int)server->cursor->x - 5, (int)server->cursor->y - 5);
		}
		break;
	case WTWM_ACTION_DEICONIFY:
		if (toplevel) {
			set_toplevel_iconified(toplevel, false);
			if (!server->config.no_raise_on_deiconify)
				raise_toplevel_group(toplevel);
		}
		break;
	case WTWM_ACTION_FOCUS:
		toggle_click_focus(server, toplevel);
		break;
	case WTWM_ACTION_UNFOCUS:
		server->focus_root = true;
		clear_keyboard_focus(server); break;
	case WTWM_ACTION_DELETE:
		if (toplevel) delete_toplevel(toplevel);
		break;
	case WTWM_ACTION_DESTROY:
		if (toplevel) destroy_toplevel_client(toplevel);
		break;
	case WTWM_ACTION_EXEC:
		spawn_command(action->argument); break;
	case WTWM_ACTION_MENU:
		/* Pointer routes intercept F_MENU before ExecuteFunction. */
		break;
	case WTWM_ACTION_FUNCTION: start_action_function(server, toplevel,
		find_function(server, action->argument), context); break;
	case WTWM_ACTION_REFRESH:
	case WTWM_ACTION_WINREFRESH:
		schedule_refresh(server); break;
	case WTWM_ACTION_ZOOM:
	case WTWM_ACTION_HORIZOOM:
	case WTWM_ACTION_FULLZOOM:
	case WTWM_ACTION_LEFTZOOM:
	case WTWM_ACTION_RIGHTZOOM:
	case WTWM_ACTION_TOPZOOM:
	case WTWM_ACTION_BOTTOMZOOM:
		apply_zoom(toplevel, action->type); break;
	case WTWM_ACTION_WARPNEXT:
		warp_cycle(server, true, false); break;
	case WTWM_ACTION_WARPPREV:
		warp_cycle(server, false, false); break;
	case WTWM_ACTION_WARPTO:
		warp_to_name(server, action->argument); break;
	case WTWM_ACTION_WARPRING:
		warp_cycle(server, strcmp(action->argument, "next") == 0, true); break;
	case WTWM_ACTION_WARPTOSCREEN:
		warp_to_screen(server, action->argument); break;
	case WTWM_ACTION_WARPTOICONMGR:
		warp_to_icon_manager(server, toplevel, action->argument); break;
	case WTWM_ACTION_AUTORAISE:
		if (toplevel != NULL) toplevel->auto_raise = !toplevel->auto_raise;
		break;
	case WTWM_ACTION_ICONMGR_UP:
	case WTWM_ACTION_ICONMGR_DOWN:
	case WTWM_ACTION_ICONMGR_LEFT:
	case WTWM_ACTION_ICONMGR_RIGHT:
	case WTWM_ACTION_ICONMGR_FORWARD:
	case WTWM_ACTION_ICONMGR_BACKWARD:
	case WTWM_ACTION_ICONMGR_NEXT:
	case WTWM_ACTION_ICONMGR_PREVIOUS:
		move_icon_manager_selection(server, action->type); break;
	case WTWM_ACTION_ICONMGR_SHOW:
		(void)wtwm_icon_manager_set_visible(&server->icon_managers,
			action_icon_manager_identity(server, toplevel), true);
		refresh_icon_managers(server); break;
	case WTWM_ACTION_ICONMGR_HIDE:
		(void)wtwm_icon_manager_set_visible(&server->icon_managers,
			action_icon_manager_identity(server, toplevel), false);
		refresh_icon_managers(server); break;
	case WTWM_ACTION_ICONMGR_SORT:
		(void)wtwm_icon_manager_sort(&server->icon_managers,
			action_icon_manager_identity(server, toplevel));
		refresh_icon_managers(server); break;
	case WTWM_ACTION_IDENTIFY:
		wlr_log(WLR_INFO, "window: title='%s' type=%s",
			toplevel_title(toplevel), toplevel->xwayland != NULL ? "X11" : "Wayland");
		break;
	case WTWM_ACTION_VERSION:
		wlr_log(WLR_INFO, "%s", "wtwm 0.1.0 (twm 1.0.13.1 compatibility)");
		break;
	case WTWM_ACTION_PRIORITY:
		wlr_log(WLR_DEBUG, "%s",
			"f.priority is inactive without the X Sync priority extension");
		break;
	case WTWM_ACTION_STARTWM:
		if (spawn_command(action->argument)) wl_display_terminate(server->display);
		break;
	case WTWM_ACTION_SAVEYOURSELF:
		if (!send_save_yourself(toplevel)) {
			wlr_log(WLR_DEBUG, "%s",
				"f.saveyourself requires X11 WM_SAVE_YOURSELF support");
			(void)ring_bell(server);
		}
		break;
	case WTWM_ACTION_CUT:
		cut_text(server, action->argument); break;
	case WTWM_ACTION_CUTFILE: {
		char *filename = fetch_cut_buffer(server);
		if (filename != NULL) {
			filename[strcspn(filename, " \t\r\n")] = '\0';
			if (filename[0] != '\0') (void)file_to_cut_buffer(server, filename);
			free(filename);
		}
		break;
	}
	case WTWM_ACTION_FILE:
		(void)file_to_cut_buffer(server, action->argument); break;
	case WTWM_ACTION_COLORMAP:
		wlr_log(WLR_DEBUG, "%s",
			"Xwayland owns installed colormaps; f.colormap is a verified no-op");
		break;
	case WTWM_ACTION_RESTART:
		server->restart_requested = true;
		wl_display_terminate(server->display);
		break;
	case WTWM_ACTION_QUIT: wl_display_terminate(server->display); break;
	case WTWM_ACTION_UNSUPPORTED:
		wlr_log(WLR_ERROR, "unsupported action escaped parser: %s", action->name);
		break;
	}
}

static void execute_pointer_action(struct server *server,
		struct toplevel *toplevel, const struct wtwm_action *action,
		uint32_t context) {
	if (action->type == WTWM_ACTION_MENU)
		show_menu(server, action->argument, toplevel);
	else
		execute_action(server, toplevel, action, context);
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
	static const struct {
		const char *name;
		uint32_t modifier;
	} xkb_modifiers[] = {
		{"Mod1", WTWM_MOD_META1},
		{"Mod2", WTWM_MOD_META2},
		{"Mod3", WTWM_MOD_META3},
		{"Mod4", WTWM_MOD_META4},
		{"Mod5", WTWM_MOD_META5},
	};
	for (size_t i = 0; i < sizeof(xkb_modifiers) / sizeof(xkb_modifiers[0]); ++i) {
		if (xkb_state_mod_name_is_active(keyboard->xkb_state,
				xkb_modifiers[i].name, XKB_STATE_MODS_EFFECTIVE) > 0)
			mods |= xkb_modifiers[i].modifier;
	}
	return mods;
}

static const char *binding_context_name(uint32_t context) {
	switch (context) {
	case WTWM_CONTEXT_ROOT: return "root";
	case WTWM_CONTEXT_WINDOW: return "window";
	case WTWM_CONTEXT_TITLE: return "title";
	case WTWM_CONTEXT_ICON: return "icon";
	case WTWM_CONTEXT_FRAME: return "frame";
	case WTWM_CONTEXT_ICONMGR: return "iconmgr";
	default: return "none";
	}
}

static bool dispatch_binding(struct server *server, enum wtwm_binding_type type,
	unsigned button, const char *key, uint32_t context, struct toplevel *toplevel) {
	uint32_t modifiers = current_modifiers(server);
	uint32_t used = wtwm_bindings_used_modifiers(server->config.bindings,
		server->config.binding_count);
	if (type == WTWM_BINDING_KEY) {
		/* C_NAME is one independent key/modifier slot.  Its selector is applied
		 * to every managed client, by title then resource/app-id then class. */
		const struct wtwm_binding *named = NULL;
		for (size_t i = server->config.binding_count; i > 0; --i) {
			const struct wtwm_binding *candidate = &server->config.bindings[i - 1];
			if (candidate->type == type && candidate->window_name[0] != '\0' &&
					key != NULL && strcmp(candidate->key, key) == 0 &&
					candidate->modifiers == (modifiers & used)) {
				named = candidate;
				break;
			}
		}
		if (named != NULL) {
			size_t selector_length = strlen(named->window_name);
			size_t client_count = 0;
			struct toplevel *item;
			wl_list_for_each(item, &server->toplevels, link) ++client_count;
			struct toplevel **clients = client_count == 0 ? NULL :
				calloc(client_count, sizeof(*clients));
			if (client_count != 0 && clients == NULL) return false;
			size_t client_index = 0;
			wl_list_for_each(item, &server->toplevels, link)
				clients[client_index++] = item;
			for (unsigned category = 0; category < 3; ++category) {
				bool matched = false;
				for (client_index = 0; client_index < client_count; ++client_index) {
					item = clients[client_index];
					if (!item->mapped || item->placement_pending) continue;
					struct wtwm_client_identity identity = toplevel_identity(item);
					const char *value = category == 0 ?
						(identity.name != NULL ? identity.name : identity.title) :
						(category == 1 ? (identity.resource_name != NULL ?
						identity.resource_name : identity.app_id) : identity.resource_class);
					if (value == NULL || strncmp(value, named->window_name,
							selector_length) != 0) continue;
					test_trace_toplevel_event(item, "binding", "frame");
					bool previous_from_key = server->action_from_key;
					server->action_from_key = true;
					execute_action(server, item, &named->action, WTWM_CONTEXT_FRAME);
					server->action_from_key = previous_from_key;
					matched = true;
				}
				if (matched) {
					free(clients);
					return true;
				}
			}
			free(clients);
		}
	}
	struct wtwm_binding_trigger trigger = {
		.type = type,
		.button = button,
		.key = key,
		.modifiers = modifiers,
		.context = context,
		.client = NULL,
	};
	const struct wtwm_binding *binding = wtwm_bindings_select(
		server->config.bindings, server->config.binding_count, &trigger);
	if (binding == NULL) return false;
	if (toplevel != NULL)
		test_trace_toplevel_event(toplevel, "binding",
			binding_context_name(context));
	bool previous_from_key = server->action_from_key;
	server->action_from_key = type == WTWM_BINDING_KEY;
	if (type == WTWM_BINDING_BUTTON)
		execute_pointer_action(server, toplevel, &binding->action, context);
	else
		execute_action(server, toplevel, &binding->action, context);
	server->action_from_key = previous_from_key;
	return true;
}

static bool scene_node_descends_from(struct wlr_scene_node *node,
		struct wlr_scene_tree *ancestor) {
	while (node != NULL) {
		if (node == &ancestor->node) return true;
		struct wlr_scene_tree *parent = node->parent;
		node = parent != NULL ? &parent->node : NULL;
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
	for (size_t i = 0; i < server->icon_manager_view_count; ++i) {
		struct icon_manager_view *view = &server->icon_manager_views[i];
		if (view->tree == NULL ||
				!scene_node_descends_from(leaf, view->tree)) continue;
		hit.toplevel = toplevel_from_scene_tree(tree);
		hit.context = WTWM_CONTEXT_ICONMGR;
		return hit;
	}
	hit.toplevel = toplevel_from_scene_tree(tree);
	if (hit.toplevel == NULL) return hit;
	hit.context = WTWM_CONTEXT_FRAME;
	if (hit.toplevel->icon_tree != NULL &&
			(tree == hit.toplevel->icon_tree ||
			leaf == &hit.toplevel->icon_background->node)) {
		hit.context = WTWM_CONTEXT_ICON;
		return hit;
	}
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
	if (hit.toplevel->title && (tree == hit.toplevel->title_tree ||
		leaf == &hit.toplevel->title->node ||
		leaf == &hit.toplevel->focus_mark->node ||
		leaf == &hit.toplevel->title_text->node)) {
		hit.context = WTWM_CONTEXT_TITLE;
		for (size_t i = 0; i < hit.toplevel->title_button_count; ++i) {
			struct title_button_view *button = &hit.toplevel->title_buttons[i];
			if (leaf == &button->border->node ||
					leaf == &button->background->node ||
					leaf == &button->bitmap_node->node) {
				hit.on_title_button = true;
				hit.title_button_index = i;
				break;
			}
		}
	}
	if (hit.toplevel->xwayland != NULL &&
			hit.toplevel->xwayland->override_redirect) hit.toplevel = NULL;
	return hit;
}

static bool toplevel_supports_take_focus(const struct toplevel *toplevel) {
	return xwayland_supports_protocol(toplevel,
		toplevel->server->atom_wm_take_focus);
}

static void update_pointer_toplevel(struct server *server,
		const struct hit_result *hit) {
	struct toplevel *entered = hit->toplevel;
	uint32_t previous_context = server->pointer_context;
	if (entered == server->pointer_toplevel) {
		if (entered != NULL && hit->context == WTWM_CONTEXT_ICONMGR &&
				previous_context != WTWM_CONTEXT_ICONMGR) {
			activate_icon_manager_entry(server, entered->icon_identity, false);
			if (server->focus_root && !entered->iconified)
				focus_toplevel(entered, entered->xwayland == NULL ||
					xwayland_accepts_input(entered), false, "iconmgr");
		}
		else if (previous_context == WTWM_CONTEXT_ICONMGR &&
				hit->context != WTWM_CONTEXT_ICONMGR) {
			server->icon_managers.active_manager_identity = 0;
			server->icon_managers.active_entry_identity = 0;
			refresh_icon_managers(server);
		}
		server->pointer_context = hit->context;
		return;
	}
	struct toplevel *left = server->pointer_toplevel;
	server->pointer_toplevel = entered;
	server->pointer_context = hit->context;
	if (previous_context == WTWM_CONTEXT_ICONMGR) {
		server->icon_managers.active_manager_identity = 0;
		server->icon_managers.active_entry_identity = 0;
		refresh_icon_managers(server);
	}
	if (server->focus_root && left != NULL && server->focus == left) {
		struct wtwm_focus_leave_result result = wtwm_focus_leave(
			&(struct wtwm_focus_leave_input){
				.focus_root = true,
				.surface = WTWM_FOCUS_SURFACE_FRAME,
				.title_focus = !server->config.no_title_focus,
				.take_focus = toplevel_supports_take_focus(left),
			});
		if (result.deactivate)
			clear_focus(server, result.set_pointer_root);
	}
	if (entered == NULL) return;
	if (hit->context == WTWM_CONTEXT_ICONMGR) {
		activate_icon_manager_entry(server, entered->icon_identity, false);
	}
	if (server->focus_root && !entered->iconified) {
		struct wtwm_focus_enter_input input = {
			.focus_root = true,
			/* A root-to-client/title transition crosses the enclosing frame
			 * first in twm's X event hierarchy. */
			.surface = WTWM_FOCUS_SURFACE_FRAME,
			.title_focus = !server->config.no_title_focus,
			.has_title = entered->decorated,
			.global_no_titlebar = server->config.no_title,
			.input_hint = entered->xwayland == NULL ||
				xwayland_input_hint_true(entered),
			.take_focus = toplevel_supports_take_focus(entered),
		};
		struct wtwm_focus_enter_result result = wtwm_focus_enter(&input);
		if (result.activate)
			focus_toplevel(entered, result.set_input_focus,
				result.send_take_focus, "frame");
	}
	if (entered->auto_raise) raise_toplevel(entered);
}

static void process_cursor_motion(struct server *server, uint32_t time_msec) {
	server->current_input_time_ms = time_msec;
	if (server->cursor_mode == CURSOR_MOVE &&
			server->interaction.intent == INTERACTION_INITIAL_CONFIRM) return;
	if (server->cursor_mode == CURSOR_MOVE &&
			server->interaction.intent == INTERACTION_INITIAL_POSITION) {
		struct interaction_session *interaction = &server->interaction;
		struct wtwm_frame_geometry geometry;
		toplevel_geometry(server->grabbed, &geometry);
		struct wlr_box output_box = {0};
		wlr_output_layout_get_box(server->output_layout, NULL, &output_box);
		struct wtwm_placement_area area = {
			.x = output_box.x,
			.y = output_box.y,
			.width = output_box.width > 0 ? output_box.width : 1,
			.height = output_box.height > 0 ? output_box.height : 1,
		};
		int x = 0, y = 0;
		wtwm_placement_prompt_position(&area, server->config.dont_move_off,
			geometry.outer_width, geometry.outer_height,
			(int)server->cursor->x, (int)server->cursor->y, &x, &y);
		interaction->moved = interaction->moved ||
			x != interaction->preview.x || y != interaction->preview.y;
		interaction->preview.x = x;
		interaction->preview.y = y;
		show_interaction_outline(server);
		return;
	}
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
				struct wtwm_frame_geometry geometry = {0};
				if (!interaction->icon_move)
					toplevel_geometry(server->grabbed, &geometry);
				int width = interaction->icon_move ?
					interaction->original.width : geometry.outer_width;
				int height = interaction->icon_move ?
					interaction->original.height : geometry.outer_height;
				interaction->constrained_axis = wtwm_constrained_move_axis(
					width, height,
					(int)server->cursor->x - interaction->original.x,
					(int)server->cursor->y - interaction->original.y);
			}
			if (interaction->constrained_axis == WTWM_AXIS_NONE) return;
			if (interaction->constrained_axis == WTWM_AXIS_HORIZONTAL)
				y = interaction->original.y;
			else
				x = interaction->original.x;
		}
		struct wtwm_frame_geometry geometry = {0};
		if (!interaction->icon_move)
			toplevel_geometry(server->grabbed, &geometry);
		int width = interaction->icon_move ?
			interaction->original.width : geometry.outer_width;
		int height = interaction->icon_move ?
			interaction->original.height : geometry.outer_height;
		if (server->config.dont_move_off) {
			struct wlr_box output_box = {0};
			wlr_output_layout_get_box(server->output_layout, NULL, &output_box);
			x -= output_box.x;
			y -= output_box.y;
			wtwm_clamp_move(output_box.width, output_box.height,
				width, height,
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
			if (interaction->icon_move) {
				server->grabbed->icon_x = x;
				server->grabbed->icon_y = y;
				wlr_scene_node_set_position(&server->grabbed->icon_tree->node, x, y);
			} else {
				set_toplevel_position(server->grabbed, x, y);
			}
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
		while (!menu_contains(&server->menu, server->cursor->x,
				server->cursor->y) && server->menu.parent != NULL &&
				menu_contains(server->menu.parent, server->cursor->x,
					server->cursor->y))
			(void)pop_menu(server);
		update_menu_selection(server);
		set_cursor_role(server, "Menu");
		wlr_seat_pointer_clear_focus(server->seat);
		return;
	}
	struct hit_result hit = desktop_at(server, server->cursor->x, server->cursor->y);
	update_pointer_toplevel(server, &hit);
	if (hit.surface != NULL) {
		wlr_seat_pointer_notify_enter(server->seat, hit.surface, hit.sx, hit.sy);
		wlr_seat_pointer_notify_motion(server->seat, time_msec, hit.sx, hit.sy);
	} else {
		const char *role = hit.on_title_button ? "Button" :
			(hit.context == WTWM_CONTEXT_TITLE ? "Title" :
			(hit.context == WTWM_CONTEXT_ICON ? "Icon" : "Frame"));
		set_cursor_role(server, role);
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

static void begin_initial_resize(struct server *server) {
	struct toplevel *toplevel = server->grabbed;
	if (toplevel == NULL) return;
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	server->interaction.intent = INTERACTION_INITIAL_RESIZE;
	server->cursor_mode = CURSOR_RESIZE;
	server->interaction.original = server->interaction.preview;
	server->interaction.resize_edges = WTWM_RESIZE_EDGE_NONE;
	server->interaction.resize_offset_x = 0;
	server->interaction.resize_offset_y = 0;
	double center_x = server->interaction.preview.x + geometry.outer_width / 2.0;
	double center_y = server->interaction.preview.y + geometry.outer_height / 2.0;
	wlr_cursor_warp_closest(server->cursor, NULL, center_x, center_y);
	set_cursor_role(server, "Resize");
	server->interaction.pointer_start_x = server->cursor->x;
	server->interaction.pointer_start_y = server->cursor->y;
	show_interaction_outline(server);
}

static void fill_initial_placement(struct server *server) {
	struct toplevel *toplevel = server->grabbed;
	if (toplevel == NULL) return;
	struct wlr_box output_box = {0};
	wlr_output_layout_get_box(server->output_layout, NULL, &output_box);
	struct wtwm_placement_area area = {
		.x = output_box.x,
		.y = output_box.y,
		.width = output_box.width > 0 ? output_box.width : 1,
		.height = output_box.height > 0 ? output_box.height : 1,
	};
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	int width = toplevel->width;
	int height = toplevel->height;
	wtwm_placement_fill_size(&area, server->interaction.preview.x,
		server->interaction.preview.y,
		geometry.outer_width - toplevel->width,
		geometry.outer_height - toplevel->height, &width, &height);
	constrain_toplevel_size(toplevel, &width, &height);
	server->interaction.preview.width = width;
	server->interaction.preview.height = height;
	server->interaction.moved = true;
	show_interaction_outline(server);
	finish_initial_placement(server);
}

static bool handle_active_interaction_button(struct server *server,
		const struct wlr_pointer_button_event *event) {
	struct interaction_session *interaction = &server->interaction;
	if (interaction->intent == INTERACTION_MENU_POSITION) {
		if (event->state == WL_POINTER_BUTTON_STATE_PRESSED)
			finish_interactive(server, false);
		return true;
	}
	if (interaction->intent == INTERACTION_INITIAL_POSITION) {
		if (event->state != WL_POINTER_BUTTON_STATE_PRESSED) return true;
		switch (wtwm_placement_button(twm_button(event->button))) {
		case WTWM_PLACEMENT_BUTTON_CONFIRM:
			interaction->intent = INTERACTION_INITIAL_CONFIRM;
			interaction->confirming_button = event->button;
			test_trace_toplevel_event_at(server->grabbed, "confirm", "placement",
				interaction->preview.x, interaction->preview.y,
				interaction->preview.width, interaction->preview.height);
			break;
		case WTWM_PLACEMENT_BUTTON_RESIZE:
			begin_initial_resize(server);
			break;
		case WTWM_PLACEMENT_BUTTON_FILL:
			fill_initial_placement(server);
			break;
		case WTWM_PLACEMENT_BUTTON_IGNORE:
			break;
		}
		return true;
	}
	if (interaction->intent == INTERACTION_INITIAL_CONFIRM) {
		if (event->state == WL_POINTER_BUTTON_STATE_RELEASED &&
				event->button == interaction->confirming_button)
			finish_initial_placement(server);
		return true;
	}
	if (interaction->intent == INTERACTION_INITIAL_RESIZE) {
		if (event->state == WL_POINTER_BUTTON_STATE_RELEASED)
			finish_initial_placement(server);
		return true;
	}
	finish_interactive(server,
		event->state == WL_POINTER_BUTTON_STATE_PRESSED);
	return true;
}

static void cursor_button(struct wl_listener *listener, void *data) {
	struct server *server = wl_container_of(listener, server, cursor_button);
	struct wlr_pointer_button_event *event = data;
	server->current_input_time_ms = event->time_msec;
	if (server->grabbed != NULL) {
		handle_active_interaction_button(server, event);
		return;
	}
	if (event->state == WL_POINTER_BUTTON_STATE_PRESSED)
		server->last_interaction_moved = false;
	if (server->menu.tree != NULL) {
		if (event->state == WL_POINTER_BUTTON_STATE_PRESSED) {
			hide_menu(server);
			return;
		}
		if (event->state == WL_POINTER_BUTTON_STATE_RELEASED) {
			int selected = menu_item_at(server);
			struct wtwm_action action = {0};
			struct toplevel *target = server->menu.target;
			bool windows_menu = server->menu.definition == &server->windows_menu;
			if (windows_menu && selected > 0 &&
					(size_t)selected < server->windows_menu.item_count)
				target = server->windows_menu_targets[selected];
			bool activate = selected >= 0 &&
				server->menu.definition->items[selected].action.type != WTWM_ACTION_TITLE &&
				server->menu.definition->items[selected].action.type != WTWM_ACTION_MENU;
			if (activate) action = windows_menu ? server->config.window_function :
				server->menu.definition->items[selected].action;
			hide_menu(server);
			if (activate && windows_menu && action.type == WTWM_ACTION_NOP) {
				set_toplevel_iconified(target, false);
				raise_toplevel(target);
			} else if (activate && (action.type == WTWM_ACTION_MOVE ||
					action.type == WTWM_ACTION_FORCEMOVE)) {
				if (target != NULL) {
					begin_menu_position(target,
						action.type == WTWM_ACTION_FORCEMOVE,
						server->current_input_time_ms);
				} else {
					server->deferred_root_action = action;
					server->deferred_root_action_active = true;
				}
			} else if (activate) {
				execute_action(server, target, &action,
					target != NULL ? WTWM_CONTEXT_FRAME : WTWM_CONTEXT_ROOT);
			}
		}
		return;
	}
	struct hit_result hit = desktop_at(server, server->cursor->x, server->cursor->y);
	if (event->state == WL_POINTER_BUTTON_STATE_RELEASED) {
		if (server->icon_manager_down_identity != 0) {
			server->icon_manager_down_identity = 0;
			refresh_icon_managers(server);
		}
		if (hit.surface != NULL)
			wlr_seat_pointer_notify_button(server->seat, event->time_msec,
				event->button, event->state);
		return;
	}
	if (hit.context == WTWM_CONTEXT_ICONMGR && hit.toplevel != NULL) {
		server->icon_manager_down_identity = hit.toplevel->icon_identity;
		refresh_icon_managers(server);
	}
	if (server->deferred_root_action_active) {
		struct wtwm_action action = server->deferred_root_action;
		server->deferred_root_action_active = false;
		if (hit.toplevel != NULL)
			execute_action(server, hit.toplevel, &action, hit.context);
		return;
	}
	bool handled = false;
	if (hit.on_title_button && event->button == BTN_LEFT &&
			hit.title_button_index < hit.toplevel->title_button_count) {
		const struct wtwm_action *action =
			&hit.toplevel->title_buttons[hit.title_button_index].action;
		if (action->type == WTWM_ACTION_RESIZE) {
			begin_interactive(hit.toplevel, CURSOR_RESIZE, 0, false, true,
				event->time_msec);
		} else execute_pointer_action(server, hit.toplevel, action,
			WTWM_CONTEXT_TITLE);
		handled = true;
	}
	if (!handled) handled = dispatch_binding(server, WTWM_BINDING_BUTTON,
		twm_button(event->button), NULL, hit.context, hit.toplevel);
	if (!handled && hit.context == WTWM_CONTEXT_TITLE && event->button == BTN_LEFT) {
		begin_interactive(hit.toplevel, CURSOR_MOVE, 0, false, true,
			event->time_msec);
		handled = true;
	}
	if (!handled && server->config.default_function.type != WTWM_ACTION_NOP) {
		execute_pointer_action(server, hit.toplevel, &server->config.default_function,
			hit.context);
		handled = true;
	}
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
		if (server->pointer_context == WTWM_CONTEXT_ICONMGR &&
				server->pointer_toplevel != NULL) {
			toplevel = server->pointer_toplevel;
			context = WTWM_CONTEXT_ICONMGR;
		}
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
	if (server->seat->pointer_state.focused_client == event->seat_client) {
		server->cursor_role[0] = '\0';
		wlr_cursor_set_surface(server->cursor, event->surface, event->hotspot_x, event->hotspot_y);
	}
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

static void output_background_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct output *output = wl_container_of(listener, output,
		background_destroy);
	output->background = NULL;
	wl_list_remove(&output->background_destroy.link);
	wl_list_init(&output->background_destroy.link);
}

static void output_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct output *output = wl_container_of(listener, output, destroy);
	wl_list_remove(&output->frame.link);
	wl_list_remove(&output->request_state.link);
	wl_list_remove(&output->destroy.link);
	wl_list_remove(&output->link);
	if (output->background != NULL)
		wlr_scene_node_destroy(&output->background->node);
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
	struct wlr_box box = {0};
	wlr_output_layout_get_box(server->output_layout, wlr_output, &box);
	float background[4];
	configured_color(server, "DefaultBackground", "white", NULL, background);
	output->background = wlr_scene_rect_create(&server->scene->tree,
		box.width, box.height, background);
	if (output->background != NULL) {
		wlr_scene_node_set_position(&output->background->node, box.x, box.y);
		wlr_scene_node_lower_to_bottom(&output->background->node);
		output->background_destroy.notify = output_background_destroy;
		wl_signal_add(&output->background->node.events.destroy,
			&output->background_destroy);
	}
	rebuild_icon_layout(server);
	refresh_icon_managers(server);
}

static void update_toplevel_metadata(struct toplevel *toplevel,
	bool title_changed);

static void server_placement_area(struct server *server,
		struct wtwm_placement_area *area) {
	struct wlr_box box = {0};
	wlr_output_layout_get_box(server->output_layout, NULL, &box);
	area->x = box.x;
	area->y = box.y;
	area->width = box.width > 0 ? box.width : 1;
	area->height = box.height > 0 ? box.height : 1;
}

static void server_max_window_size(struct server *server,
		const struct wtwm_placement_area *area, int *width, int *height) {
	if (server->config.max_window_size_set) {
		*width = server->config.max_window_width;
		*height = server->config.max_window_height;
	} else {
		wtwm_default_max_window_size(area->width, area->height, width, height);
	}
}

static void clip_initial_toplevel_size(struct toplevel *toplevel,
		const struct wtwm_placement_area *area, int *width, int *height) {
	int max_width = 0, max_height = 0;
	server_max_window_size(toplevel->server, area, &max_width, &max_height);
	wtwm_clip_initial_size(max_width, max_height, width, height);
}

static void place_native_toplevel(struct toplevel *toplevel) {
	struct wtwm_placement_area area;
	server_placement_area(toplevel->server, &area);
	int width = toplevel->width, height = toplevel->height;
	clip_initial_toplevel_size(toplevel, &area, &width, &height);
	if (width != toplevel->width || height != toplevel->height) {
		toplevel->width = width;
		toplevel->height = height;
		wlr_xdg_toplevel_set_size(toplevel->xdg, width, height);
	}
	if (toplevel->placed) {
		toplevel->placement_kind = WTWM_PLACEMENT_REMAPPED;
		return;
	}
	int pointer_x = (int)toplevel->server->cursor->x;
	int pointer_y = (int)toplevel->server->cursor->y;
	int x = pointer_x, y = pointer_y;
	if (toplevel->server->config.random_placement) {
		wtwm_random_placement_next(&toplevel->server->random_placement,
			area.width, area.height, width, height, &x, &y);
		x += area.x;
		y += area.y;
		toplevel->placement_kind = WTWM_PLACEMENT_RANDOM;
	} else {
		wtwm_pointer_placement(toplevel->server->placement_index,
			pointer_x, pointer_y, &x, &y);
		toplevel->placement_kind = WTWM_PLACEMENT_POINTER;
	}
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	if (toplevel->placement_kind == WTWM_PLACEMENT_POINTER &&
			toplevel->server->config.dont_move_off)
		wtwm_clamp_outer_position(&area, geometry.outer_width,
			geometry.outer_height, &x, &y);
	wlr_scene_node_set_position(&toplevel->tree->node, x, y);
	toplevel->frame_x = x;
	toplevel->frame_y = y;
	toplevel->placed = true;
	++toplevel->server->placement_index;
}

static void toplevel_map(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, map);
	if (toplevel->mapped) return;
	int previous_width = toplevel->width;
	int previous_height = toplevel->height;
	struct wlr_box geometry;
	wlr_xdg_surface_get_geometry(toplevel->xdg->base, &geometry);
	if (geometry.width > 0) toplevel->width = geometry.width;
	if (geometry.height > 0) toplevel->height = geometry.height;
	update_decoration(toplevel);
	if (toplevel->width != previous_width || toplevel->height != previous_height)
		test_trace_toplevel_event(toplevel, "configure", "client");
	bool initial_rules = initialize_toplevel_rules(toplevel);
	toplevel->mapped = true;
	toplevel->iconified = false;
	wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
	sync_toplevel_scene_stack(toplevel);
	sync_icon_manager_toplevel(toplevel);
	place_native_toplevel(toplevel);
	wlr_scene_node_set_enabled(&toplevel->tree->node, true);
	test_trace_toplevel_event(toplevel, "map", "client");
	if (should_start_iconified(toplevel, initial_rules)) {
		set_toplevel_iconified(toplevel, true);
	} else {
		suspend_toplevel(toplevel, false);
		process_cursor_motion(toplevel->server,
			toplevel->server->current_input_time_ms);
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
	bool placement_pending = toplevel->placement_pending;
	bool had_logical_focus = server->focus == toplevel;
	bool had_keyboard_focus = surface_belongs_to_toplevel(
		server->seat->keyboard_state.focused_surface, toplevel);
	bool had_pointer_focus = surface_belongs_to_toplevel(
		server->seat->pointer_state.focused_surface, toplevel);
	if (placement_pending) {
		if (toplevel == server->grabbed) cancel_initial_placement(toplevel);
		else {
			toplevel->placement_pending = false;
			test_trace_toplevel_event_at(toplevel, "abort", "placement",
				toplevel->frame_x, toplevel->frame_y,
				toplevel->width, toplevel->height);
		}
	} else if (toplevel == server->grabbed) {
		reset_cursor(server);
	}
	if (server->continuation.toplevel == toplevel)
		memset(&server->continuation, 0, sizeof(server->continuation));
	if (server->menu.target == toplevel ||
			server->menu.definition == &server->windows_menu) hide_menu(server);
	if (server->ring_leader == toplevel) server->ring_leader = NULL;
	if (server->pointer_toplevel == toplevel) {
		server->pointer_toplevel = NULL;
		server->pointer_context = WTWM_CONTEXT_ROOT;
	}
	if (had_pointer_focus) wlr_seat_pointer_clear_focus(server->seat);
	dismiss_toplevel_popups(toplevel);
	if (!toplevel->mapped) return;
	remove_icon_manager_toplevel(toplevel);
	if (toplevel->icon_region_allocated && server->icon_layout != NULL) {
		(void)wtwm_icon_layout_release(server->icon_layout,
			toplevel->icon_identity);
		toplevel->icon_region_allocated = false;
	}
	toplevel->mapped = false;
	wl_list_remove(&toplevel->link);
	wl_list_init(&toplevel->link);
	wlr_scene_node_set_enabled(&toplevel->tree->node, false);
	if (toplevel->icon_tree != NULL)
		wlr_scene_node_set_enabled(&toplevel->icon_tree->node, false);
	if (!placement_pending) test_trace_toplevel_event(toplevel, "unmap", "client");
	if (had_keyboard_focus || had_logical_focus) {
		server->focus_root = true;
		clear_keyboard_focus(server);
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
	destroy_icon_scene(toplevel);
	clear_icon_manager_render_cache(toplevel);
	free(toplevel->title_buttons);
	free(toplevel->net_wm_icon_pixels);
	free(toplevel->wm_hints_icon_bits);
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
	if (toplevel->mapped) sync_icon_manager_toplevel(toplevel);
	if (title_changed) refresh_toplevel_icon(toplevel);
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
	toplevel->icon_identity = ++server->next_icon_identity;
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
	float border[4];
	configured_color(server, "BorderColor", "black", toplevel, border);
	toplevel->frame = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->frame_pattern = wlr_scene_buffer_create(toplevel->tree, NULL);
	if (toplevel->frame == NULL || toplevel->frame_pattern == NULL ||
			!create_title_scene(toplevel)) {
		wlr_scene_node_destroy(&toplevel->tree->node);
		free(toplevel->title_buttons);
		free(toplevel);
		wlr_xdg_toplevel_send_close(xdg);
		return;
	}
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

static void destroy_xwayland_scene(struct toplevel *toplevel);

static bool create_xwayland_frame_scene(struct toplevel *toplevel) {
	if (toplevel->tree != NULL) return true;
	struct wlr_scene_tree *parent = toplevel->xwayland->override_redirect ?
		toplevel->server->overlay_tree : toplevel->server->view_tree;
	toplevel->tree = wlr_scene_tree_create(parent);
	if (toplevel->tree == NULL) return false;
	wlr_scene_node_set_enabled(&toplevel->tree->node, false);
	toplevel->tree->node.data = toplevel;
	float border[4];
	configured_color(toplevel->server, "BorderColor", "black", toplevel, border);
	toplevel->frame = wlr_scene_rect_create(toplevel->tree, 1, 1, border);
	toplevel->frame_pattern = wlr_scene_buffer_create(toplevel->tree, NULL);
	if (toplevel->frame == NULL || toplevel->frame_pattern == NULL ||
			!create_title_scene(toplevel)) {
		wlr_scene_node_destroy(&toplevel->tree->node);
		toplevel->tree = NULL;
		free(toplevel->title_buttons);
		toplevel->title_buttons = NULL;
		toplevel->title_button_count = 0;
		return false;
	}
	update_toplevel_metadata(toplevel, true);
	return true;
}

static bool create_xwayland_scene(struct toplevel *toplevel) {
	bool created_frame = toplevel->tree == NULL;
	if (!create_xwayland_frame_scene(toplevel)) return false;
	if (toplevel->content != NULL) return true;
	if (toplevel->xwayland->surface == NULL) return true;
	toplevel->content = wlr_scene_subsurface_tree_create(
		toplevel->tree, toplevel->xwayland->surface);
	if (toplevel->content == NULL) {
		if (created_frame) destroy_xwayland_scene(toplevel);
		return false;
	}
	update_toplevel_metadata(toplevel, true);
	return true;
}

static void destroy_xwayland_scene(struct toplevel *toplevel) {
	if (toplevel->tree != NULL) wlr_scene_node_destroy(&toplevel->tree->node);
	destroy_icon_scene(toplevel);
	free(toplevel->title_buttons);
	toplevel->title_buttons = NULL;
	toplevel->title_button_count = 0;
	toplevel->tree = NULL;
	toplevel->content = NULL;
	toplevel->frame = NULL;
	toplevel->frame_pattern = NULL;
	toplevel->title_tree = NULL;
	toplevel->title = NULL;
	toplevel->focus_mark = NULL;
	toplevel->title_text = NULL;
}

static void position_xwayland_transient(struct toplevel *toplevel) {
	if (toplevel->xwayland->override_redirect || toplevel->tree == NULL) return;
	struct wlr_xwayland_surface *parent_surface = toplevel->xwayland->parent;
	struct toplevel *parent = parent_surface != NULL ? parent_surface->data : NULL;
	if (parent == NULL || parent == toplevel || !parent->mapped || parent->tree == NULL ||
			parent_surface->override_redirect) return;
	/* twm initially stacks a transient immediately above its parent.  Keep the
	 * compositor's top-to-bottom model in the same order as the X server; later
	 * explicit raise/lower operations still affect one window at a time. */
	if (toplevel->mapped && toplevel->link.next != &parent->link) {
		wl_list_remove(&toplevel->link);
		wl_list_insert(parent->link.prev, &toplevel->link);
	}
	wlr_scene_node_place_above(&toplevel->tree->node, &parent->tree->node);
	wlr_xwayland_surface_restack(toplevel->xwayland,
		parent_surface, XCB_STACK_MODE_ABOVE);
	test_trace_toplevel_event(toplevel, "restack", "frame");
}

static void position_xwayland_transient_children(struct toplevel *parent) {
	struct toplevel *child;
	wl_list_for_each(child, &parent->server->xwayland_views, xwayland_link) {
		if (child != parent && child->mapped && child->associated &&
				child->xwayland->parent == parent->xwayland)
			position_xwayland_transient(child);
	}
}

static bool xwayland_position_flag(const struct toplevel *toplevel,
		uint32_t flag) {
	return toplevel->xwayland->size_hints != NULL &&
		(toplevel->xwayland->size_hints->flags & flag) != 0;
}

static bool initial_xwayland_frame(struct toplevel *toplevel,
		const struct wtwm_placement_area *area, int width, int height,
		bool start_iconified, int *frame_x, int *frame_y) {
	bool transient = toplevel->xwayland->parent != NULL;
	bool ask_user = wtwm_placement_asks_user(transient,
		xwayland_position_flag(toplevel, XCB_ICCCM_SIZE_HINT_US_POSITION),
		xwayland_position_flag(toplevel, XCB_ICCCM_SIZE_HINT_P_POSITION),
		toplevel->server->config.use_p_position_mode,
		toplevel->xwayland->x, toplevel->xwayland->y);
	int requested_x = toplevel->xwayland->x;
	int requested_y = toplevel->xwayland->y;
	if (ask_user && toplevel->server->config.random_placement) {
		wtwm_random_placement_next(&toplevel->server->random_placement,
			area->width, area->height, width, height,
			&requested_x, &requested_y);
		requested_x += area->x;
		requested_y += area->y;
		toplevel->placement_kind = WTWM_PLACEMENT_RANDOM;
	} else if (ask_user && !start_iconified) {
		struct wtwm_frame_geometry geometry;
		toplevel_geometry(toplevel, &geometry);
		wtwm_placement_prompt_position(area,
			toplevel->server->config.dont_move_off,
			geometry.outer_width, geometry.outer_height,
			(int)toplevel->server->cursor->x,
			(int)toplevel->server->cursor->y, frame_x, frame_y);
		toplevel->placement_kind = WTWM_PLACEMENT_INTERACTIVE;
		++toplevel->server->placement_index;
		return true;
	} else {
		toplevel->placement_kind = WTWM_PLACEMENT_REQUESTED;
	}
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(toplevel, &geometry);
	int gravity_x = -1, gravity_y = -1;
	xwayland_gravity_offsets(toplevel, &gravity_x, &gravity_y);
	struct wtwm_window_position position;
	wtwm_initial_window_position(requested_x, requested_y,
		toplevel->original_client_border, &geometry,
		toplevel->server->config.client_border_width,
		gravity_x, gravity_y, &position);
	*frame_x = position.frame_x;
	*frame_y = position.frame_y;
	if (ask_user && toplevel->server->config.random_placement)
		++toplevel->server->placement_index;
	return false;
}

static void expose_managed_xwayland(struct toplevel *toplevel,
		bool start_iconified) {
	update_decoration(toplevel);
	wlr_scene_node_set_enabled(&toplevel->tree->node, true);
	sync_icon_manager_toplevel(toplevel);
	test_trace_toplevel_event(toplevel, "map", "client");
	position_xwayland_transient(toplevel);
	position_xwayland_transient_children(toplevel);
	if (start_iconified) {
		set_toplevel_iconified(toplevel, true);
	} else {
		suspend_toplevel(toplevel, false);
		process_cursor_motion(toplevel->server,
			toplevel->server->current_input_time_ms);
	}
}

static void start_next_initial_placement(struct server *server) {
	if (server->grabbed != NULL) return;
	struct toplevel *candidate = NULL, *item;
	wl_list_for_each(item, &server->toplevels, link) {
		if (!item->placement_pending) continue;
		if (candidate == NULL || item->placement_order < candidate->placement_order)
			candidate = item;
	}
	if (candidate == NULL) return;
	struct wtwm_frame_geometry geometry;
	toplevel_geometry(candidate, &geometry);
	struct wtwm_placement_area area;
	server_placement_area(server, &area);
	int x = 0, y = 0;
	wtwm_placement_prompt_position(&area, server->config.dont_move_off,
		geometry.outer_width, geometry.outer_height,
		(int)server->cursor->x, (int)server->cursor->y, &x, &y);
	server->grabbed = candidate;
	server->cursor_mode = CURSOR_MOVE;
	server->last_interaction_moved = false;
	server->interaction = (struct interaction_session){
		.original = {.x = x, .y = y,
			.width = candidate->width, .height = candidate->height},
		.preview = {.x = x, .y = y,
			.width = candidate->width, .height = candidate->height},
		.pointer_start_x = server->cursor->x,
		.pointer_start_y = server->cursor->y,
		.started = true,
		.intent = INTERACTION_INITIAL_POSITION,
	};
	set_cursor_role(server, "Move");
	candidate->frame_x = x;
	candidate->frame_y = y;
	test_trace_toplevel_event_at(candidate, "begin", "placement",
		x, y, candidate->width, candidate->height);
	show_interaction_outline(server);
}

static void finish_initial_placement(struct server *server) {
	struct toplevel *toplevel = server->grabbed;
	if (toplevel == NULL || !toplevel->placement_pending) return;
	struct wtwm_interaction_box preview = server->interaction.preview;
	clear_interaction_outline(server);
	toplevel->width = preview.width;
	toplevel->height = preview.height;
	configure_xwayland_frame(toplevel, preview.x, preview.y,
		preview.width, preview.height);
	toplevel->placed = true;
	test_trace_toplevel_event_at(toplevel, "commit", "placement",
		preview.x, preview.y, preview.width, preview.height);
	toplevel->placement_pending = false;
	bool start_iconified = toplevel->placement_start_iconified;
	toplevel->placement_start_iconified = false;
	reset_cursor(server);
	expose_managed_xwayland(toplevel, start_iconified);
	start_next_initial_placement(server);
}

static void cancel_initial_placement(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->placement_pending) return;
	struct server *server = toplevel->server;
	toplevel->placement_pending = false;
	test_trace_toplevel_event_at(toplevel, "abort", "placement",
		server->interaction.preview.x, server->interaction.preview.y,
		server->interaction.preview.width, server->interaction.preview.height);
	if (server->grabbed == toplevel) reset_cursor(server);
	start_next_initial_placement(server);
}

static void insert_xwayland_stack(struct toplevel *toplevel) {
	/* Xwayland may associate/map sibling wl_surfaces in a different order than
	 * their X windows were created.  The XWM surface list retains the initial
	 * top-to-bottom order, the reverse of QueryTree's bottom-to-top result. */
	struct toplevel *higher = NULL, *item;
	wl_list_for_each(item, &toplevel->server->xwayland_views, xwayland_link) {
		if (item == toplevel) break;
		if (item->mapped && !item->xwayland->override_redirect) higher = item;
	}
	if (higher == NULL)
		wl_list_insert(&toplevel->server->toplevels, &toplevel->link);
	else
		wl_list_insert(&higher->link, &toplevel->link);
	sync_toplevel_scene_stack(toplevel);
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
		insert_xwayland_stack(toplevel);
		struct wtwm_placement_area area;
		server_placement_area(toplevel->server, &area);
		int width = toplevel->width, height = toplevel->height;
		clip_initial_toplevel_size(toplevel, &area, &width, &height);
		int frame_x = toplevel->frame_x;
		int frame_y = toplevel->frame_y;
		bool interactive_placement = false;
		bool start_iconified = should_start_iconified(toplevel, initial_rules);
		if (!toplevel->frame_positioned) {
			/* Geometry uses the clipped client size, as AddWindow does. */
			toplevel->width = width;
			toplevel->height = height;
			interactive_placement = initial_xwayland_frame(toplevel, &area,
				width, height, start_iconified,
				&frame_x, &frame_y);
		} else {
			toplevel->placement_kind = WTWM_PLACEMENT_REMAPPED;
		}
		if (interactive_placement) {
			toplevel->placement_pending = true;
			toplevel->placement_start_iconified = start_iconified;
			toplevel->placement_order = ++toplevel->server->placement_order_next;
			start_next_initial_placement(toplevel->server);
			return;
		}
		configure_xwayland_frame(toplevel, frame_x, frame_y, width, height);
		toplevel->placed = true;
		expose_managed_xwayland(toplevel, start_iconified);
		return;
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
	if (changed) {
		test_trace_toplevel_event(toplevel, "icon_name", "icon");
		sync_icon_manager_toplevel(toplevel);
		refresh_toplevel_icon(toplevel);
	}
}

static void read_xwayland_net_wm_icon(struct toplevel *toplevel) {
	free(toplevel->net_wm_icon_pixels);
	toplevel->net_wm_icon_pixels = NULL;
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
		refresh_toplevel_icon(toplevel);
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
		if (toplevel->net_wm_icon_pixels == NULL && width <= 256 && height <= 256) {
			toplevel->net_wm_icon_pixels = malloc(pixels *
				sizeof(*toplevel->net_wm_icon_pixels));
			if (toplevel->net_wm_icon_pixels != NULL) {
				memcpy(toplevel->net_wm_icon_pixels, &values[index],
					pixels * sizeof(*toplevel->net_wm_icon_pixels));
				toplevel->net_wm_icon_width = width;
				toplevel->net_wm_icon_height = height;
			}
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
	refresh_toplevel_icon(toplevel);
}

static void read_xwayland_wm_hints_icon(struct toplevel *toplevel) {
	free(toplevel->wm_hints_icon_bits);
	toplevel->wm_hints_icon_bits = NULL;
	toplevel->wm_hints_icon_width = 0;
	toplevel->wm_hints_icon_height = 0;
	toplevel->wm_hints_icon_window_width = 0;
	toplevel->wm_hints_icon_window_height = 0;
	xcb_icccm_wm_hints_t *hints = toplevel->xwayland->hints;
	xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(
		toplevel->server->xwayland);
	if (hints == NULL || connection == NULL) {
		refresh_toplevel_icon(toplevel);
		return;
	}
	if ((hints->flags & XCB_ICCCM_WM_HINT_ICON_WINDOW) != 0 &&
			hints->icon_window != XCB_WINDOW_NONE) {
		xcb_get_geometry_reply_t *window_geometry = xcb_get_geometry_reply(
			connection, xcb_get_geometry(connection, hints->icon_window), NULL);
		if (window_geometry != NULL && window_geometry->width > 0 &&
				window_geometry->height > 0 && window_geometry->width <= 256 &&
				window_geometry->height <= 256) {
			toplevel->wm_hints_icon_window_width = window_geometry->width;
			toplevel->wm_hints_icon_window_height = window_geometry->height;
		}
		free(window_geometry);
	}
	if ((hints->flags & XCB_ICCCM_WM_HINT_ICON_PIXMAP) == 0 ||
			hints->icon_pixmap == XCB_PIXMAP_NONE) {
		refresh_toplevel_icon(toplevel);
		return;
	}
	xcb_get_geometry_reply_t *geometry = xcb_get_geometry_reply(connection,
		xcb_get_geometry(connection, hints->icon_pixmap), NULL);
	if (geometry == NULL || geometry->depth != 1 || geometry->width == 0 ||
			geometry->height == 0 || geometry->width > 256 ||
			geometry->height > 256) {
		free(geometry);
		refresh_toplevel_icon(toplevel);
		return;
	}
	xcb_get_image_reply_t *image = xcb_get_image_reply(connection,
		xcb_get_image(connection, XCB_IMAGE_FORMAT_Z_PIXMAP,
			hints->icon_pixmap, 0, 0, geometry->width, geometry->height,
			UINT32_MAX), NULL);
	if (image == NULL) {
		free(geometry);
		refresh_toplevel_icon(toplevel);
		return;
	}
	const unsigned char *source = xcb_get_image_data(image);
	size_t source_length = (size_t)xcb_get_image_data_length(image);
	size_t source_stride = source_length / geometry->height;
	size_t stride = ((size_t)geometry->width + 7u) / 8u;
	unsigned char *bits = calloc(geometry->height, stride);
	if (bits != NULL) {
		bool lsb = xcb_get_setup(connection)->bitmap_format_bit_order ==
			XCB_IMAGE_ORDER_LSB_FIRST;
		for (unsigned y = 0; y < geometry->height; ++y)
			for (unsigned x = 0; x < geometry->width; ++x) {
				size_t source_byte = (size_t)y * source_stride + x / 8u;
				unsigned source_bit = lsb ? x & 7u : 7u - (x & 7u);
				if (source_byte < source_length &&
						(source[source_byte] & (1u << source_bit)) != 0)
					bits[(size_t)y * stride + x / 8u] |=
						(unsigned char)(1u << (x & 7u));
			}
		toplevel->wm_hints_icon_bits = bits;
		toplevel->wm_hints_icon_width = geometry->width;
		toplevel->wm_hints_icon_height = geometry->height;
	}
	free(image);
	free(geometry);
	refresh_toplevel_icon(toplevel);
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
	manage_bufferless_start_iconified(toplevel);
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
	read_xwayland_wm_hints_icon(toplevel);
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
		 * then misses that commit. Complete any pending callback after our
		 * listeners exist, and manage the retained buffer without depending on
		 * Xwayland producing another commit. */
		finish_surface_frame(toplevel->xwayland->surface);
		map_xwayland_toplevel(toplevel);
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

static char *read_xwayland_property_bytes(struct toplevel *toplevel,
		xcb_atom_t atom, size_t *length) {
	*length = 0;
	xcb_connection_t *connection = wlr_xwayland_get_xwm_connection(
		toplevel->server->xwayland);
	if (connection == NULL) return NULL;
	xcb_get_property_reply_t *reply = xcb_get_property_reply(connection,
		xcb_get_property(connection, false, toplevel->xwayland->window_id,
			atom, XCB_ATOM_ANY, 0, 1024), NULL);
	if (reply == NULL || reply->format != 8) {
		free(reply);
		return NULL;
	}
	int byte_count = xcb_get_property_value_length(reply);
	if (byte_count <= 0) {
		free(reply);
		return NULL;
	}
	char *value = malloc((size_t)byte_count + 1);
	if (value != NULL) {
		memcpy(value, xcb_get_property_value(reply), (size_t)byte_count);
		value[byte_count] = '\0';
		*length = (size_t)byte_count;
	}
	free(reply);
	return value;
}

static void update_bufferless_xwayland_identity(struct toplevel *toplevel) {
	size_t name_length = 0;
	char *name = read_xwayland_property_bytes(toplevel, XCB_ATOM_WM_NAME,
		&name_length);
	size_t class_length = 0;
	char *class_data = read_xwayland_property_bytes(toplevel, XCB_ATOM_WM_CLASS,
		&class_length);
	char *instance = NULL;
	char *resource_class = NULL;
	if (class_data != NULL) {
		size_t instance_length = strnlen(class_data, class_length);
		instance = strndup(class_data, instance_length);
		if (instance_length < class_length) {
			const char *class_start = class_data + instance_length + 1;
			size_t remaining = class_length - instance_length - 1;
			resource_class = strndup(class_start,
				strnlen(class_start, remaining));
		}
	}
	free(toplevel->xwayland_direct_name);
	toplevel->xwayland_direct_name = name;
	free(toplevel->xwayland_direct_instance);
	toplevel->xwayland_direct_instance = instance;
	free(toplevel->xwayland_direct_class);
	toplevel->xwayland_direct_class = resource_class;
	free(class_data);
	(void)name_length;
}

static void manage_bufferless_start_iconified(struct toplevel *toplevel) {
	const struct wtwm_config *config = &toplevel->server->config;
	const struct wtwm_string_list *start_iconified =
		&config->start_iconified_windows;
	if (!toplevel->xwayland_map_requested || toplevel->mapped ||
			toplevel->associated ||
			toplevel->xwayland->override_redirect ||
			!toplevel_matches(start_iconified, toplevel))
		return;
	toplevel->start_iconified_match = true;
	initialize_xwayland_border(toplevel);
	read_xwayland_icon_name(toplevel);
	read_xwayland_net_wm_icon(toplevel);
	read_xwayland_wm_hints_icon(toplevel);
	if (create_xwayland_frame_scene(toplevel)) map_xwayland_toplevel(toplevel);
}

static void xwayland_set_title(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_title);
	update_toplevel_metadata(toplevel, true);
	manage_bufferless_start_iconified(toplevel);
}

static void xwayland_set_class(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, set_class);
	update_toplevel_metadata(toplevel, false);
	manage_bufferless_start_iconified(toplevel);
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
	read_xwayland_wm_hints_icon(toplevel);
	if (toplevel->mapped && toplevel->xwayland->hints != NULL &&
			(toplevel->xwayland->hints->flags & XCB_ICCCM_WM_HINT_X_URGENCY) != 0)
		wlr_log(WLR_DEBUG, "X11 window 0x%08" PRIx32 " requests attention",
			toplevel->xwayland->window_id);
	/* wlroots may deliver the initial pointer crossing before WM_HINTS.  twm
	 * reads those hints before dispatching the crossing, so finish the direct
	 * input-focus half when the late property arrives without duplicating
	 * activation or WM_TAKE_FOCUS. */
	if (toplevel->mapped && toplevel->server->focus_root &&
			toplevel->server->pointer_toplevel == toplevel &&
			toplevel->server->focus == toplevel) {
		struct wtwm_focus_enter_result result = wtwm_focus_enter(
			&(struct wtwm_focus_enter_input){
				.focus_root = true,
				.surface = WTWM_FOCUS_SURFACE_FRAME,
				.title_focus = !toplevel->server->config.no_title_focus,
				.has_title = toplevel->decorated,
				.global_no_titlebar = toplevel->server->config.no_title,
				.input_hint = xwayland_input_hint_true(toplevel),
			});
		if (result.set_input_focus)
			focus_toplevel(toplevel, true, false, "frame");
	}
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
	unmanage_toplevel(toplevel);
	test_trace_toplevel_event(toplevel, "destroy", "client");
	if (toplevel->associated) {
		wl_list_remove(&toplevel->map.link);
		wl_list_remove(&toplevel->unmap.link);
		wl_list_remove(&toplevel->commit.link);
	}
	if (toplevel->tree != NULL) destroy_xwayland_scene(toplevel);
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
	free(toplevel->xwayland_direct_name);
	free(toplevel->xwayland_direct_instance);
	free(toplevel->xwayland_direct_class);
	clear_icon_manager_render_cache(toplevel);
	free(toplevel->net_wm_icon_pixels);
	free(toplevel->wm_hints_icon_bits);
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
	toplevel->icon_identity = ++server->next_icon_identity;
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
	/* twm manages an X MapRequest before the client has painted.  Rootless
	 * Xwayland may intentionally defer wl_surface buffers for minimized
	 * windows, so the user event hook below builds the logical icon and manager
	 * entry directly from X11 metadata when StartIconified matches.  Association
	 * attaches content if the window is deiconified later. */
	manage_bufferless_start_iconified(toplevel);
	schedule_xwayland_sync(toplevel);
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
	if (type == XCB_FOCUS_IN) {
		xcb_focus_in_event_t *focus = (xcb_focus_in_event_t *)event;
		/* Managed X11 focus follows the twm model above. Consuming FocusIn
		 * prevents wlroots' EWMH helper from replacing our direct ICCCM
		 * PointerRoot/client decision with its conflated activation policy. */
		struct toplevel *toplevel =
			xwayland_toplevel_for_window(server, focus->event);
		return toplevel != NULL && toplevel->associated &&
			!toplevel->xwayland->override_redirect;
	}
	if (type == XCB_PROPERTY_NOTIFY) {
		xcb_property_notify_event_t *property = (xcb_property_notify_event_t *)event;
		struct toplevel *toplevel =
			xwayland_toplevel_for_window(server, property->window);
		if (toplevel == NULL) return 0;
		if (property->atom == XCB_ATOM_WM_NAME ||
				property->atom == XCB_ATOM_WM_CLASS)
			update_bufferless_xwayland_identity(toplevel);
		else if (property->atom == server->atom_wm_icon_name)
			read_xwayland_icon_name(toplevel);
		else if (property->atom == server->atom_net_wm_icon)
			read_xwayland_net_wm_icon(toplevel);
		else if (property->atom == server->atom_wm_normal_hints ||
				property->atom == server->atom_wm_protocols ||
				property->atom == server->atom_wm_transient_for)
			schedule_xwayland_sync(toplevel);
		return 0;
	}
	if (type == XCB_MAP_REQUEST) {
		xcb_map_request_event_t *map = (xcb_map_request_event_t *)event;
		struct toplevel *toplevel =
			xwayland_toplevel_for_window(server, map->window);
		if (toplevel != NULL) {
			toplevel->xwayland_map_requested = true;
			update_bufferless_xwayland_identity(toplevel);
			read_xwayland_icon_name(toplevel);
			reserve_icon_manager_toplevel(toplevel);
			manage_bufferless_start_iconified(toplevel);
		}
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
	struct wtwm_client_identity identity = toplevel_identity(toplevel);
	const char *app_id = toplevel->xdg != NULL ? toplevel->xdg->app_id :
		identity.resource_class;
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
		test_write(control, ",\"placement\":");
		test_write_json_string(control, event->placement);
		test_write(control, ",\"active\":%s}}",
			event->active ? "true" : "false");
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
		"\"random_placement\":{\"next_x\":%d,\"next_y\":%d},"
		"\"cursor\":{\"x\":%.3f,\"y\":%.3f},\"focus_root\":%s,"
		"\"active\":",
		server->frame_sequence, control->animation_ms, server->placement_index,
		server->random_placement.next_x, server->random_placement.next_y,
		server->cursor->x, server->cursor->y,
		server->focus_root ? "true" : "false");
	if (server->focus == NULL) test_write(control, "null");
	else test_write_json_string(control, toplevel_title(server->focus));
	test_write(control, ",\"focus\":");
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
		struct wtwm_client_identity identity = toplevel_identity(toplevel);
		toplevel_geometry(toplevel, &geometry);
		test_write(control, "{\"id\":%" PRIu64 ",\"title\":",
			toplevel->test_id);
		test_write_json_string(control, toplevel_title(toplevel));
		test_write(control, ",\"app_id\":");
		test_write_json_string(control, toplevel_app_id(toplevel));
		test_write(control, ",\"type\":\"%s\",\"instance\":",
			toplevel->xwayland != NULL ? "x11" : "wayland");
		test_write_json_string(control, identity.resource_name);
		test_write(control, ",\"class\":");
		test_write_json_string(control, identity.resource_class);
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
			"\"border_width\":%d,\"title_bar_height\":%d,\"title_height\":%d,"
			"\"frame_width\":%d,\"frame_height\":%d,"
			"\"outer_width\":%d,\"outer_height\":%d,"
			"\"content_x\":%d,\"content_y\":%d,"
			"\"stack\":%u,\"mapped\":%s,\"placement_pending\":%s,"
			"\"iconified\":%s,\"iconify_by_unmapping\":%s,"
			"\"decorated\":%s,\"auto_raise\":%s,\"active\":%s,\"placement\":",
			toplevel->tree->node.x, toplevel->tree->node.y,
			toplevel->width, toplevel->height,
			geometry.border_width, geometry.title_bar_height, geometry.title_extent,
			geometry.frame_width, geometry.frame_height,
			geometry.outer_width, geometry.outer_height,
			geometry.content_x, geometry.content_y, stack++,
			toplevel->mapped && !toplevel->placement_pending ? "true" : "false",
			toplevel->placement_pending ? "true" : "false",
			toplevel->iconified ? "true" : "false",
			toplevel->iconify_by_unmapping ? "true" : "false",
			toplevel->decorated ? "true" : "false",
			toplevel->auto_raise ? "true" : "false",
			server->focus == toplevel ? "true" : "false");
		test_write_json_string(control,
			wtwm_placement_kind_name(toplevel->placement_kind));
		if (toplevel->xwayland != NULL) {
			struct wlr_xwayland_surface *xsurface = toplevel->xwayland;
			xcb_icccm_wm_hints_t *hints = xsurface->hints;
			xcb_size_hints_t *size = xsurface->size_hints;
			uint32_t size_flags = size != NULL ? size->flags : 0;
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
				size_flags,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_MIN_SIZE) != 0 ?
					size->min_width : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_MIN_SIZE) != 0 ?
					size->min_height : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_MAX_SIZE) != 0 ?
					size->max_width : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_MAX_SIZE) != 0 ?
					size->max_height : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_BASE_SIZE) != 0 ?
					size->base_width : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_BASE_SIZE) != 0 ?
					size->base_height : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_RESIZE_INC) != 0 ?
					size->width_inc : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_RESIZE_INC) != 0 ?
					size->height_inc : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_ASPECT) != 0 ?
					size->min_aspect_num : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_ASPECT) != 0 ?
					size->min_aspect_den : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_ASPECT) != 0 ?
					size->max_aspect_num : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_ASPECT) != 0 ?
					size->max_aspect_den : 0,
				(size_flags & XCB_ICCCM_SIZE_HINT_P_WIN_GRAVITY) != 0 ?
					size->win_gravity : 0);
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
	test_write(control, "],\"icon_views\":[");
	first = true;
	wl_list_for_each(toplevel, &server->toplevels, link) {
		if (!toplevel->iconified || toplevel->icon_tree == NULL) continue;
		if (!first) test_write(control, ",");
		first = false;
		test_write(control, "{\"title\":");
		test_write_json_string(control, toplevel_title(toplevel));
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
			"\"source\":",
			toplevel->icon_x, toplevel->icon_y,
			toplevel->icon_width, toplevel->icon_height);
		test_write_json_string(control, toplevel->icon_source);
		test_write(control, ",\"region_allocated\":%s}",
			toplevel->icon_region_allocated ? "true" : "false");
	}
	test_write(control, "],\"icon_managers\":[");
	for (size_t i = 0; i < server->icon_managers.manager_count; ++i) {
		const struct wtwm_icon_manager_model *manager =
			&server->icon_managers.managers[i];
		struct icon_manager_view *view = icon_manager_view_for(server,
			manager->identity);
		if (i != 0) test_write(control, ",");
		test_write(control, "{\"id\":%" PRIu64 ",\"name\":",
			manager->identity);
		test_write_json_string(control, manager->label);
		test_write(control,
			",\"visible\":%s,\"sorted\":%s,\"columns\":%zu,"
			"\"rows\":%zu,\"x\":%d,\"y\":%d,\"width\":%d,"
			"\"height\":%d,\"active_entry\":%" PRIu64 ",\"entries\":[",
			manager->visible ? "true" : "false",
			manager->sorted ? "true" : "false", manager->current_columns,
			manager->current_rows, view != NULL ? view->x : 0,
			view != NULL ? view->y : 0, view != NULL ? view->width : 0,
			view != NULL ? view->height : 0,
			manager->selected_entry_identity);
		for (size_t position = 0; position < manager->entry_count; ++position) {
			const struct wtwm_icon_manager_entry *entry =
				wtwm_icon_manager_entry_at(&server->icon_managers,
					manager->identity, position);
			if (position != 0) test_write(control, ",");
			test_write(control, "{\"id\":%" PRIu64 ",\"label\":",
				entry->identity);
			test_write_json_string(control, entry->label);
			test_write(control, ",\"row\":%zu,\"column\":%zu}",
				entry->row, entry->column);
		}
		test_write(control, "]}");
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
		const char *intent = server->interaction.intent == INTERACTION_DRAG ? "drag" :
			server->interaction.intent == INTERACTION_MENU_POSITION ? "menu-position" :
			server->interaction.intent == INTERACTION_INITIAL_POSITION ? "placement" :
			server->interaction.intent == INTERACTION_INITIAL_CONFIRM ?
				"placement-confirm" : "placement-resize";
		test_write(control, "{\"window\":");
		test_write_json_string(control, toplevel_title(server->grabbed));
		test_write(control,
			",\"mode\":\"%s\",\"intent\":\"%s\",\"started\":%s,\"moved\":%s,"
			"\"force\":%s,\"opaque\":%s,\"constrained\":%s,"
			"\"axis\":\"%s\",\"edges\":%" PRIu32 ","
			"\"preview\":{\"x\":%d,\"y\":%d,\"width\":%d,"
			"\"height\":%d}}",
			server->cursor_mode == CURSOR_MOVE ? "move" : "resize", intent,
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
	test_write(control, ",\"deferred_root_action\":%s,\"menu\":",
		server->deferred_root_action_active ? "true" : "false");
	if (server->menu.tree == NULL) {
		test_write(control, "null");
	} else {
		test_write(control, "{\"name\":");
		test_write_json_string(control, server->menu.definition->name);
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
			"\"row_height\":%d,\"depth\":%u,\"selected\":%d}",
			server->menu.x, server->menu.y, server->menu.width,
			server->menu.height, server->menu.row_height,
			menu_depth(&server->menu), server->menu.selected);
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
		wtwm_random_placement_seed(&server->random_placement,
			server->placement_index);
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
	fprintf(stream, "usage: %s [-d] [-f twmrc] [-s startup-command]"
		" [--visual-mode color|grayscale|monochrome]", program);
#ifdef WTWM_TEST_CONTROL
	fprintf(stream, " [--test-control path] [--test-socket name]"
		" [--test-backend auto|headless|wayland]");
#endif
	fprintf(stream, "\n");
}

int main(int argc, char **argv) {
	const char *config_path = NULL;
	const char *startup = NULL;
	const char *visual_mode = "color";
	enum {
		OPTION_VISUAL_MODE = 256,
		OPTION_TEST_CONTROL,
		OPTION_TEST_SOCKET,
		OPTION_TEST_BACKEND,
	};
#ifdef WTWM_TEST_CONTROL
	const char *test_control_path = NULL;
	const char *test_socket = NULL;
	const char *test_backend = "auto";
	static const struct option options[] = {
		{"debug", no_argument, NULL, 'd'},
		{"config", required_argument, NULL, 'f'},
		{"help", no_argument, NULL, 'h'},
		{"startup", required_argument, NULL, 's'},
		{"visual-mode", required_argument, NULL, OPTION_VISUAL_MODE},
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
		{"visual-mode", required_argument, NULL, OPTION_VISUAL_MODE},
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
		case OPTION_VISUAL_MODE: visual_mode = optarg; break;
#ifdef WTWM_TEST_CONTROL
		case OPTION_TEST_CONTROL: test_control_path = optarg; break;
		case OPTION_TEST_SOCKET: test_socket = optarg; break;
		case OPTION_TEST_BACKEND: test_backend = optarg; break;
#endif
		default: usage(stderr, argv[0]); return 2;
		}
	}
	if (strcmp(visual_mode, "color") != 0 &&
			strcmp(visual_mode, "grayscale") != 0 &&
			strcmp(visual_mode, "monochrome") != 0) {
		fprintf(stderr, "wtwm: invalid visual mode: %s\n", visual_mode);
		return 2;
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
	server.argc = argc;
	server.argv = argv;
	server.config_path = config_path;
	server.previous_output_index = -1;
	server.color_mode = strcmp(visual_mode, "monochrome") == 0 ?
		WTWM_COLOR_MODE_MONOCHROME :
		(strcmp(visual_mode, "grayscale") == 0 ? WTWM_COLOR_MODE_GRAYSCALE :
			WTWM_COLOR_MODE_COLOR);
	server.focus_root = true;
	server.pointer_context = WTWM_CONTEXT_ROOT;
	wtwm_random_placement_init(&server.random_placement);
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
	server.icon_manager_tree = wlr_scene_tree_create(&server.scene->tree);
	server.overlay_tree = wlr_scene_tree_create(&server.scene->tree);
	server.menu_tree = wlr_scene_tree_create(&server.scene->tree);
	wl_list_init(&server.toplevels);
	wl_list_init(&server.xwayland_views);
	wl_list_init(&server.popups);
	initialize_icon_managers(&server);
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
	set_cursor_role(&server, "Frame");
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
	if (startup != NULL) spawn_command(startup);
	wlr_log(WLR_INFO, "wtwm running on WAYLAND_DISPLAY=%s", socket);
	wl_display_run(server.display);
	xwayland_finish(&server);
	wl_display_destroy_clients(server.display);
#ifdef WTWM_TEST_CONTROL
	test_control_finish(&server);
#endif
	hide_menu(&server);
	finish_icon_animation(&server);
	wtwm_icon_layout_destroy(server.icon_layout);
	free(server.windows_menu.items);
	free(server.windows_menu_targets);
	wlr_scene_node_destroy(&server.scene->tree.node);
	wlr_xcursor_manager_destroy(server.cursor_manager);
	wlr_cursor_destroy(server.cursor);
	if (server.configured_cursor_buffer != NULL)
		wlr_buffer_drop(server.configured_cursor_buffer);
	wlr_allocator_destroy(server.allocator);
	wlr_renderer_destroy(server.renderer);
	wlr_backend_destroy(server.backend);
	wl_display_destroy(server.display);
	wtwm_config_finish(&server.config);
#ifdef WTWM_TEST_CONTROL
	pango_cairo_font_map_set_default(NULL);
	FcFini();
#endif
	if (server.restart_requested) {
		execvp(server.argv[0], server.argv);
		wlr_log_errno(WLR_ERROR, "%s", "failed to restart wtwm");
		return 1;
	}
	return 0;

fail_runtime:
	xwayland_finish(&server);
#ifdef WTWM_TEST_CONTROL
	test_control_finish(&server);
#endif
	hide_menu(&server);
	finish_icon_animation(&server);
	wtwm_icon_layout_destroy(server.icon_layout);
	free(server.windows_menu.items);
	free(server.windows_menu_targets);
	wlr_scene_node_destroy(&server.scene->tree.node);
	wlr_xcursor_manager_destroy(server.cursor_manager);
	wlr_cursor_destroy(server.cursor);
	if (server.configured_cursor_buffer != NULL)
		wlr_buffer_drop(server.configured_cursor_buffer);
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
