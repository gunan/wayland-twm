/* SPDX-License-Identifier: MIT */
#define WLR_USE_UNSTABLE

#include "text.h"
#include <wtwm/font.h>

#include <drm_fourcc.h>
#include <pango/pangocairo.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <wlr/interfaces/wlr_buffer.h>
#include <xcb/xcb.h>

struct text_buffer {
	struct wlr_buffer base;
	uint32_t *pixels;
	size_t stride;
};

static xcb_connection_t *x11_connection;
static const struct wlr_buffer_impl text_impl;

static struct text_buffer *from_buffer(struct wlr_buffer *buffer) {
	return (struct text_buffer *)buffer;
}

static struct text_buffer *pixel_buffer_create(int width, int height) {
	if (width < 1 || height < 1) return NULL;
	struct text_buffer *buffer = calloc(1, sizeof(*buffer));
	if (buffer == NULL) return NULL;
	buffer->stride = (size_t)cairo_format_stride_for_width(
		CAIRO_FORMAT_ARGB32, width);
	if ((size_t)height > SIZE_MAX / buffer->stride) {
		free(buffer);
		return NULL;
	}
	buffer->pixels = calloc((size_t)height, buffer->stride);
	if (buffer->pixels == NULL) {
		free(buffer);
		return NULL;
	}
	wlr_buffer_init(&buffer->base, &text_impl, width, height);
	return buffer;
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

void wtwm_text_set_x11_connection(xcb_connection_t *connection) {
	x11_connection = connection;
}

struct core_font {
	xcb_font_t id;
	xcb_query_font_reply_t *metrics;
};

static bool core_font_open(const char *name, struct core_font *font) {
	if (x11_connection == NULL || font == NULL) return false;
	if (name == NULL || name[0] == '\0') name = "fixed";
	for (unsigned attempt = 0; attempt < 2; ++attempt) {
		const char *candidate = attempt == 0 ? name : "fixed";
		if (attempt == 1 && strcmp(name, "fixed") == 0) break;
		xcb_font_t id = xcb_generate_id(x11_connection);
		xcb_void_cookie_t open = xcb_open_font_checked(x11_connection, id,
			(uint16_t)strlen(candidate), candidate);
		xcb_generic_error_t *error = xcb_request_check(x11_connection, open);
		if (error != NULL) {
			free(error);
			continue;
		}
		xcb_query_font_reply_t *metrics = xcb_query_font_reply(x11_connection,
			xcb_query_font(x11_connection, id), NULL);
		if (metrics != NULL) {
			*font = (struct core_font){id, metrics};
			return true;
		}
		xcb_close_font(x11_connection, id);
	}
	return false;
}

static void core_font_close(struct core_font *font) {
	if (font == NULL || font->metrics == NULL) return;
	xcb_close_font(x11_connection, font->id);
	free(font->metrics);
	font->metrics = NULL;
}

static bool ascii_text(const char *text) {
	for (const unsigned char *cursor = (const unsigned char *)text;
			*cursor != '\0'; ++cursor)
		if (*cursor >= 0x80) return false;
	return true;
}

static xcb_query_text_extents_reply_t *core_text_extents(xcb_font_t font,
		const char *text, size_t length) {
	if (length > UINT32_MAX || length > SIZE_MAX / sizeof(xcb_char2b_t))
		return NULL;
	xcb_char2b_t *characters = calloc(length > 0 ? length : 1,
		sizeof(*characters));
	if (characters == NULL) return NULL;
	for (size_t i = 0; i < length; ++i)
		characters[i].byte2 = (uint8_t)text[i];
	xcb_query_text_extents_reply_t *reply = xcb_query_text_extents_reply(
		x11_connection, xcb_query_text_extents(x11_connection, font,
			(uint32_t)length, characters), NULL);
	free(characters);
	return reply;
}

bool wtwm_measure_font_metrics(const char *font, int *height, int *ascent) {
	if (height == NULL || ascent == NULL) return false;
	struct core_font core = {0};
	if (core_font_open(font, &core)) {
		int measured_ascent = core.metrics->font_ascent;
		int measured_descent = core.metrics->font_descent;
		if (measured_ascent < 0) measured_ascent = 0;
		if (measured_descent < 0) measured_descent = 0;
		*height = measured_ascent + measured_descent;
		*ascent = measured_ascent;
		core_font_close(&core);
		if (*height < 1) *height = 1;
		return true;
	}
	int bitmap_height = wtwm_x11_bitmap_font_height(font);
	if (bitmap_height > 0) {
		*height = bitmap_height;
		*ascent = bitmap_height > 2 ? bitmap_height - 2 : bitmap_height;
		return true;
	}
	cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1, 1);
	cairo_t *cairo = cairo_create(surface);
	PangoLayout *layout = pango_cairo_create_layout(cairo);
	PangoFontDescription *description = font_description(font);
	if (description == NULL) {
		g_object_unref(layout);
		cairo_destroy(cairo);
		cairo_surface_destroy(surface);
		*height = *ascent = 1;
		return false;
	}
	pango_layout_set_font_description(layout, description);
	pango_layout_set_text(layout, "Mg", -1);
	int width = 0;
	pango_layout_get_pixel_size(layout, &width, height);
	*ascent = pango_layout_get_baseline(layout) / PANGO_SCALE;
	(void)width;
	pango_font_description_free(description);
	g_object_unref(layout);
	cairo_destroy(cairo);
	cairo_surface_destroy(surface);
	if (*height < 1) *height = 1;
	if (*ascent < 0) *ascent = 0;
	if (*ascent > *height) *ascent = *height;
	return true;
}

