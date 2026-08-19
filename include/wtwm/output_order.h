/* SPDX-License-Identifier: MIT */
#ifndef WTWM_OUTPUT_ORDER_H
#define WTWM_OUTPUT_ORDER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct wtwm_output_identity {
	char *name;
	char *make;
	char *model;
	char *serial;
	uint64_t announcement_ordinal;
};

/* Copy an output's immutable first-announcement identity.  NULL fields are
 * represented by owned empty strings. */
bool wtwm_output_identity_init(struct wtwm_output_identity *identity,
	const char *name, const char *make, const char *model, const char *serial,
	uint64_t announcement_ordinal);
void wtwm_output_identity_finish(struct wtwm_output_identity *identity);

struct wtwm_output_order;

/* Allocate one dense snapshot that callers populate before sorting. */
bool wtwm_output_order_create(size_t count, struct wtwm_output_order **order);
bool wtwm_output_order_set(struct wtwm_output_order *order, size_t index,
	const struct wtwm_output_identity *identity, void *output);
bool wtwm_output_order_sort(struct wtwm_output_order *order);
size_t wtwm_output_order_count(const struct wtwm_output_order *order);
void *wtwm_output_order_at(const struct wtwm_output_order *order, size_t index);
void wtwm_output_order_destroy(struct wtwm_output_order *order);

#endif
