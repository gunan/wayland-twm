/* SPDX-License-Identifier: MIT */
#include <wtwm/visual.h>

#include <limits.h>
#include <stddef.h>
#include <stdint.h>

static int saturate_int(int64_t value) {
	if (value > INT_MAX) return INT_MAX;
	if (value < INT_MIN) return INT_MIN;
	return (int)value;
}

static int nonnegative(int value) {
	return value > 0 ? value : 0;
}

static int positive(int value) {
	return value > 0 ? value : 1;
}

static int bounded_ascent(int ascent, int height) {
	if (ascent < 0) return 0;
	return ascent > height ? height : ascent;
}

static struct wtwm_visual_config normalized_config(
		const struct wtwm_visual_config *config) {
	struct wtwm_visual_config normalized = config != NULL ? *config :
		wtwm_visual_config_defaults();
	normalized.border_width = nonnegative(normalized.border_width);
	normalized.frame_padding = nonnegative(normalized.frame_padding);
	normalized.title_padding = nonnegative(normalized.title_padding);
	normalized.button_indent = nonnegative(normalized.button_indent);
	normalized.title_button_border_width =
		nonnegative(normalized.title_button_border_width);
	normalized.menu_border_width = nonnegative(normalized.menu_border_width);
	return normalized;
}

struct wtwm_visual_config wtwm_visual_config_defaults(void) {
	return (struct wtwm_visual_config){
		.border_width = WTWM_VISUAL_DEFAULT_BORDER_WIDTH,
		.frame_padding = WTWM_VISUAL_DEFAULT_FRAME_PADDING,
		.title_padding = WTWM_VISUAL_DEFAULT_TITLE_PADDING,
		.button_indent = WTWM_VISUAL_DEFAULT_BUTTON_INDENT,
		.title_button_border_width =
			WTWM_VISUAL_DEFAULT_TITLE_BUTTON_BORDER_WIDTH,
		.menu_border_width = WTWM_VISUAL_DEFAULT_MENU_BORDER_WIDTH,
		.menu_shadows = true,
	};
}

static struct wtwm_visual_box outline_line_box(int64_t x1, int64_t y1,
		int64_t x2, int64_t y2) {
	if (x2 < x1) {
		int64_t swap = x1;
		x1 = x2;
		x2 = swap;
	}
	if (y2 < y1) {
		int64_t swap = y1;
		y1 = y2;
		y2 = swap;
	}
	return (struct wtwm_visual_box){
		.x = saturate_int(x1),
		.y = saturate_int(y1),
		.width = saturate_int(x2 - x1 + 1),
		.height = saturate_int(y2 - y1 + 1),
	};
}

void wtwm_outline_layout_compute(int outer_width, int outer_height,
		int border_width, int title_height,
		struct wtwm_outline_layout *layout) {
	if (layout == NULL) return;
	outer_width = positive(outer_width);
	outer_height = positive(outer_height);
	border_width = nonnegative(border_width);
	title_height = nonnegative(title_height);

	int64_t left = 0;
	int64_t right = (int64_t)outer_width - 1;
	int64_t top = 0;
	int64_t bottom = (int64_t)outer_height - 1;
	int64_t inner_left = left + border_width;
	int64_t inner_right = right - border_width;
	int64_t inner_top = top + title_height + border_width;
	int64_t inner_bottom = bottom - border_width;
	int64_t width_third = (inner_right - inner_left) / 3;
	int64_t height_third = (inner_bottom - inner_top) / 3;

	struct wtwm_outline_layout result = {0};
	result.lines[result.line_count++] =
		outline_line_box(left, top, right, top);
	result.lines[result.line_count++] =
		outline_line_box(left, bottom, right, bottom);
	result.lines[result.line_count++] =
		outline_line_box(left, top, left, bottom);
	result.lines[result.line_count++] =
		outline_line_box(right, top, right, bottom);
	result.lines[result.line_count++] = outline_line_box(
		inner_left + width_third, inner_top,
		inner_left + width_third, inner_bottom);
	result.lines[result.line_count++] = outline_line_box(
		inner_left + 2 * width_third, inner_top,
		inner_left + 2 * width_third, inner_bottom);
	result.lines[result.line_count++] = outline_line_box(
		inner_left, inner_top + height_third,
		inner_right, inner_top + height_third);
	result.lines[result.line_count++] = outline_line_box(
		inner_left, inner_top + 2 * height_third,
		inner_right, inner_top + 2 * height_third);
	if (title_height != 0) {
		result.lines[result.line_count++] = outline_line_box(
			left, top + title_height, right, top + title_height);
	}
	*layout = result;
}

