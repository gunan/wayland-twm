/* SPDX-License-Identifier: MIT */
#include <wtwm/geometry.h>

#include <limits.h>
#include <stddef.h>
#include <stdint.h>

static int clamp_dimension(int value) {
	return value > 0 ? value : 1;
}

static int clamp_nonnegative(int value) {
	return value > 0 ? value : 0;
}

static int saturate_int(int64_t value) {
	if (value > INT_MAX) return INT_MAX;
	if (value < INT_MIN) return INT_MIN;
	return (int)value;
}

int wtwm_title_bar_height(int font_height, int frame_padding) {
	int64_t height = clamp_dimension(font_height);
	height += (int64_t)2 * clamp_nonnegative(frame_padding);
	if ((height & 1) == 0) ++height;
	return saturate_int(height);
}

void wtwm_frame_geometry(int client_width, int client_height, int border_width,
		int title_bar_height, bool has_title,
		struct wtwm_frame_geometry *geometry) {
	client_width = clamp_dimension(client_width);
	client_height = clamp_dimension(client_height);
	border_width = clamp_nonnegative(border_width);
	title_bar_height = has_title ? clamp_dimension(title_bar_height) : 0;
	int title_extent = has_title ?
		saturate_int((int64_t)title_bar_height + border_width) : 0;
	int frame_height = saturate_int((int64_t)client_height + title_extent);
	geometry->client_width = client_width;
	geometry->client_height = client_height;
	geometry->border_width = border_width;
	geometry->title_bar_height = title_bar_height;
	geometry->title_extent = title_extent;
	geometry->frame_width = client_width;
	geometry->frame_height = frame_height;
	geometry->outer_width = saturate_int((int64_t)client_width + 2 * border_width);
	geometry->outer_height = saturate_int((int64_t)frame_height + 2 * border_width);
	geometry->content_x = border_width;
	geometry->content_y = saturate_int((int64_t)border_width + title_extent);
}

static void finish_position(const struct wtwm_frame_geometry *geometry,
		struct wtwm_window_position *position) {
	position->client_x = saturate_int((int64_t)position->frame_x +
		geometry->content_x);
	position->client_y = saturate_int((int64_t)position->frame_y +
		geometry->content_y);
}

void wtwm_initial_window_position(int requested_x, int requested_y,
		int original_client_border, const struct wtwm_frame_geometry *geometry,
		bool use_client_border_width, int gravity_x, int gravity_y,
		struct wtwm_window_position *position) {
	original_client_border = clamp_nonnegative(original_client_border);
	int border_delta = use_client_border_width ? 0 :
		original_client_border - geometry->border_width;
	int64_t adjusted_x = (int64_t)requested_x + gravity_x * border_delta;
	int64_t adjusted_y = (int64_t)requested_y + gravity_y * border_delta;
	if (gravity_y < 0)
		adjusted_y -= (int64_t)gravity_y * geometry->title_extent;
	position->frame_x = saturate_int(adjusted_x + original_client_border -
		geometry->border_width);
	position->frame_y = saturate_int(adjusted_y - geometry->title_extent +
		original_client_border - geometry->border_width);
	finish_position(geometry, position);
}

void wtwm_configure_request_position(int current_frame_x, int current_frame_y,
		int requested_x, int requested_y, bool has_x, bool has_y,
		const struct wtwm_frame_geometry *geometry, int gravity_y,
		struct wtwm_window_position *position) {
	position->frame_x = has_x ? saturate_int((int64_t)requested_x -
		geometry->border_width) : current_frame_x;
	position->frame_y = has_y ? saturate_int((int64_t)requested_y -
		(gravity_y < 0 ? 0 : geometry->title_extent) -
		geometry->border_width) : current_frame_y;
	finish_position(geometry, position);
}

static int minimum(int first, int second) {
	return first < second ? first : second;
}

