/* SPDX-License-Identifier: MIT
 *
 * wtwm is built on wlroots' public 0.18 scene and xdg-shell APIs.  The small
 * compositor core follows the same event-driven shape as wlroots/tinywl, with
 * server-side decorations and twm actions kept in this project.
 */
#define _POSIX_C_SOURCE 200809L
#define WLR_USE_UNSTABLE

#include "wtwm/config.h"
#include "text.h"
#ifdef WTWM_TEST_CONTROL
#include "test_control.h"
#endif

#include <errno.h>
#include <getopt.h>
#include <inttypes.h>
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
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_xcursor_manager.h>
#include <wlr/types/wlr_xdg_decoration_v1.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/log.h>
#include <xkbcommon/xkbcommon.h>

enum cursor_mode { CURSOR_PASSTHROUGH, CURSOR_MOVE, CURSOR_RESIZE };

struct server;

#ifdef WTWM_TEST_CONTROL
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
};
#endif

struct toplevel {
	struct wl_list link;
	struct server *server;
	struct wlr_xdg_toplevel *xdg;
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
	int title_height;
	bool mapped;
	bool placed;
	bool iconified;
	bool decorated;
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

struct server {
	struct wtwm_config config;
	struct wl_display *display;
	struct wlr_backend *backend;
	struct wlr_renderer *renderer;
	struct wlr_allocator *allocator;
	struct wlr_scene *scene;
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
	struct wl_list keyboards;
	enum cursor_mode cursor_mode;
	struct toplevel *grabbed;
	double grab_x;
	double grab_y;
	struct wlr_box grab_box;
	uint32_t resize_edges;
	uint64_t frame_sequence;
#ifdef WTWM_TEST_CONTROL
	struct test_control test_control;
#endif
};

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

static struct wlr_xdg_toplevel *toplevel_for_surface(struct wlr_surface *surface) {
	if (surface == NULL) return NULL;
	surface = wlr_surface_get_root_surface(surface);
	struct wlr_xdg_popup *popup;
	while ((popup = wlr_xdg_popup_try_from_wlr_surface(surface)) != NULL) {
		if (popup->parent == NULL) return NULL;
		surface = wlr_surface_get_root_surface(popup->parent);
	}
	return wlr_xdg_toplevel_try_from_wlr_surface(surface);
}

static bool surface_belongs_to_toplevel(struct wlr_surface *surface,
	struct toplevel *toplevel) {
	return toplevel_for_surface(surface) == toplevel->xdg;
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

static bool name_matches(const struct wtwm_string_list *patterns,
	struct wlr_xdg_toplevel *xdg) {
	const char *app_id = xdg->app_id ? xdg->app_id : "";
	const char *title = xdg->title ? xdg->title : "";
	return wtwm_config_match_native(patterns, title, app_id);
}

static void update_title_text(struct toplevel *toplevel) {
	if (toplevel->title_text == NULL) return;
	float foreground[4];
	color_value(toplevel->server->config.title_foreground, foreground);
	int width = 0, height = 0;
	struct wlr_buffer *buffer = wtwm_render_text(toplevel->xdg->title,
		toplevel->server->config.title_font, foreground, &width, &height);
	if (buffer == NULL) return;
	toplevel->title_text_height = height;
	wlr_scene_buffer_set_buffer(toplevel->title_text, buffer);
	wlr_buffer_drop(buffer);
}

static void update_decoration(struct toplevel *toplevel) {
	if (!toplevel->decorated) {
		wlr_scene_node_set_position(&toplevel->content->node, 0, 0);
		return;
	}
	int border = toplevel->server->config.border_width;
	int button = toplevel->title_height - 4;
	int full_width = toplevel->width + 2 * border;
	int full_height = toplevel->height + toplevel->title_height + 2 * border;
	wlr_scene_rect_set_size(toplevel->frame, full_width, full_height);
	wlr_scene_rect_set_size(toplevel->title, toplevel->width, toplevel->title_height);
	wlr_scene_rect_set_size(toplevel->focus_mark,
		toplevel->width > 2 * button + 12 ? toplevel->width - 2 * button - 12 : 1, 2);
	wlr_scene_rect_set_size(toplevel->left_button, button, button);
	wlr_scene_rect_set_size(toplevel->right_button, button, button);
	wlr_scene_rect_set_size(toplevel->right_inner, button > 8 ? button - 8 : 1,
		button > 8 ? button - 8 : 1);
	wlr_scene_node_set_position(&toplevel->title->node, border, border);
	wlr_scene_node_set_position(&toplevel->focus_mark->node,
		border + button + 6, border + toplevel->title_height - 4);
	wlr_scene_node_set_position(&toplevel->left_button->node, border + 2, border + 2);
	wlr_scene_node_set_position(&toplevel->left_dot->node,
		border + button / 2, border + button / 2);
	wlr_scene_node_set_position(&toplevel->right_button->node,
		border + toplevel->width - button - 2, border + 2);
	wlr_scene_node_set_position(&toplevel->right_inner->node,
		border + toplevel->width - button + 2, border + 6);
	wlr_scene_node_set_position(&toplevel->title_text->node,
		border + button + 7,
		border + (toplevel->title_height - toplevel->title_text_height) / 2);
	wlr_scene_node_set_position(&toplevel->content->node,
		border, border + toplevel->title_height);
}

static void set_decorated(struct toplevel *toplevel, bool enabled) {
	if (toplevel->title == NULL) return;
	toplevel->decorated = enabled;
	wlr_scene_node_set_enabled(&toplevel->frame->node, enabled);
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

static void focus_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || toplevel->iconified || !toplevel->mapped) return;
	struct server *server = toplevel->server;
	struct wlr_surface *surface = toplevel->xdg->base->surface;
	struct wlr_surface *previous = server->seat->keyboard_state.focused_surface;
	if (previous != surface) {
		struct wlr_xdg_toplevel *old = toplevel_for_surface(previous);
		if (old != NULL) wlr_xdg_toplevel_set_activated(old, false);
	}
	wlr_scene_node_raise_to_top(&toplevel->tree->node);
	wl_list_remove(&toplevel->link);
	wl_list_insert(&server->toplevels, &toplevel->link);
	wlr_xdg_toplevel_set_activated(toplevel->xdg, true);
	set_focused_marker(server, toplevel);
	struct wlr_keyboard *keyboard = wlr_seat_get_keyboard(server->seat);
	if (keyboard != NULL) {
		wlr_seat_keyboard_notify_enter(server->seat, surface, keyboard->keycodes,
			keyboard->num_keycodes, &keyboard->modifiers);
	}
}

static void focus_next(struct server *server) {
	struct toplevel *item;
	wl_list_for_each(item, &server->toplevels, link) {
		if (item->mapped && !item->iconified) {
			focus_toplevel(item);
			return;
		}
	}
	wlr_seat_keyboard_clear_focus(server->seat);
	set_focused_marker(server, NULL);
}

static void lower_toplevel(struct toplevel *toplevel) {
	if (toplevel == NULL || !toplevel->mapped) return;
	wlr_scene_node_lower_to_bottom(&toplevel->tree->node);
	wl_list_remove(&toplevel->link);
	wl_list_insert(toplevel->server->toplevels.prev, &toplevel->link);
}

static void reset_cursor(struct server *server) {
	server->cursor_mode = CURSOR_PASSTHROUGH;
	server->grabbed = NULL;
}

static void begin_interactive(struct toplevel *toplevel, enum cursor_mode mode,
	uint32_t edges) {
	if (toplevel == NULL || !toplevel->mapped || toplevel->iconified) return;
	struct server *server = toplevel->server;
	server->grabbed = toplevel;
	server->cursor_mode = mode;
	if (mode == CURSOR_MOVE) {
		server->grab_x = server->cursor->x - toplevel->tree->node.x;
		server->grab_y = server->cursor->y - toplevel->tree->node.y;
		return;
	}
	server->resize_edges = edges ? edges : (WLR_EDGE_RIGHT | WLR_EDGE_BOTTOM);
	server->grab_box = (struct wlr_box){
		.x = toplevel->tree->node.x,
		.y = toplevel->tree->node.y,
		.width = toplevel->width,
		.height = toplevel->height,
	};
	double edge_x = server->grab_box.x +
		((server->resize_edges & WLR_EDGE_RIGHT) ? server->grab_box.width : 0);
	double edge_y = server->grab_box.y +
		((server->resize_edges & WLR_EDGE_BOTTOM) ? server->grab_box.height : 0);
	server->grab_x = server->cursor->x - edge_x;
	server->grab_y = server->cursor->y - edge_y;
}

static void spawn_shell(const char *command) {
	if (command == NULL || command[0] == '\0') return;
	if (fork() == 0) {
		execl("/bin/sh", "/bin/sh", "-c", command, (void *)NULL);
		_exit(127);
	}
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
	struct wlr_scene_tree *tree = wlr_scene_tree_create(&server->scene->tree);
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

static void execute_action(struct server *server, struct toplevel *toplevel,
	const struct wtwm_action *action, unsigned depth) {
	if (depth > 8) return;
	switch (action->type) {
	case WTWM_ACTION_MOVE: case WTWM_ACTION_FORCEMOVE:
		begin_interactive(toplevel, CURSOR_MOVE, 0); break;
	case WTWM_ACTION_RESIZE:
		begin_interactive(toplevel, CURSOR_RESIZE, WLR_EDGE_RIGHT | WLR_EDGE_BOTTOM); break;
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
			wlr_xdg_toplevel_set_suspended(toplevel->xdg, true);
			focus_next(server);
		}
		break;
	case WTWM_ACTION_DEICONIFY:
		if (toplevel) {
			toplevel->iconified = false;
			wlr_scene_node_set_enabled(&toplevel->tree->node, true);
			wlr_xdg_toplevel_set_suspended(toplevel->xdg, false);
			focus_toplevel(toplevel);
		}
		break;
	case WTWM_ACTION_FOCUS:
		if (toplevel) focus_toplevel(toplevel);
		break;
	case WTWM_ACTION_UNFOCUS:
		wlr_seat_keyboard_clear_focus(server->seat); set_focused_marker(server, NULL); break;
	case WTWM_ACTION_DELETE: case WTWM_ACTION_DESTROY:
		if (toplevel) wlr_xdg_toplevel_send_close(toplevel->xdg);
		break;
	case WTWM_ACTION_EXEC:
		spawn_shell(action->argument); break;
	case WTWM_ACTION_MENU:
		show_menu(server, action->argument, toplevel); break;
	case WTWM_ACTION_FUNCTION:
		for (size_t i = 0; i < server->config.function_count; ++i) {
			if (strcmp(server->config.functions[i].name, action->argument) == 0) {
				for (size_t j = 0; j < server->config.functions[i].action_count; ++j)
					execute_action(server, toplevel,
						&server->config.functions[i].actions[j], depth + 1);
				break;
			}
		}
		break;
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
		execute_action(server, toplevel, &binding->action, 0);
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
	return hit;
}

static void process_cursor_motion(struct server *server, uint32_t time_msec) {
	if (server->cursor_mode == CURSOR_MOVE) {
		wlr_scene_node_set_position(&server->grabbed->tree->node,
			(int)(server->cursor->x - server->grab_x),
			(int)(server->cursor->y - server->grab_y));
		return;
	}
	if (server->cursor_mode == CURSOR_RESIZE) {
		int left = server->grab_box.x;
		int right = left + server->grab_box.width;
		int top = server->grab_box.y;
		int bottom = top + server->grab_box.height;
		int edge_x = (int)(server->cursor->x - server->grab_x);
		int edge_y = (int)(server->cursor->y - server->grab_y);
		if (server->resize_edges & WLR_EDGE_LEFT) left = edge_x;
		if (server->resize_edges & WLR_EDGE_RIGHT) right = edge_x;
		if (server->resize_edges & WLR_EDGE_TOP) top = edge_y;
		if (server->resize_edges & WLR_EDGE_BOTTOM) bottom = edge_y;
		int width = right - left;
		int height = bottom - top;
		if (width >= 40 && height >= 30) {
			wlr_scene_node_set_position(&server->grabbed->tree->node, left, top);
			wlr_xdg_toplevel_set_size(server->grabbed->xdg, width, height);
		}
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
		server->seat->keyboard_state.focused_surface != hit.toplevel->xdg->base->surface &&
		(server->config.auto_raise ||
			name_matches(&server->config.auto_raise_windows,
			hit.toplevel->xdg))) focus_toplevel(hit.toplevel);
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
	if (server->menu.tree != NULL) {
		if (event->state == WL_POINTER_BUTTON_STATE_RELEASED) {
			int selected = menu_item_at(server);
			struct wtwm_action action = {0};
			struct toplevel *target = server->menu.target;
			bool activate = selected >= 0 &&
				server->menu.definition->items[selected].action.type != WTWM_ACTION_TITLE;
			if (activate) action = server->menu.definition->items[selected].action;
			hide_menu(server);
			if (activate) execute_action(server, target, &action, 0);
		}
		return;
	}
	struct hit_result hit = desktop_at(server, server->cursor->x, server->cursor->y);
	if (event->state == WL_POINTER_BUTTON_STATE_RELEASED) {
		if (hit.surface != NULL)
			wlr_seat_pointer_notify_button(server->seat, event->time_msec,
				event->button, event->state);
		reset_cursor(server);
		return;
	}
	if (hit.toplevel != NULL) focus_toplevel(hit.toplevel);
	bool handled = false;
	if ((hit.left_button || hit.right_button) && event->button == BTN_LEFT) {
		const struct wtwm_action *configured = NULL;
		for (size_t i = 0; i < server->config.title_button_count; ++i) {
			if (server->config.title_buttons[i].right_side == hit.right_button) {
				configured = &server->config.title_buttons[i].action;
				break;
			}
		}
		if (configured != NULL) execute_action(server, hit.toplevel, configured, 0);
		else if (hit.left_button) {
			struct wtwm_action action = {.type = WTWM_ACTION_ICONIFY};
			execute_action(server, hit.toplevel, &action, 0);
		} else {
			begin_interactive(hit.toplevel, CURSOR_RESIZE,
				WLR_EDGE_RIGHT | WLR_EDGE_BOTTOM);
		}
		handled = true;
	}
	if (!handled) handled = dispatch_binding(server, WTWM_BINDING_BUTTON,
		twm_button(event->button), NULL, hit.context, hit.toplevel);
	if (!handled && hit.context == WTWM_CONTEXT_TITLE && event->button == BTN_LEFT) {
		begin_interactive(hit.toplevel, CURSOR_MOVE, 0);
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
	uint32_t keycode = event->keycode + 8;
	const xkb_keysym_t *symbols = NULL;
	int count = xkb_state_key_get_syms(keyboard->wlr->xkb_state, keycode, &symbols);
	bool handled = false;
	if (event->state == WL_KEYBOARD_KEY_STATE_PRESSED) {
		struct wlr_surface *focused = server->seat->keyboard_state.focused_surface;
		struct wlr_xdg_toplevel *xdg = focused ? wlr_xdg_toplevel_try_from_wlr_surface(focused) : NULL;
		struct toplevel *toplevel = xdg ?
			toplevel_from_scene_tree(xdg->base->data) : NULL;
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
	if (name_matches(&toplevel->server->config.start_iconified_windows,
			toplevel->xdg)) {
		toplevel->iconified = true;
		wlr_scene_node_set_enabled(&toplevel->tree->node, false);
		wlr_xdg_toplevel_set_suspended(toplevel->xdg, true);
	} else {
		wlr_xdg_toplevel_set_suspended(toplevel->xdg, false);
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
	if (server->menu.target == toplevel) hide_menu(server);
	if (had_pointer_focus) wlr_seat_pointer_clear_focus(server->seat);
	dismiss_toplevel_popups(toplevel);
	if (!toplevel->mapped) return;
	toplevel->mapped = false;
	wl_list_remove(&toplevel->link);
	wl_list_init(&toplevel->link);
	wlr_scene_node_set_enabled(&toplevel->tree->node, false);
	if (had_keyboard_focus) {
		wlr_seat_keyboard_clear_focus(server->seat);
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
	if (toplevel->xdg->base->initial_commit) {
		wlr_xdg_toplevel_set_size(toplevel->xdg, 0, 0);
		update_toplevel_metadata(toplevel, false);
	}
	struct wlr_box geometry;
	wlr_xdg_surface_get_geometry(toplevel->xdg->base, &geometry);
	if (geometry.width > 0) toplevel->width = geometry.width;
	if (geometry.height > 0) toplevel->height = geometry.height;
	update_decoration(toplevel);
}

static void toplevel_destroy(struct wl_listener *listener, void *data) {
	(void)data;
	struct toplevel *toplevel = wl_container_of(listener, toplevel, destroy);
	unmanage_toplevel(toplevel);
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
	begin_interactive(toplevel, CURSOR_MOVE, 0);
}

static void request_resize(struct wl_listener *listener, void *data) {
	struct toplevel *toplevel = wl_container_of(listener, toplevel, request_resize);
	struct wlr_xdg_toplevel_resize_event *event = data;
	begin_interactive(toplevel, CURSOR_RESIZE, event->edges);
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
	execute_action(toplevel->server, toplevel, &action, 0);
}

static void update_toplevel_metadata(struct toplevel *toplevel, bool title_changed) {
	if (title_changed) update_title_text(toplevel);
	set_decorated(toplevel, (!toplevel->server->config.no_title &&
		!name_matches(&toplevel->server->config.no_title_windows,
			toplevel->xdg)) ||
		name_matches(&toplevel->server->config.make_title_windows,
			toplevel->xdg));
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
	wl_list_init(&toplevel->link);
	toplevel->width = 640;
	toplevel->height = 480;
	toplevel->title_height = server->config.title_padding * 2 + 10;
	if (toplevel->title_height < 18) toplevel->title_height = 18;
	toplevel->decorated = !server->config.no_title;
	toplevel->tree = wlr_scene_tree_create(&server->scene->tree);
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
	update_title_text(toplevel);
	set_decorated(toplevel, toplevel->decorated);
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

static struct popup *popup_from_xdg(struct server *server,
	struct wlr_xdg_popup *xdg) {
	struct popup *popup;
	wl_list_for_each(popup, &server->popups, link) {
		if (popup->xdg == xdg) return popup;
	}
	return NULL;
}

static bool popup_parent_info(struct server *server, struct wlr_surface *surface,
	struct wlr_scene_tree **tree, struct toplevel **root, unsigned *depth) {
	struct wlr_xdg_surface *parent = wlr_xdg_surface_try_from_wlr_surface(surface);
	if (parent == NULL) return false;
	if (parent->role == WLR_XDG_SURFACE_ROLE_TOPLEVEL && parent->toplevel != NULL) {
		struct toplevel *toplevel = toplevel_from_xdg(parent->toplevel);
		if (toplevel == NULL || !toplevel->mapped ||
			parent->data != toplevel->content) return false;
		*tree = toplevel->content;
		*root = toplevel;
		*depth = 1;
		return true;
	}
	if (parent->role == WLR_XDG_SURFACE_ROLE_POPUP && parent->popup != NULL) {
		struct popup *popup = popup_from_xdg(server, parent->popup);
		if (popup == NULL || !popup->mapped || popup->root == NULL ||
			!popup->root->mapped || popup->tree == NULL || parent->data != popup->tree)
			return false;
		*tree = popup->tree;
		*root = popup->root;
		*depth = popup->depth + 1;
		return true;
	}
	return false;
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
	struct wlr_scene_tree *parent_tree = NULL;
	if (!popup_parent_info(server, xdg->parent, &parent_tree,
			&popup->root, &popup->depth)) {
		wlr_log(WLR_ERROR, "dismissing xdg popup with an unmanaged parent");
		free(popup);
		wlr_xdg_popup_destroy(xdg);
		return;
	}
	popup->tree = wlr_scene_xdg_surface_create(parent_tree, xdg->base);
	if (popup->tree == NULL) {
		free(popup);
		wlr_xdg_popup_destroy(xdg);
		return;
	}
	xdg->base->data = popup->tree;
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

static void test_write_state(struct test_control *control) {
	struct server *server = control->server;
	struct wlr_surface *focused = server->seat->keyboard_state.focused_surface;
	struct wlr_xdg_toplevel *focused_xdg = focused ?
		wlr_xdg_toplevel_try_from_wlr_surface(focused) : NULL;
	test_write(control, "OK STATE {\"frame\":%" PRIu64
		",\"animation_ms\":%u,\"placement_seed\":%u,"
		"\"cursor\":{\"x\":%.3f,\"y\":%.3f},\"focus\":",
		server->frame_sequence, control->animation_ms, server->placement_index,
		server->cursor->x, server->cursor->y);
	if (focused_xdg == NULL) test_write(control, "null");
	else test_write_json_string(control, focused_xdg->title);
	test_write(control, ",\"windows\":[");
	bool first = true;
	unsigned stack = 0;
	struct toplevel *toplevel;
	wl_list_for_each(toplevel, &server->toplevels, link) {
		if (!first) test_write(control, ",");
		first = false;
		test_write(control, "{\"title\":");
		test_write_json_string(control, toplevel->xdg->title);
		test_write(control, ",\"app_id\":");
		test_write_json_string(control, toplevel->xdg->app_id);
		test_write(control,
			",\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d,"
			"\"title_height\":%d,\"stack\":%u,\"mapped\":%s,\"iconified\":%s}",
			toplevel->tree->node.x, toplevel->tree->node.y,
			toplevel->width, toplevel->height, toplevel->title_height, stack++,
			toplevel->mapped ? "true" : "false",
			toplevel->iconified ? "true" : "false");
	}
	test_write(control, "],\"icons\":[");
	first = true;
	wl_list_for_each(toplevel, &server->toplevels, link) {
		if (!toplevel->iconified) continue;
		if (!first) test_write(control, ",");
		first = false;
		test_write_json_string(control, toplevel->xdg->title);
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
	test_write(control, "],\"interactive\":%s,\"menu\":",
		server->grabbed != NULL ? "true" : "false");
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
		test_write(control, "OK KEY %u %s\n", command->code,
			command->pressed ? "press" : "release");
		break;
	}
	case WTWM_TEST_COMMAND_STATE:
		test_write_state(control);
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
		wl_list_for_each(toplevel, &server->toplevels, link) update_title_text(toplevel);
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
	signal(SIGCHLD, SIG_IGN);
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
	wlr_compositor_create(server.display, 5, server.renderer);
	wlr_subcompositor_create(server.display);
	wlr_data_device_manager_create(server.display);
	server.output_layout = wlr_output_layout_create(server.display);
	wl_list_init(&server.outputs);
	server.new_output.notify = new_output;
	wl_signal_add(&server.backend->events.new_output, &server.new_output);
	server.scene = wlr_scene_create();
	server.scene_layout = wlr_scene_attach_output_layout(server.scene, server.output_layout);
	wl_list_init(&server.toplevels);
	wl_list_init(&server.popups);
	server.xdg_shell = wlr_xdg_shell_create(server.display, 3);
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
#ifdef WTWM_TEST_CONTROL
	static const struct wlr_keyboard_impl test_keyboard_impl = {
		.name = "wtwm-test-keyboard",
	};
	wlr_keyboard_init(&server.test_control.keyboard, &test_keyboard_impl,
		"wtwm-test-keyboard");
	server.test_control.keyboard_initialized = true;
	new_keyboard(&server, &server.test_control.keyboard.base);
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
	if (startup != NULL) spawn_shell(startup);
	wlr_log(WLR_INFO, "wtwm running on WAYLAND_DISPLAY=%s", socket);
	wl_display_run(server.display);
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