void wtwm_title_layout_compute(const struct wtwm_visual_config *config,
		int title_width, int font_height, int font_ascent, int text_width,
		unsigned int left_button_count, unsigned int right_button_count,
		bool has_focus_highlight, struct wtwm_title_layout *layout) {
	if (layout == NULL) return;
	struct wtwm_visual_config metrics = normalized_config(config);
	title_width = nonnegative(title_width);
	font_height = positive(font_height);
	font_ascent = bounded_ascent(font_ascent, font_height);
	text_width = nonnegative(text_width);

	/* twm.c: TitleHeight = font height + 2 * FramePadding, rounded odd. */
	int title_height = saturate_int((int64_t)font_height +
		(int64_t)2 * metrics.frame_padding);
	if ((title_height & 1) == 0 && title_height < INT_MAX) ++title_height;

	/* menus.c: InitTitlebarButtons. */
	int button_width = saturate_int((int64_t)title_height -
		(int64_t)2 * ((int64_t)metrics.frame_padding + metrics.button_indent));
	int button_padding = metrics.title_padding > 1 ?
		saturate_int(((int64_t)metrics.title_padding + 1) / 2) : 1;
	int button_stride = saturate_int((int64_t)button_width + button_padding);
	int button_inner_size = saturate_int((int64_t)button_width -
		(int64_t)2 * metrics.title_button_border_width);

	/* add_window.c: ComputeCommonTitleOffsets. */
	int left_x = metrics.frame_padding;
	if (left_button_count > 0)
		left_x = saturate_int((int64_t)left_x + metrics.button_indent);
	int title_x = saturate_int((int64_t)left_x +
		(int64_t)left_button_count * button_stride - button_padding +
		metrics.title_padding);
	int right_offset = metrics.frame_padding;
	if (right_button_count > 0) {
		right_offset = saturate_int((int64_t)right_offset +
			metrics.button_indent +
			(int64_t)right_button_count * button_stride - button_padding);
	}
	int right_x = saturate_int((int64_t)title_width - right_offset);

	/* add_window.c: ComputeWindowTitleOffsets. */
	int highlight_x = saturate_int((int64_t)title_x + text_width);
	if (has_focus_highlight || right_button_count > 0)
		highlight_x = saturate_int((int64_t)highlight_x +
			metrics.title_padding);
	int highlight_width = saturate_int((int64_t)right_x - highlight_x);
	if (right_button_count > 0)
		highlight_width = saturate_int((int64_t)highlight_width -
			metrics.title_padding);
	bool highlight_visible = has_focus_highlight && highlight_width > 0;
	int squeezed_right_x = saturate_int((int64_t)highlight_x +
		(has_focus_highlight ? (int64_t)button_width * 2 : 0) +
		(right_button_count > 0 ? metrics.title_padding : 0) +
		metrics.frame_padding);
	if (squeezed_right_x > right_x) squeezed_right_x = right_x;
	int squeezed_width = saturate_int((int64_t)squeezed_right_x + right_offset);
	if (squeezed_width > title_width) squeezed_width = title_width;
	if (squeezed_width < 0) squeezed_width = 0;

	*layout = (struct wtwm_title_layout){
		.title = {0, 0, title_width, title_height},
		.text = {title_x, metrics.frame_padding, text_width, font_height},
		.focus_highlight = {
			.x = highlight_x,
			.y = metrics.frame_padding,
			.width = highlight_width > 0 ? highlight_width : 1,
			.height = saturate_int((int64_t)title_height -
				(int64_t)2 * metrics.frame_padding),
		},
		.text_baseline_y = saturate_int((int64_t)font_ascent +
			metrics.frame_padding),
		.title_extent = saturate_int((int64_t)title_height +
			metrics.border_width),
		.button_width = button_width,
		.button_inner_size = button_inner_size,
		.button_stride = button_stride,
		.button_border_width = metrics.title_button_border_width,
		/* Reference uses TBInfo.leftx for both axes, even with no left button. */
		.button_y = left_x,
		.left_button_x = left_x,
		.right_button_x = right_x,
		.squeezed_title_width = squeezed_width,
		.left_button_count = left_button_count,
		.right_button_count = right_button_count,
		.button_geometry_valid = button_width > 0 && button_inner_size > 0 &&
			button_stride > 0,
		.focus_highlight_visible = highlight_visible,
	};
}

