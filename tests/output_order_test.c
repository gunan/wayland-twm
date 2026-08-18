/* SPDX-License-Identifier: MIT */

#include <wtwm/output_order.h>

#include <assert.h>
#include <stdint.h>
#include <string.h>

struct fixture {
	struct wtwm_output_identity identity;
	int geometry_x;
};

static void init_fixture(struct fixture *fixture, const char *name,
		const char *make, const char *model, const char *serial,
		uint64_t ordinal) {
	assert(wtwm_output_identity_init(&fixture->identity, name, make, model,
		serial, ordinal));
}

static void finish_fixtures(struct fixture *fixtures, size_t count) {
	for (size_t i = 0; i < count; ++i)
		wtwm_output_identity_finish(&fixtures[i].identity);
}

static struct wtwm_output_order *snapshot(struct fixture *fixtures,
		const size_t *announcement_order, size_t count) {
	struct wtwm_output_order *order = NULL;
	assert(wtwm_output_order_create(count, &order));
	for (size_t i = 0; i < count; ++i) {
		size_t item = announcement_order != NULL ? announcement_order[i] : i;
		assert(wtwm_output_order_set(order, i, &fixtures[item].identity,
			&fixtures[item]));
	}
	assert(wtwm_output_order_sort(order));
	return order;
}

static void assert_order(struct wtwm_output_order *order,
		struct fixture *fixtures, const size_t *expected, size_t count) {
	assert(wtwm_output_order_count(order) == count);
	for (size_t i = 0; i < count; ++i)
		assert(wtwm_output_order_at(order, i) == &fixtures[expected[i]]);
	assert(wtwm_output_order_at(order, count) == NULL);
}

static void reverse_announcement(void) {
	struct fixture outputs[3] = {0};
	init_fixture(&outputs[0], "alpha", "", "", "", 2);
	init_fixture(&outputs[1], "bravo", "", "", "", 1);
	init_fixture(&outputs[2], "charlie", "", "", "", 0);
	const size_t announced[] = {2, 1, 0};
	const size_t expected[] = {0, 1, 2};
	struct wtwm_output_order *order = snapshot(outputs, announced, 3);
	assert_order(order, outputs, expected, 3);
	wtwm_output_order_destroy(order);
	finish_fixtures(outputs, 3);
}

static void secondary_fields(void) {
	struct fixture outputs[5] = {0};
	init_fixture(&outputs[0], "same", "b", "a", "a", 0);
	init_fixture(&outputs[1], "same", "a", "b", "a", 1);
	init_fixture(&outputs[2], "same", "a", "a", "b", 2);
	init_fixture(&outputs[3], "same", "a", "a", "a", 3);
	init_fixture(&outputs[4], "later", "", "", "", 4);
	const size_t expected[] = {4, 3, 2, 1, 0};
	struct wtwm_output_order *order = snapshot(outputs, NULL, 5);
	assert_order(order, outputs, expected, 5);
	wtwm_output_order_destroy(order);
	finish_fixtures(outputs, 5);
}

static void null_empty_and_collision(void) {
	struct fixture outputs[4] = {0};
	outputs[0].identity.announcement_ordinal = 12;
	init_fixture(&outputs[1], "", "", "", "", 4);
	init_fixture(&outputs[2], "", NULL, "", NULL, 9);
	init_fixture(&outputs[3], "", "", "", "", UINT64_MAX);
	const size_t expected[] = {1, 2, 0, 3};
	struct wtwm_output_order *order = snapshot(outputs, NULL, 4);
	assert_order(order, outputs, expected, 4);
	wtwm_output_order_destroy(order);
	finish_fixtures(outputs, 4);
}

static void unsigned_bytes(void) {
	const char byte_7f[] = {(char)0x7f, '\0'};
	const char byte_80[] = {(char)0x80, '\0'};
	const char byte_ff[] = {(char)0xff, '\0'};
	struct fixture outputs[3] = {0};
	init_fixture(&outputs[0], byte_ff, "", "", "", 0);
	init_fixture(&outputs[1], byte_80, "", "", "", 1);
	init_fixture(&outputs[2], byte_7f, "", "", "", 2);
	const size_t expected[] = {2, 1, 0};
	struct wtwm_output_order *order = snapshot(outputs, NULL, 3);
	assert_order(order, outputs, expected, 3);
	wtwm_output_order_destroy(order);
	finish_fixtures(outputs, 3);
}

static void identity_copy_and_geometry_stability(void) {
	char first_name[] = "left";
	char second_name[] = "right";
	struct fixture outputs[2] = {0};
	init_fixture(&outputs[0], first_name, "make", "model", "serial", 1);
	init_fixture(&outputs[1], second_name, "make", "model", "serial", 0);
	memcpy(first_name, "zzzz", sizeof(first_name));
	memcpy(second_name, "aaaaa", sizeof(second_name));
	outputs[0].geometry_x = 10000;
	outputs[1].geometry_x = -10000;
	const size_t expected[] = {0, 1};
	struct wtwm_output_order *order = snapshot(outputs, NULL, 2);
	assert_order(order, outputs, expected, 2);
	wtwm_output_order_destroy(order);

	outputs[0].geometry_x = -20000;
	outputs[1].geometry_x = 20000;
	order = snapshot(outputs, NULL, 2);
	assert_order(order, outputs, expected, 2);
	wtwm_output_order_destroy(order);
	finish_fixtures(outputs, 2);
}

static void invalid_arguments(void) {
	assert(!wtwm_output_identity_init(NULL, "a", "b", "c", "d", 0));
	wtwm_output_identity_finish(NULL);
	assert(!wtwm_output_order_create(1, NULL));
	struct wtwm_output_order *order = (void *)(uintptr_t)1;
	assert(!wtwm_output_order_create(SIZE_MAX, &order));
	assert(order == NULL);
	assert(wtwm_output_order_create(0, &order));
	assert(wtwm_output_order_count(order) == 0);
	assert(wtwm_output_order_sort(order));
	assert(wtwm_output_order_at(order, 0) == NULL);
	assert(!wtwm_output_order_sort(order));
	wtwm_output_order_destroy(order);

	struct fixture output = {0};
	init_fixture(&output, "one", "", "", "", 0);
	assert(wtwm_output_order_create(2, &order));
	assert(!wtwm_output_order_set(NULL, 0, &output.identity, &output));
	assert(!wtwm_output_order_set(order, 2, &output.identity, &output));
	assert(!wtwm_output_order_set(order, 0, NULL, &output));
	assert(!wtwm_output_order_set(order, 0, &output.identity, NULL));
	assert(wtwm_output_order_set(order, 0, &output.identity, &output));
	assert(!wtwm_output_order_sort(order));
	assert(wtwm_output_order_at(order, 0) == NULL);
	assert(wtwm_output_order_set(order, 1, &output.identity, &output));
	assert(wtwm_output_order_sort(order));
	assert(!wtwm_output_order_set(order, 0, &output.identity, &output));
	wtwm_output_order_destroy(order);
	wtwm_output_order_destroy(NULL);
	wtwm_output_identity_finish(&output.identity);
}

int main(void) {
	reverse_announcement();
	secondary_fields();
	null_empty_and_collision();
	unsigned_bytes();
	identity_copy_and_geometry_stability();
	invalid_arguments();
	return 0;
}