static int multiple_toward_zero(int64_t value, int increment) {
	if (increment == 1) return saturate_int(value);
	return saturate_int(value / increment * increment);
}

void wtwm_constrain_size(const struct wtwm_size_hints *hints,
		int limit_width, int limit_height, int *width, int *height) {
	struct wtwm_size_hints empty = {0};
	if (hints == NULL) hints = &empty;
	limit_width = clamp_dimension(limit_width);
	limit_height = clamp_dimension(limit_height);

	bool has_min = (hints->flags & WTWM_SIZE_HINT_MIN) != 0;
	bool has_max = (hints->flags & WTWM_SIZE_HINT_MAX) != 0;
	bool has_base = (hints->flags & WTWM_SIZE_HINT_BASE) != 0;
	bool has_increment = (hints->flags & WTWM_SIZE_HINT_INCREMENT) != 0;
	int min_width = has_min ? hints->min_width :
		(has_base ? hints->base_width : 1);
	int min_height = has_min ? hints->min_height :
		(has_base ? hints->base_height : 1);
	int base_width = has_base ? hints->base_width :
		(has_min ? hints->min_width : 0);
	int base_height = has_base ? hints->base_height :
		(has_min ? hints->min_height : 0);
	int max_width = has_max ? minimum(limit_width, hints->max_width) : limit_width;
	int max_height = has_max ? minimum(limit_height, hints->max_height) : limit_height;
	int width_increment = has_increment && hints->width_increment > 0 ?
		hints->width_increment : 1;
	int height_increment = has_increment && hints->height_increment > 0 ?
		hints->height_increment : 1;
	int constrained_width = *width;
	int constrained_height = *height;

	if (constrained_width < min_width) constrained_width = min_width;
	if (constrained_height < min_height) constrained_height = min_height;
	if (constrained_width > max_width) constrained_width = max_width;
	if (constrained_height > max_height) constrained_height = max_height;

	constrained_width = saturate_int(
		(int64_t)multiple_toward_zero((int64_t)constrained_width - base_width,
			width_increment) + base_width);
	constrained_height = saturate_int(
		(int64_t)multiple_toward_zero((int64_t)constrained_height - base_height,
			height_increment) + base_height);

	if ((hints->flags & WTWM_SIZE_HINT_ASPECT) != 0 &&
			hints->min_aspect_x > 0 && hints->min_aspect_y > 0 &&
			hints->max_aspect_x > 0 && hints->max_aspect_y > 0) {
		if ((int64_t)hints->min_aspect_x * constrained_height >
				(int64_t)hints->min_aspect_y * constrained_width) {
			int delta = multiple_toward_zero(
				(int64_t)hints->min_aspect_x * constrained_height /
					hints->min_aspect_y - constrained_width,
				width_increment);
			if ((int64_t)constrained_width + delta <= max_width) {
				constrained_width += delta;
			} else {
				delta = multiple_toward_zero(
					(int64_t)constrained_height -
						(int64_t)constrained_width * hints->min_aspect_y /
							hints->min_aspect_x,
					height_increment);
				if ((int64_t)constrained_height - delta >= min_height)
					constrained_height -= delta;
			}
		}

		if ((int64_t)hints->max_aspect_x * constrained_height <
				(int64_t)hints->max_aspect_y * constrained_width) {
			int delta = multiple_toward_zero(
				(int64_t)constrained_width * hints->max_aspect_y /
					hints->max_aspect_x - constrained_height,
				height_increment);
			if ((int64_t)constrained_height + delta <= max_height) {
				constrained_height += delta;
			} else {
				delta = multiple_toward_zero(
					(int64_t)constrained_width -
						(int64_t)hints->max_aspect_x * constrained_height /
							hints->max_aspect_y,
					width_increment);
				if ((int64_t)constrained_width - delta >= min_width)
					constrained_width -= delta;
			}
		}
	}

	*width = clamp_dimension(constrained_width);
	*height = clamp_dimension(constrained_height);
}