int wtwm_title_squeeze_x(int frame_width, int title_width, int frame_border,
		enum wtwm_title_justification justification, int numerator,
		int denominator) {
	frame_width = nonnegative(frame_width);
	title_width = nonnegative(title_width);
	frame_border = nonnegative(frame_border);
	int64_t base = numerator;
	if (denominator == 0) {
		if (numerator == 0) {
			if (justification == WTWM_TITLE_JUSTIFY_RIGHT) base = frame_width;
			else if (justification == WTWM_TITLE_JUSTIFY_CENTER)
				base = frame_width / 2;
		}
	} else {
		base = (int64_t)numerator * frame_width / denominator;
		if (numerator < 0) base += frame_width;
	}
	if (justification == WTWM_TITLE_JUSTIFY_CENTER) base -= title_width / 2;
	else if (justification == WTWM_TITLE_JUSTIFY_RIGHT) base -= title_width - 1;
	int64_t maximum = (int64_t)frame_width - title_width + 1;
	if (base > maximum) base = maximum;
	if (base < 0) base = 0;
	return saturate_int(base - frame_border);
}

bool wtwm_title_button_box(const struct wtwm_title_layout *layout,
		bool right_side, unsigned int index, struct wtwm_visual_box *box) {
	if (layout == NULL || box == NULL || !layout->button_geometry_valid)
		return false;
	unsigned int count = right_side ? layout->right_button_count :
		layout->left_button_count;
	if (index >= count) return false;
	int base_x = right_side ? layout->right_button_x : layout->left_button_x;
	*box = (struct wtwm_visual_box){
		.x = saturate_int((int64_t)base_x +
			(int64_t)index * layout->button_stride),
		.y = layout->button_y,
		.width = layout->button_width,
		.height = layout->button_width,
	};
	return true;
}

void wtwm_menu_layout_compute(const struct wtwm_visual_config *config,
		int font_height, int font_ascent, int max_text_width,
		unsigned int row_count, bool has_pull_entry,
		struct wtwm_menu_layout *layout) {
	if (layout == NULL) return;
	struct wtwm_visual_config metrics = normalized_config(config);
	font_height = positive(font_height);
	font_ascent = bounded_ascent(font_ascent, font_height);
	/* AddToMenu promotes zero-width (including empty) labels to one pixel. */
	max_text_width = positive(max_text_width);

	int row_height = saturate_int((int64_t)font_height + 4);
	int content_width = saturate_int((int64_t)max_text_width +
		(has_pull_entry ? WTWM_VISUAL_MENU_PULL_ALLOWANCE : 0) +
		WTWM_VISUAL_MENU_HORIZONTAL_PADDING);
	int content_height = saturate_int((int64_t)row_count * row_height);
	int outer_width = saturate_int((int64_t)content_width +
		(int64_t)2 * metrics.menu_border_width);
	int outer_height = saturate_int((int64_t)content_height +
		(int64_t)2 * metrics.menu_border_width);
	bool shadow_visible = metrics.menu_shadows && row_count > 0;
	int visible_width = outer_width;
	int visible_height = outer_height;
	if (shadow_visible) {
		int shadow_right = saturate_int((int64_t)WTWM_VISUAL_MENU_SHADOW_OFFSET +
			content_width);
		int shadow_bottom = saturate_int((int64_t)WTWM_VISUAL_MENU_SHADOW_OFFSET +
			content_height);
		if (shadow_right > visible_width) visible_width = shadow_right;
		if (shadow_bottom > visible_height) visible_height = shadow_bottom;
	}

	*layout = (struct wtwm_menu_layout){
		.content = {
			metrics.menu_border_width,
			metrics.menu_border_width,
			content_width,
			content_height,
		},
		.outer = {0, 0, outer_width, outer_height},
		.shadow = {
			WTWM_VISUAL_MENU_SHADOW_OFFSET,
			WTWM_VISUAL_MENU_SHADOW_OFFSET,
			content_width,
			content_height,
		},
		.visible_bounds = {0, 0, visible_width, visible_height},
		.row_height = row_height,
		.text_x = saturate_int((int64_t)metrics.menu_border_width + 5),
		.text_baseline_offset = saturate_int((int64_t)metrics.menu_border_width +
			font_ascent),
		.border_width = metrics.menu_border_width,
		.row_count = row_count,
		.shadow_visible = shadow_visible,
	};
}