int wtwm_measure_font_height(const char *font) {
	int height = 1;
	int ascent = 1;
	(void)wtwm_measure_font_metrics(font, &height, &ascent);
	return height;
}

static unsigned char color_channel(float value) {
	if (value <= 0.0f) return 0;
	if (value >= 1.0f) return 255;
	return (unsigned char)(value * 255.0f + 0.5f);
}

static uint32_t color_pixel(const float color[static 4]) {
	unsigned char alpha = color_channel(color[3]);
	unsigned char red = color_channel(color[0]);
	unsigned char green = color_channel(color[1]);
	unsigned char blue = color_channel(color[2]);
	red = (unsigned char)(((unsigned)red * alpha + 127u) / 255u);
	green = (unsigned char)(((unsigned)green * alpha + 127u) / 255u);
	blue = (unsigned char)(((unsigned)blue * alpha + 127u) / 255u);
	return (uint32_t)alpha << 24 | (uint32_t)red << 16 |
		(uint32_t)green << 8 | blue;
}

static struct wlr_buffer *render_core_text(const char *text, const char *font,
		const float color[static 4], int *width, int *height) {
	if (x11_connection == NULL || !ascii_text(text)) return NULL;
	struct core_font core = {0};
	if (!core_font_open(font, &core)) return NULL;
	size_t length = strlen(text);
	xcb_query_text_extents_reply_t *extents =
		core_text_extents(core.id, text, length);
	if (extents == NULL) {
		core_font_close(&core);
		return NULL;
	}
	int text_width = extents->overall_width;
	if (text_width < 1) text_width = 1;
	int text_height = core.metrics->font_ascent + core.metrics->font_descent;
	if (text_height < 1) text_height = 1;
	if (text_width > UINT16_MAX || text_height > UINT16_MAX) {
		free(extents);
		core_font_close(&core);
		return NULL;
	}
	const xcb_setup_t *setup = xcb_get_setup(x11_connection);
	xcb_screen_iterator_t screens = xcb_setup_roots_iterator(setup);
	if (screens.rem == 0) {
		free(extents);
		core_font_close(&core);
		return NULL;
	}
	xcb_pixmap_t pixmap = xcb_generate_id(x11_connection);
	xcb_create_pixmap(x11_connection, 1, pixmap, screens.data->root,
		(uint16_t)text_width, (uint16_t)text_height);
	xcb_gcontext_t gc = xcb_generate_id(x11_connection);
	uint32_t gc_values[] = {0, 0, core.id};
	xcb_create_gc(x11_connection, gc, pixmap,
		XCB_GC_FOREGROUND | XCB_GC_BACKGROUND | XCB_GC_FONT, gc_values);
	xcb_rectangle_t rectangle = {0, 0, (uint16_t)text_width,
		(uint16_t)text_height};
	xcb_poly_fill_rectangle(x11_connection, pixmap, gc, 1, &rectangle);
	uint32_t foreground = 1;
	xcb_change_gc(x11_connection, gc, XCB_GC_FOREGROUND, &foreground);
	int16_t x = 0;
	for (size_t offset = 0; offset < length;) {
		size_t remaining = length - offset;
		uint8_t chunk = remaining > 255 ? 255 : (uint8_t)remaining;
		xcb_image_text_8(x11_connection, chunk, pixmap, gc, x,
			(int16_t)core.metrics->font_ascent, text + offset);
		xcb_query_text_extents_reply_t *part =
			core_text_extents(core.id, text + offset, chunk);
		if (part == NULL) break;
		x = (int16_t)(x + part->overall_width);
		free(part);
		offset += chunk;
	}
	xcb_get_image_reply_t *image = xcb_get_image_reply(x11_connection,
		xcb_get_image(x11_connection, XCB_IMAGE_FORMAT_Z_PIXMAP, pixmap,
			0, 0, (uint16_t)text_width, (uint16_t)text_height, UINT32_MAX), NULL);
	xcb_free_gc(x11_connection, gc);
	xcb_free_pixmap(x11_connection, pixmap);
	free(extents);
	core_font_close(&core);
	if (image == NULL) return NULL;
	struct text_buffer *buffer = pixel_buffer_create(text_width, text_height);
	if (buffer == NULL) {
		free(image);
		return NULL;
	}
	const uint8_t *data = xcb_get_image_data(image);
	int data_length = xcb_get_image_data_length(image);
	size_t source_stride = text_height > 0 ?
		(size_t)data_length / (size_t)text_height : 0;
	uint32_t pixel = color_pixel(color);
	for (int y = 0; y < text_height; ++y)
		for (int px = 0; px < text_width; ++px) {
			size_t byte = (size_t)y * source_stride + (size_t)px / 8;
			if (byte >= (size_t)data_length) continue;
			unsigned bit = setup->bitmap_format_bit_order == XCB_IMAGE_ORDER_LSB_FIRST ?
				(unsigned)px & 7u : 7u - ((unsigned)px & 7u);
			if ((data[byte] & (1u << bit)) != 0)
				buffer->pixels[(size_t)y * buffer->stride / 4u + (size_t)px] = pixel;
		}
	free(image);
	*width = text_width;
	*height = text_height;
	return &buffer->base;
}

