/* SPDX-License-Identifier: MIT */
#ifndef WTWM_TEXT_H
#define WTWM_TEXT_H

#include <wlr/types/wlr_buffer.h>

/* Returns a referenced immutable ARGB buffer. The caller must wlr_buffer_drop(). */
struct wlr_buffer *wtwm_render_text(const char *text, const char *font,
	const float color[static 4], int *width, int *height);

#endif