bool wtwm_menu_row_box(const struct wtwm_menu_layout *layout,
		unsigned int index, struct wtwm_visual_box *box) {
	if (layout == NULL || box == NULL || index >= layout->row_count) return false;
	*box = (struct wtwm_visual_box){
		.x = layout->content.x,
		.y = saturate_int((int64_t)layout->content.y +
			(int64_t)index * layout->row_height),
		.width = layout->content.width,
		.height = layout->row_height,
	};
	return true;
}

bool wtwm_menu_text_origin(const struct wtwm_menu_layout *layout,
		unsigned int index, int text_width, bool title_entry, int *x, int *y) {
	if (layout == NULL || x == NULL || y == NULL || index >= layout->row_count)
		return false;
	text_width = nonnegative(text_width);
	*x = title_entry ? saturate_int((int64_t)layout->content.x +
		((int64_t)layout->content.width - text_width) / 2) : layout->text_x;
	*y = saturate_int((int64_t)layout->text_baseline_offset +
		(int64_t)index * layout->row_height);
	return true;
}

bool wtwm_menu_pull_origin(const struct wtwm_menu_layout *layout,
		unsigned int index, int pull_width, int *x, int *y) {
	if (layout == NULL || pull_width <= 0 || x == NULL || y == NULL)
		return false;
	struct wtwm_visual_box row;
	if (!wtwm_menu_row_box(layout, index, &row)) return false;
	*x = saturate_int((int64_t)layout->content.x + layout->content.width -
		pull_width - 5);
	*y = row.y;
	return true;
}

bool wtwm_menu_popup_origin(const struct wtwm_menu_layout *layout,
		bool submenu, int anchor_x, int anchor_y, int *x, int *y) {
	if (layout == NULL || x == NULL || y == NULL) return false;
	int64_t origin_x = anchor_x;
	int64_t origin_y = anchor_y;
	if (!submenu) {
		origin_x -= layout->content.width / 2;
		origin_y -= layout->row_height / 2;
	}
	*x = saturate_int(origin_x);
	*y = saturate_int(origin_y);
	return true;
}

int wtwm_visual_scale_edge(int logical, unsigned int scale_120) {
	if (scale_120 == 0) scale_120 = 120;
	int64_t magnitude = logical;
	bool negative = magnitude < 0;
	if (negative) magnitude = -magnitude;
	int64_t scaled = magnitude * scale_120;
	scaled = (scaled + 60) / 120;
	if (negative) scaled = -scaled;
	return saturate_int(scaled);
}

struct wtwm_visual_box wtwm_visual_scale_box(struct wtwm_visual_box logical,
		unsigned int scale_120) {
	int left = wtwm_visual_scale_edge(logical.x, scale_120);
	int top = wtwm_visual_scale_edge(logical.y, scale_120);
	int right = wtwm_visual_scale_edge(
		saturate_int((int64_t)logical.x + logical.width), scale_120);
	int bottom = wtwm_visual_scale_edge(
		saturate_int((int64_t)logical.y + logical.height), scale_120);
	return (struct wtwm_visual_box){left, top,
		saturate_int((int64_t)right - left),
		saturate_int((int64_t)bottom - top)};
}
