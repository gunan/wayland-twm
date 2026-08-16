/* SPDX-License-Identifier: MIT */
#ifndef WTWM_FONT_H
#define WTWM_FONT_H

#include <stddef.h>

/* Large enough for every description produced from a supported XLFD name. */
#define WTWM_PANGO_FONT_DESCRIPTION_MAX 1089

/* Return an exact X core bitmap-font height, or zero for a scalable font. */
int wtwm_x11_bitmap_font_height(const char *font);

/*
 * Translate X core aliases and complete XLFD names into practical Pango names.
 *
 * The result is always NUL-terminated when description is non-NULL and
 * capacity is nonzero.  The return value is the required length excluding that
 * terminator, so callers may first query with a NULL destination and zero
 * capacity.  Invalid XLFD names map to the deterministic fallback rather than
 * being passed to Pango.
 */
size_t wtwm_pango_font_description(const char *font, char *description,
	size_t capacity);

#endif
