/* SPDX-License-Identifier: MIT */
#ifndef WTWM_COLOR_H
#define WTWM_COLOR_H

#include <stdbool.h>
#include <stdint.h>

struct wtwm_color {
	uint16_t red;
	uint16_t green;
	uint16_t blue;
};

/* Parse X11 numeric color forms without consulting an X server color database. */
bool wtwm_color_parse_literal(const char *name, struct wtwm_color *color);

/* Convert X11's 16-bit channels to wlroots' normalized scene color. */
void wtwm_color_to_float(const struct wtwm_color *color, float result[static 4]);

/* Match twm's integer, channel-by-channel InterpolateMenuColors arithmetic. */
struct wtwm_color wtwm_color_interpolate(struct wtwm_color first,
	struct wtwm_color last, unsigned index, unsigned steps);

/* Deterministic Wayland translations for GrayScale and Monochrome visuals. */
struct wtwm_color wtwm_color_grayscale(struct wtwm_color color);
struct wtwm_color wtwm_color_monochrome(struct wtwm_color color);

#endif