struct wlr_buffer *wtwm_render_text(const char *value, const char *font,
	const float color[static 4], int *width, int *height) {
	const char *text = value ? value : "";
	struct wlr_buffer *core = render_core_text(text, font, color, width, height);
	if (core != NULL) return core;
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

	struct text_buffer *buffer = pixel_buffer_create(text_width, text_height);
	if (buffer == NULL) {
		pango_font_description_free(description);
		return NULL;
	}
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

struct wlr_buffer *wtwm_render_pattern(int width, int height,
		const unsigned char *bits, unsigned int pattern_width,
		unsigned int pattern_height, const float foreground[static 4],
		const float background[static 4]) {
	if (bits == NULL || pattern_width == 0 || pattern_height == 0) return NULL;
	struct text_buffer *buffer = pixel_buffer_create(width, height);
	if (buffer == NULL) return NULL;
	size_t pattern_stride = ((size_t)pattern_width + 7u) / 8u;
	uint32_t foreground_pixel = color_pixel(foreground);
	uint32_t background_pixel = color_pixel(background);
	for (int y = 0; y < height; ++y)
		for (int x = 0; x < width; ++x) {
			size_t byte = (size_t)((unsigned)y % pattern_height) * pattern_stride +
				((unsigned)x % pattern_width) / 8u;
			unsigned bit = (unsigned)x % pattern_width % 8u;
			buffer->pixels[(size_t)y * buffer->stride / 4u + (size_t)x] =
				(bits[byte] & (1u << bit)) != 0 ? foreground_pixel :
				background_pixel;
		}
	return &buffer->base;
}

struct wlr_buffer *wtwm_render_argb_icon(int width, int height,
		const uint32_t *pixels) {
	if (pixels == NULL || width < 1 || height < 1) return NULL;
	if ((size_t)width > SIZE_MAX / (size_t)height) return NULL;
	struct text_buffer *buffer = pixel_buffer_create(width, height);
	if (buffer == NULL) return NULL;
	for (int y = 0; y < height; ++y)
		for (int x = 0; x < width; ++x) {
			uint32_t source = pixels[(size_t)y * (size_t)width + (size_t)x];
			unsigned alpha = source >> 24;
			unsigned red = (source >> 16) & 0xffu;
			unsigned green = (source >> 8) & 0xffu;
			unsigned blue = source & 0xffu;
			red = (red * alpha + 127u) / 255u;
			green = (green * alpha + 127u) / 255u;
			blue = (blue * alpha + 127u) / 255u;
			buffer->pixels[(size_t)y * buffer->stride / 4u + (size_t)x] =
				alpha << 24 | red << 16 | green << 8 | blue;
		}
	return &buffer->base;
}

static bool xbm_bit(const struct wtwm_xbm *xbm, unsigned x, unsigned y) {
	if (xbm == NULL || x >= xbm->width || y >= xbm->height) return false;
	return (xbm->data[(size_t)y * xbm->stride + x / 8u] &
		(1u << (x & 7u))) != 0;
}

struct wlr_buffer *wtwm_render_xbm_cursor(const struct wtwm_xbm *source,
		const struct wtwm_xbm *mask, const float foreground[static 4],
		const float background[static 4]) {
	if (source == NULL || source->width == 0 || source->height == 0) return NULL;
	if (mask != NULL && (mask->width != source->width ||
		mask->height != source->height)) return NULL;
	struct text_buffer *buffer = pixel_buffer_create((int)source->width,
		(int)source->height);
	if (buffer == NULL) return NULL;
	uint32_t foreground_pixel = color_pixel(foreground);
	uint32_t background_pixel = color_pixel(background);
	for (unsigned y = 0; y < source->height; ++y)
		for (unsigned x = 0; x < source->width; ++x) {
			bool source_set = xbm_bit(source, x, y);
			bool mask_set = mask == NULL || xbm_bit(mask, x, y);
			uint32_t pixel = !mask_set ? 0 :
				(source_set ? foreground_pixel : background_pixel);
			buffer->pixels[(size_t)y * buffer->stride / 4u + x] = pixel;
		}
	return &buffer->base;
}

struct wlr_buffer *wtwm_render_xbm_title(const struct wtwm_xbm *bitmap,
		int size, const float foreground[static 4]) {
	if (bitmap == NULL || size < 1) return NULL;
	struct text_buffer *buffer = pixel_buffer_create(size, size);
	if (buffer == NULL) return NULL;
	uint32_t pixel = color_pixel(foreground);
	int destination_x = (size - (int)bitmap->width + 1) / 2;
	int destination_y = (size - (int)bitmap->height + 1) / 2;
	for (unsigned y = 0; y < bitmap->height; ++y)
		for (unsigned x = 0; x < bitmap->width; ++x) {
			int target_x = destination_x + (int)x;
			int target_y = destination_y + (int)y;
			if (target_x < 0 || target_y < 0 || target_x >= size ||
				target_y >= size || !xbm_bit(bitmap, x, y)) continue;
			buffer->pixels[(size_t)target_y * buffer->stride / 4u +
				(size_t)target_x] = pixel;
		}
	return &buffer->base;
}

static void set_title_pixel(struct text_buffer *buffer, int x, int y,
		uint32_t pixel) {
	if (x < 0 || y < 0 || x >= buffer->base.width || y >= buffer->base.height)
		return;
	buffer->pixels[(size_t)y * buffer->stride / 4u + (size_t)x] = pixel;
}

struct wlr_buffer *wtwm_render_builtin_title(const char *name, int size,
		const float foreground[static 4]) {
	if (name == NULL || size < 1 || name[0] != ':') return NULL;
	struct text_buffer *buffer = pixel_buffer_create(size, size);
	if (buffer == NULL) return NULL;
	uint32_t pixel = color_pixel(foreground);
	if (strcasecmp(name, ":dot") == 0 || strcasecmp(name, ":iconify") == 0) {
		int diameter = size * 3 / 4;
		if (diameter < 1) diameter = 1;
		if ((diameter & 1) == 0) --diameter;
		int radius = diameter / 2;
		int center = size / 2;
		for (int y = -radius; y <= radius; ++y)
			for (int x = -radius; x <= radius; ++x)
				if (x * x + y * y <= radius * radius + radius)
					set_title_pixel(buffer, center + x, center + y, pixel);
	} else if (strcasecmp(name, ":resize") == 0) {
		int outer = size * 2 / 3;
		int inner = outer / 2;
		for (int i = 0; i <= outer; ++i) {
			set_title_pixel(buffer, outer, i, pixel);
			set_title_pixel(buffer, i, outer, pixel);
		}
		for (int i = 0; i <= inner; ++i) {
			set_title_pixel(buffer, inner, i, pixel);
			set_title_pixel(buffer, i, inner, pixel);
		}
	} else if (strcasecmp(name, ":menu") == 0) {
		for (int y = size / 4; y <= size * 3 / 4; y += size > 5 ? 3 : 2)
			for (int x = 1; x < size - 1; ++x)
				set_title_pixel(buffer, x, y, pixel);
	} else if (strcasecmp(name, ":xlogo") == 0 ||
			strcasecmp(name, ":delete") == 0) {
		for (int i = 0; i < size; ++i) {
			set_title_pixel(buffer, i, i, pixel);
			set_title_pixel(buffer, size - i - 1, i, pixel);
		}
	} else {
		static const unsigned char question[] = {
			0x38, 0x7c, 0x64, 0x30, 0x18, 0x00, 0x18, 0x18,
		};
		int origin_x = (size - 8 + 1) / 2;
		int origin_y = (size - 8 + 1) / 2;
		for (int y = 0; y < 8; ++y)
			for (int x = 0; x < 8; ++x)
				if ((question[y] & (1u << x)) != 0)
					set_title_pixel(buffer, origin_x + x, origin_y + y, pixel);
	}
	return &buffer->base;
}
