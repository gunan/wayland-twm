/* SPDX-License-Identifier: MIT */
#ifndef WTWM_TEXT_H
#define WTWM_TEXT_H

#include <wtwm/xbm.h>

#include <stdbool.h>
#include <wlr/types/wlr_buffer.h>
#include <xcb/xcb.h>

/* Enable exact X core-font measurement/rasterization once Xwayland is ready. */
void wtwm_text_set_x11_connection(xcb_connection_t *connection);

/* Returns a referenced immutable ARGB buffer. The caller must wlr_buffer_drop(). */
struct wlr_buffer *wtwm_render_text(const char *text, const char *font,
	const float color[static 4], int *width, int *height);

/* Return exact core-font metrics when available, otherwise Pango metrics. */
bool wtwm_measure_font_metrics(const char *font, int *height, int *ascent);
int wtwm_measure_font_height(const char *font);

/* Monochrome compositor-owned assets, returned with one caller reference. */
struct wlr_buffer *wtwm_render_pattern(int width, int height,
	const unsigned char *bits, unsigned int pattern_width,
	unsigned int pattern_height, const float foreground[static 4],
	const float background[static 4]);
struct wlr_buffer *wtwm_render_xbm_cursor(const struct wtwm_xbm *source,
	const struct wtwm_xbm *mask, const float foreground[static 4],
	const float background[static 4]);
struct wlr_buffer *wtwm_render_xbm_title(const struct wtwm_xbm *bitmap,
	int size, const float foreground[static 4]);
struct wlr_buffer *wtwm_render_builtin_title(const char *name, int size,
	const float foreground[static 4]);

#endif
