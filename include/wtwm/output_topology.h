/* SPDX-License-Identifier: MIT */
#ifndef WTWM_OUTPUT_TOPOLOGY_H
#define WTWM_OUTPUT_TOPOLOGY_H

#include <wtwm/output_order.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_OUTPUT_TOPOLOGY_MAX_SCALE 16.0

/* Numeric order matches the eight protocol transforms without importing it. */
enum wtwm_output_transform {
	WTWM_OUTPUT_TRANSFORM_NORMAL,
	WTWM_OUTPUT_TRANSFORM_90,
	WTWM_OUTPUT_TRANSFORM_180,
	WTWM_OUTPUT_TRANSFORM_270,
	WTWM_OUTPUT_TRANSFORM_FLIPPED,
	WTWM_OUTPUT_TRANSFORM_FLIPPED_90,
	WTWM_OUTPUT_TRANSFORM_FLIPPED_180,
	WTWM_OUTPUT_TRANSFORM_FLIPPED_270,
};

struct wtwm_output_topology_mode {
	int width;
	int height;
	uint32_t refresh_mhz;
};

/* One managed output. Disabled outputs have a zero logical layout box. */
struct wtwm_output_topology_output {
	const struct wtwm_output_identity *identity;
	bool enabled;
	struct wtwm_output_topology_mode mode;
	/* Promoted wlroots scale; finite, positive, and within the resource bound. */
	double scale;
	enum wtwm_output_transform transform;
	int x;
	int y;
	int width;
	int height;
};

/* Input order is immaterial; enabled indices are derived canonically. */
struct wtwm_output_topology_snapshot {
	const struct wtwm_output_topology_output *outputs;
	size_t count;
};

enum wtwm_output_topology_change {
	WTWM_OUTPUT_TOPOLOGY_ADDED = 1u << 0,
	WTWM_OUTPUT_TOPOLOGY_REMOVED = 1u << 1,
	WTWM_OUTPUT_TOPOLOGY_ENABLED = 1u << 2,
	WTWM_OUTPUT_TOPOLOGY_DISABLED = 1u << 3,
	WTWM_OUTPUT_TOPOLOGY_MODE = 1u << 4,
	WTWM_OUTPUT_TOPOLOGY_SCALE = 1u << 5,
	WTWM_OUTPUT_TOPOLOGY_TRANSFORM = 1u << 6,
	WTWM_OUTPUT_TOPOLOGY_LAYOUT = 1u << 7,
	WTWM_OUTPUT_TOPOLOGY_INDEX = 1u << 8,
};

/* The record array is owned by the plan; snapshot output pointers are borrowed. */
struct wtwm_output_topology_record {
	const struct wtwm_output_topology_output *before;
	const struct wtwm_output_topology_output *after;
	int old_index;
	int new_index;
	uint32_t changed;
};

enum wtwm_output_history_repair {
	WTWM_OUTPUT_HISTORY_UNSET,
	WTWM_OUTPUT_HISTORY_PRESERVED,
	WTWM_OUTPUT_HISTORY_RENUMBERED,
	WTWM_OUTPUT_HISTORY_INVALIDATED,
};

struct wtwm_output_topology_plan {
	struct wtwm_output_topology_record *records;
	size_t count;
	size_t old_enabled_count;
	size_t new_enabled_count;
	uint32_t changed;
	int previous;
	enum wtwm_output_history_repair history;
};

void wtwm_output_topology_plan_init(struct wtwm_output_topology_plan *plan);
void wtwm_output_topology_plan_finish(struct wtwm_output_topology_plan *plan);

/*
 * Validate complete before/after snapshots, then publish one owned plan.  The
 * snapshots must outlive the plan.  Add/remove bits describe membership;
 * remaining bits describe changes to identities present in both snapshots.
 * Invalid input leaves an initialized destination plan byte-for-byte unchanged.
 */
bool wtwm_output_topology_plan_build(
	const struct wtwm_output_topology_snapshot *before,
	const struct wtwm_output_topology_snapshot *after, int previous,
	struct wtwm_output_topology_plan *plan);

#endif
