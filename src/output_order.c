/* SPDX-License-Identifier: MIT */

#include "wtwm/output_order.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct wtwm_output_order_item {
	const struct wtwm_output_identity *identity;
	void *output;
	bool populated;
};

struct wtwm_output_order {
	size_t count;
	bool sorted;
	struct wtwm_output_order_item items[];
};

static char *copy_string(const char *value) {
	if (value == NULL) value = "";
	size_t length = strlen(value);
	if (length == SIZE_MAX) return NULL;
	char *copy = malloc(length + 1);
	if (copy != NULL) memcpy(copy, value, length + 1);
	return copy;
}

bool wtwm_output_identity_init(struct wtwm_output_identity *identity,
		const char *name, const char *make, const char *model, const char *serial,
		uint64_t announcement_ordinal) {
	if (identity == NULL) return false;
	struct wtwm_output_identity result = {
		.announcement_ordinal = announcement_ordinal,
	};
	result.name = copy_string(name);
	result.make = copy_string(make);
	result.model = copy_string(model);
	result.serial = copy_string(serial);
	if (result.name == NULL || result.make == NULL || result.model == NULL ||
			result.serial == NULL) {
		wtwm_output_identity_finish(&result);
		return false;
	}
	*identity = result;
	return true;
}

void wtwm_output_identity_finish(struct wtwm_output_identity *identity) {
	if (identity == NULL) return;
	free(identity->name);
	free(identity->make);
	free(identity->model);
	free(identity->serial);
	*identity = (struct wtwm_output_identity){0};
}

bool wtwm_output_order_create(size_t count, struct wtwm_output_order **order) {
	if (order == NULL) return false;
	*order = NULL;
	if (count > (SIZE_MAX - sizeof(struct wtwm_output_order)) /
			sizeof(struct wtwm_output_order_item)) return false;
	struct wtwm_output_order *result = calloc(1,
		sizeof(*result) + count * sizeof(result->items[0]));
	if (result == NULL) return false;
	result->count = count;
	*order = result;
	return true;
}

bool wtwm_output_order_set(struct wtwm_output_order *order, size_t index,
		const struct wtwm_output_identity *identity, void *output) {
	if (order == NULL || index >= order->count || identity == NULL ||
			output == NULL || order->sorted) return false;
	order->items[index] = (struct wtwm_output_order_item){
		.identity = identity,
		.output = output,
		.populated = true,
	};
	return true;
}

static int compare_bytes(const char *left, const char *right) {
	if (left == NULL) left = "";
	if (right == NULL) right = "";
	const unsigned char *a = (const unsigned char *)left;
	const unsigned char *b = (const unsigned char *)right;
	while (*a != '\0' && *a == *b) {
		++a;
		++b;
	}
	return *a < *b ? -1 : *a > *b;
}

static int compare_items(const void *left, const void *right) {
	const struct wtwm_output_identity *a =
		((const struct wtwm_output_order_item *)left)->identity;
	const struct wtwm_output_identity *b =
		((const struct wtwm_output_order_item *)right)->identity;
	int result = compare_bytes(a->name, b->name);
	if (result == 0) result = compare_bytes(a->make, b->make);
	if (result == 0) result = compare_bytes(a->model, b->model);
	if (result == 0) result = compare_bytes(a->serial, b->serial);
	if (result != 0) return result;
	return a->announcement_ordinal < b->announcement_ordinal ? -1 :
		a->announcement_ordinal > b->announcement_ordinal;
}

bool wtwm_output_order_sort(struct wtwm_output_order *order) {
	if (order == NULL || order->sorted) return false;
	for (size_t i = 0; i < order->count; ++i)
		if (!order->items[i].populated) return false;
	qsort(order->items, order->count, sizeof(order->items[0]), compare_items);
	order->sorted = true;
	return true;
}

size_t wtwm_output_order_count(const struct wtwm_output_order *order) {
	return order != NULL ? order->count : 0;
}

void *wtwm_output_order_at(const struct wtwm_output_order *order, size_t index) {
	if (order == NULL || !order->sorted || index >= order->count) return NULL;
	return order->items[index].output;
}

void wtwm_output_order_destroy(struct wtwm_output_order *order) {
	free(order);
}
