/* SPDX-License-Identifier: MIT */
#ifndef WTWM_FONT_H
#define WTWM_FONT_H

/* Return an exact X core bitmap-font height, or zero for a scalable font. */
int wtwm_x11_bitmap_font_height(const char *font);

/* Translate the X core aliases used by twm into practical Pango names. */
const char *wtwm_pango_font_description(const char *font);

#endif
