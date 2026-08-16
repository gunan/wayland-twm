/* SPDX-License-Identifier: MIT */
#define WLR_USE_UNSTABLE

#include "text.h"
#include <wtwm/font.h>

#include <drm_fourcc.h>
#include <pango/pangocairo.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <wlr/interfaces/wlr_buffer.h>

struct text_buffer {
	struct wlr_buffer base;
	uint32_t *pixels;
	size_t stride;
};

static struct text_buffer *from_buffer(struct wlr_buffer *buffer) {
	return (struct text_buffer *)buffer;
}

static PangoFontDescription *font_description(const char *font) {
	size_t length = wtwm_pango_font_description(font, NULL, 0);
	if (length == SIZE_MAX) return NULL;
	char *text = malloc(length + 1);
	if (text == NULL) return NULL;
	(void)wtwm_pango_font_description(font, text, length + 1);
	PangoFontDescription *description =
		pango_font_description_from_string(text);
	free(text);
	return description;
}

static void text_destroy(struct wlr_buffer *buffer) {
	struct text_buffer *text = from_buffer(buffer);
	free(text->pixels);
	free(text);
}

static bool text_begin_access(struct wlr_buffer *buffer, uint32_t flags,
	void **data, uint32_t *format, size_t *stride) {
	if (flags & WLR_BUFFER_DATA_PTR_ACCESS_WRITE) return false;
	struct text_buffer *text = from_buffer(buffer);
	*data = text->pixels;
	*format = DRM_FORMAT_ARGB8888;
	*stride = text->stride;
	return true;
}

static void text_end_access(struct wlr_buffer *buffer) {
	(void)buffer;
}

static const struct wlr_buffer_impl text_impl = {
	.destroy = text_destroy,
	.begin_data_ptr_access = text_begin_access,
	.end_data_ptr_access = text_end_access,
};

int wtwm_measure_font_height(const char *font) {
	int bitmap_height = wtwm_x11_bitmap_font_height(font);
	if (bitmap_height > 0) return bitmap_height;
	cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1, 1);
	cairo_t *cairo = cairo_create(surface);
	PangoLayout *layout = pango_cairo_create_layout(cairo);
	PangoFontDescription *description = font_description(font);
	if (description == NULL) {
		g_object_unref(layout);
		cairo_destroy(cairo);
		cairo_surface_destroy(surface);
		return 1;
	}
	pango_layout_set_font_description(layout, description);
	/* Logical line height is independent of the title's particular glyphs. */
	pango_layout_set_text(layout, "Mg", -1);
	int width = 0, height = 0;
	pango_layout_get_pixel_size(layout, &width, &height);
	(void)width;
	pango_font_description_free(description);
	g_object_unref(layout);
	cairo_destroy(cairo);
	cairo_surface_destroy(surface);
	return height > 0 ? height : 1;
}

struct wlr_buffer *wtwm_render_text(const char *value, const char *font,
	const float color[static 4], int *width, int *height) {
	const char *text = value ? value : "";
	cairo_surface_t *measure_surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1, 1);
	cairo_t *measure = cairo_create(measure_surface);
	PangoLayout *layout = pango_cairo_create_layout(measure);
	PangoFontDescription *description = font_description(font);
	if (description == NULL) {
		g_object_unref(layout);
		cairo_destroy(measure);
		cairo_surface_destroy(measure_surface);
		return NULL;
	}
	pango_layout_set_font_description(layout, description);
	pango_layout_set_text(layout, text, -1);
	int text_width = 0, text_height = 0;
	pango_layout_get_pixel_size(layout, &text_width, &text_height);
	if (text_width < 1) text_width = 1;
	if (text_height < 1) text_height = 1;
	g_object_unref(layout);
	cairo_destroy(measure);
	cairo_surface_destroy(measure_surface);

	struct text_buffer *buffer = calloc(1, sizeof(*buffer));
	if (buffer == NULL) {
		pango_font_description_free(description);
		return NULL;
	}
	buffer->stride = (size_t)cairo_format_stride_for_width(CAIRO_FORMAT_ARGB32, text_width);
	buffer->pixels = calloc((size_t)text_height, buffer->stride);
	if (buffer->pixels == NULL) {
		pango_font_description_free(description);
		free(buffer);
		return NULL;
	}
	wlr_buffer_init(&buffer->base, &text_impl, text_width, text_height);
	cairo_surface_t *surface = cairo_image_surface_create_for_data(
		(unsigned char *)buffer->pixels, CAIRO_FORMAT_ARGB32,
		text_width, text_height, (int)buffer->stride);
	cairo_t *cairo = cairo_create(surface);
	cairo_set_operator(cairo, CAIRO_OPERATOR_SOURCE);
	cairo_set_source_rgba(cairo, 0, 0, 0, 0);
	cairo_paint(cairo);
	cairo_set_operator(cairo, CAIRO_OPERATOR_OVER);
	cairo_set_source_rgba(cairo, color[0], color[1], color[2], color[3]);
	layout = pango_cairo_create_layout(cairo);
	pango_layout_set_font_description(layout, description);
	pango_layout_set_text(layout, text, -1);
	pango_cairo_show_layout(cairo, layout);
	g_object_unref(layout);
	pango_font_description_free(description);
	cairo_destroy(cairo);
	cairo_surface_flush(surface);
	cairo_surface_destroy(surface);
	*width = text_width;
	*height = text_height;
	return &buffer->base;
}
