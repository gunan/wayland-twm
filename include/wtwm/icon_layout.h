/* SPDX-License-Identifier: MIT */
#ifndef WTWM_ICON_LAYOUT_H
#define WTWM_ICON_LAYOUT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <wtwm/config.h>

enum wtwm_icon_layout_direction {
	WTWM_ICON_LAYOUT_NORTH,
	WTWM_ICON_LAYOUT_SOUTH,
	WTWM_ICON_LAYOUT_EAST,
	WTWM_ICON_LAYOUT_WEST,
};

struct wtwm_icon_layout_region {
	int x;
	int y;
	int width;
	int height;
	enum wtwm_icon_layout_direction primary;
	enum wtwm_icon_layout_direction secondary;
	int grid_width;
	int grid_height;
};

struct wtwm_icon_layout_placement {
	size_t region_index;
	int x;
	int y;
	int width;
	int height;
	int cell_x;
	int cell_y;
	int cell_width;
	int cell_height;
};

enum wtwm_icon_layout_result {
	WTWM_ICON_LAYOUT_OK,
	WTWM_ICON_LAYOUT_INVALID,
	WTWM_ICON_LAYOUT_DUPLICATE,
	WTWM_ICON_LAYOUT_FULL,
	WTWM_ICON_LAYOUT_OUT_OF_MEMORY,
};

struct wtwm_icon_layout;

/*
 * Convert a parsed IconRegion into allocator geometry. Negative geometry
 * offsets are resolved against the supplied output dimensions, as X geometry
 * does. The documented vertical-then-horizontal gravity order is required.
 */
bool wtwm_icon_layout_region_from_config(const struct wtwm_icon_region *config,
	int output_width, int output_height,
	struct wtwm_icon_layout_region *region);

/*
 * Apply twm's initial icon fallback boundary rule. An icon whose origin is
 * inside the screen may extend past its right or bottom edge; only an origin
 * strictly beyond an edge is moved back by the icon's full size.
 */
bool wtwm_icon_reference_clamp(int screen_x, int screen_y, int screen_width,
	int screen_height, int icon_width, int icon_height, int *x, int *y);

/*
 * Create an allocator containing regions in configuration order. Region
 * dimensions must be positive and the two directions must be perpendicular.
 * Non-positive grid dimensions have the reference twm meaning of one pixel.
 */
struct wtwm_icon_layout *wtwm_icon_layout_create(
	const struct wtwm_icon_layout_region *regions, size_t region_count);
void wtwm_icon_layout_destroy(struct wtwm_icon_layout *layout);

/*
 * Allocate the outer icon size, including its border. The returned icon
 * coordinates are centered within the grid-rounded cell. Allocation key zero
 * is reserved and each live allocation key must be unique.
 */
enum wtwm_icon_layout_result wtwm_icon_layout_allocate(
	struct wtwm_icon_layout *layout, uint64_t key, int width, int height,
	struct wtwm_icon_layout_placement *placement);

bool wtwm_icon_layout_lookup(const struct wtwm_icon_layout *layout,
	uint64_t key, struct wtwm_icon_layout_placement *placement);
/* True when the point is inside any configured region (right/bottom exclusive). */
bool wtwm_icon_layout_contains_point(const struct wtwm_icon_layout *layout,
	int x, int y);
bool wtwm_icon_layout_release(struct wtwm_icon_layout *layout, uint64_t key);
size_t wtwm_icon_layout_allocation_count(const struct wtwm_icon_layout *layout);

#endif
