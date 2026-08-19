/* SPDX-License-Identifier: MIT */
#ifndef WTWM_OUTPUT_RESTORE_H
#define WTWM_OUTPUT_RESTORE_H

#include <wtwm/output_order.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct wtwm_restore_box {
	int x;
	int y;
	int width;
	int height;
};

/* Outputs must be in canonical immutable-identity order. */
struct wtwm_output_restore_output {
	const struct wtwm_output_identity *identity;
	struct wtwm_restore_box box;
};

struct wtwm_output_restore_snapshot {
	const struct wtwm_output_restore_output *outputs;
	size_t count;
};

/* Parent is another client index, or -1 for a family root. */
struct wtwm_output_restore_client {
	int parent;
	/* Frame and optional boxes are complete decorated outer geometry. */
	struct wtwm_restore_box frame;
	bool icon_visible;
	struct wtwm_restore_box icon;
	bool zoomed;
	/* Runtime converts saved client size to outer size, then restores x/y only. */
	bool zoom_restore_valid;
	struct wtwm_restore_box zoom_restore;
};

struct wtwm_output_restore_record {
	struct wtwm_restore_box frame;
	int source_output;
	int target_output;
	int64_t frame_dx;
	int64_t frame_dy;
	bool frame_changed;
	bool recompute_zoom;

	struct wtwm_restore_box icon;
	int icon_source_output;
	int icon_target_output;
	bool icon_changed;

	struct wtwm_restore_box zoom_restore;
	int zoom_restore_source_output;
	int zoom_restore_target_output;
	bool zoom_restore_changed;

	/* Preserve protocol mapping and compositor-owned state while hidden. */
	bool pending;
};

struct wtwm_output_restore_plan {
	struct wtwm_output_restore_record *records;
	size_t count;
	bool pending;
	bool built;
};

void wtwm_output_restore_plan_init(struct wtwm_output_restore_plan *plan);
void wtwm_output_restore_plan_finish(struct wtwm_output_restore_plan *plan);

/*
 * Validate every snapshot, family, and geometry before publishing an owned
 * plan. Inputs and an initialized destination remain unchanged on failure.
 * Sizes and all non-geometric client state are preserved by construction.
 * Positive post-state intersection is sufficient to preserve a normal box.
 */
bool wtwm_output_restore_plan_build(
	const struct wtwm_output_restore_snapshot *before,
	const struct wtwm_output_restore_snapshot *after,
	const struct wtwm_output_restore_client *clients, size_t client_count,
	struct wtwm_output_restore_plan *plan);

#endif
