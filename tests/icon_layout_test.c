/* SPDX-License-Identifier: MIT */
#include <wtwm/icon_layout.h>

#include <assert.h>
#include <limits.h>
#include <stddef.h>

static struct wtwm_icon_layout_region region(int x, int y, int width, int height,
		enum wtwm_icon_layout_direction primary,
		enum wtwm_icon_layout_direction secondary,
		int grid_width, int grid_height) {
	return (struct wtwm_icon_layout_region){
		.x = x,
		.y = y,
		.width = width,
		.height = height,
		.primary = primary,
		.secondary = secondary,
		.grid_width = grid_width,
		.grid_height = grid_height,
	};
}

static struct wtwm_icon_layout_placement allocate(
		struct wtwm_icon_layout *layout, uint64_t key, int width, int height) {
	struct wtwm_icon_layout_placement placement;
	assert(wtwm_icon_layout_allocate(layout, key, width, height, &placement) ==
		WTWM_ICON_LAYOUT_OK);
	return placement;
}

static void assert_cell(struct wtwm_icon_layout_placement placement,
		size_t region_index, int x, int y, int width, int height) {
	assert(placement.region_index == region_index);
	assert(placement.cell_x == x);
	assert(placement.cell_y == y);
	assert(placement.cell_width == width);
	assert(placement.cell_height == height);
}

static bool placements_overlap(struct wtwm_icon_layout_placement first,
		struct wtwm_icon_layout_placement second) {
	return first.cell_x < second.cell_x + second.cell_width &&
		second.cell_x < first.cell_x + first.cell_width &&
		first.cell_y < second.cell_y + second.cell_height &&
		second.cell_y < first.cell_y + first.cell_height;
}

static void test_config_conversion(void) {
	struct wtwm_icon_region config = {
		.geometry = "200x120+10+20",
		.vertical_gravity = "North",
		.horizontal_gravity = "West",
		.grid_width = 50,
		.grid_height = 30,
	};
	struct wtwm_icon_layout_region converted;
	assert(wtwm_icon_layout_region_from_config(&config, 800, 600, &converted));
	assert(converted.x == 10);
	assert(converted.y == 20);
	assert(converted.width == 200);
	assert(converted.height == 120);
	assert(converted.primary == WTWM_ICON_LAYOUT_NORTH);
	assert(converted.secondary == WTWM_ICON_LAYOUT_WEST);
	assert(converted.grid_width == 50);
	assert(converted.grid_height == 30);

	config = (struct wtwm_icon_region){
		.geometry = "=100X60-0-10",
		.vertical_gravity = "south",
		.horizontal_gravity = "EAST",
		.grid_width = 0,
		.grid_height = -12,
	};
	assert(wtwm_icon_layout_region_from_config(&config, 800, 600, &converted));
	assert(converted.x == 700);
	assert(converted.y == 530);
	assert(converted.primary == WTWM_ICON_LAYOUT_SOUTH);
	assert(converted.secondary == WTWM_ICON_LAYOUT_EAST);
	assert(converted.grid_width == 1);
	assert(converted.grid_height == 1);

	config = (struct wtwm_icon_region){
		.geometry = "10x20+7",
		.vertical_gravity = "North",
		.horizontal_gravity = "West",
		.grid_width = 1,
		.grid_height = 1,
	};
	assert(wtwm_icon_layout_region_from_config(&config, 800, 600, &converted));
	assert(converted.x == 7);
	assert(converted.y == 0);
}

static void test_malformed_config(void) {
	struct wtwm_icon_layout_region converted;
	struct wtwm_icon_region valid = {
		.geometry = "10x10",
		.vertical_gravity = "North",
		.horizontal_gravity = "West",
		.grid_width = 1,
		.grid_height = 1,
	};
	assert(!wtwm_icon_layout_region_from_config(NULL, 100, 100, &converted));
	assert(!wtwm_icon_layout_region_from_config(&valid, 100, 100, NULL));
	assert(!wtwm_icon_layout_region_from_config(&valid, 0, 100, &converted));

	static const char *const bad_geometry[] = {
		"", "nonsense", "10", "x10", "10x", "0x10", "10x0",
		"10x10+", "10x10+1-", "10x10+1+2junk", "2147483648x10",
	};
	for (size_t i = 0; i < sizeof(bad_geometry) / sizeof(bad_geometry[0]); ++i) {
		struct wtwm_icon_region bad = valid;
		for (size_t j = 0; j < WTWM_NAME_MAX; ++j) bad.geometry[j] = '\0';
		for (size_t j = 0; bad_geometry[i][j] != '\0'; ++j)
			bad.geometry[j] = bad_geometry[i][j];
		assert(!wtwm_icon_layout_region_from_config(&bad, 100, 100, &converted));
	}

	struct wtwm_icon_region bad = valid;
	bad.vertical_gravity[0] = 'E';
	bad.vertical_gravity[1] = 'a';
	bad.vertical_gravity[2] = 's';
	bad.vertical_gravity[3] = 't';
	bad.vertical_gravity[4] = '\0';
	assert(!wtwm_icon_layout_region_from_config(&bad, 100, 100, &converted));
	bad = valid;
	bad.horizontal_gravity[0] = 'N';
	bad.horizontal_gravity[1] = 'o';
	bad.horizontal_gravity[2] = 'r';
	bad.horizontal_gravity[3] = 't';
	bad.horizontal_gravity[4] = 'h';
	bad.horizontal_gravity[5] = '\0';
	assert(!wtwm_icon_layout_region_from_config(&bad, 100, 100, &converted));
}

static void test_gravity_and_grid(void) {
	struct wtwm_icon_layout_region geometry = region(0, 0, 100, 100,
		WTWM_ICON_LAYOUT_NORTH, WTWM_ICON_LAYOUT_WEST, 20, 20);
	struct wtwm_icon_layout *layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	struct wtwm_icon_layout_placement first = allocate(layout, 1, 11, 9);
	struct wtwm_icon_layout_placement second = allocate(layout, 2, 11, 9);
	assert_cell(first, 0, 0, 0, 20, 20);
	assert(first.x == 4);
	assert(first.y == 5);
	assert(first.width == 11);
	assert(first.height == 9);
	assert_cell(second, 0, 0, 20, 20, 20);
	assert(!placements_overlap(first, second));
	wtwm_icon_layout_destroy(layout);

	geometry = region(10, 20, 100, 80, WTWM_ICON_LAYOUT_SOUTH,
		WTWM_ICON_LAYOUT_EAST, 20, 20);
	layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	first = allocate(layout, 1, 20, 20);
	second = allocate(layout, 2, 20, 20);
	assert_cell(first, 0, 90, 80, 20, 20);
	assert_cell(second, 0, 90, 60, 20, 20);
	wtwm_icon_layout_destroy(layout);

	geometry = region(10, 20, 100, 80, WTWM_ICON_LAYOUT_NORTH,
		WTWM_ICON_LAYOUT_EAST, 20, 20);
	layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	first = allocate(layout, 1, 20, 20);
	second = allocate(layout, 2, 20, 20);
	assert_cell(first, 0, 90, 20, 20, 20);
	assert_cell(second, 0, 90, 40, 20, 20);
	wtwm_icon_layout_destroy(layout);

	geometry = region(10, 20, 100, 80, WTWM_ICON_LAYOUT_SOUTH,
		WTWM_ICON_LAYOUT_WEST, 20, 20);
	layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	first = allocate(layout, 1, 20, 20);
	second = allocate(layout, 2, 20, 20);
	assert_cell(first, 0, 10, 80, 20, 20);
	assert_cell(second, 0, 10, 60, 20, 20);
	wtwm_icon_layout_destroy(layout);

	/* The allocator also preserves twm's generic primary/secondary split order. */
	geometry = region(0, 0, 100, 80, WTWM_ICON_LAYOUT_EAST,
		WTWM_ICON_LAYOUT_NORTH, 20, 20);
	layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	first = allocate(layout, 1, 20, 20);
	second = allocate(layout, 2, 20, 20);
	assert_cell(first, 0, 80, 0, 20, 20);
	assert_cell(second, 0, 60, 0, 20, 20);
	wtwm_icon_layout_destroy(layout);

	geometry = region(0, 0, 100, 80, WTWM_ICON_LAYOUT_NORTH,
		WTWM_ICON_LAYOUT_WEST, 16, 10);
	layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	first = allocate(layout, 1, 17, 11);
	assert_cell(first, 0, 0, 0, 32, 20);
	assert(first.x == 7);
	assert(first.y == 4);
	wtwm_icon_layout_destroy(layout);
}

static void test_full_and_succeeding_regions(void) {
	struct wtwm_icon_layout_region regions[] = {
		region(0, 0, 40, 40, WTWM_ICON_LAYOUT_NORTH,
			WTWM_ICON_LAYOUT_WEST, 20, 20),
		region(100, 10, 20, 20, WTWM_ICON_LAYOUT_NORTH,
			WTWM_ICON_LAYOUT_WEST, 20, 20),
	};
	struct wtwm_icon_layout *layout = wtwm_icon_layout_create(regions, 2);
	assert(layout != NULL);
	const int expected_x[] = {0, 0, 20, 20};
	const int expected_y[] = {0, 20, 0, 20};
	struct wtwm_icon_layout_placement placements[5];
	for (size_t i = 0; i < 4; ++i) {
		placements[i] = allocate(layout, i + 1, 20, 20);
		assert_cell(placements[i], 0, expected_x[i], expected_y[i], 20, 20);
		for (size_t j = 0; j < i; ++j)
			assert(!placements_overlap(placements[i], placements[j]));
	}
	placements[4] = allocate(layout, 5, 20, 20);
	assert_cell(placements[4], 1, 100, 10, 20, 20);
	assert(wtwm_icon_layout_allocate(layout, 6, 1, 1, NULL) ==
		WTWM_ICON_LAYOUT_FULL);
	assert(wtwm_icon_layout_allocation_count(layout) == 5);
	wtwm_icon_layout_destroy(layout);
}

static void test_release_reuse_and_coalescing(void) {
	struct wtwm_icon_layout_region geometry = region(0, 0, 60, 40,
		WTWM_ICON_LAYOUT_NORTH, WTWM_ICON_LAYOUT_WEST, 20, 20);
	struct wtwm_icon_layout *layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	struct wtwm_icon_layout_placement first = allocate(layout, 11, 20, 20);
	struct wtwm_icon_layout_placement second = allocate(layout, 12, 20, 20);
	struct wtwm_icon_layout_placement third = allocate(layout, 13, 20, 20);
	assert_cell(first, 0, 0, 0, 20, 20);
	assert_cell(second, 0, 0, 20, 20, 20);
	assert_cell(third, 0, 20, 0, 20, 20);

	assert(wtwm_icon_layout_release(layout, 12));
	struct wtwm_icon_layout_placement reused = allocate(layout, 14, 8, 8);
	assert_cell(reused, 0, 0, 20, 20, 20);
	assert(!wtwm_icon_layout_release(layout, 99));
	assert(wtwm_icon_layout_release(layout, 14));
	assert(wtwm_icon_layout_release(layout, 11));
	assert(wtwm_icon_layout_release(layout, 13));
	assert(wtwm_icon_layout_allocation_count(layout) == 0);

	struct wtwm_icon_layout_placement whole = allocate(layout, 20, 60, 40);
	assert_cell(whole, 0, 0, 0, 60, 40);
	wtwm_icon_layout_destroy(layout);
}

static void test_stable_sequence(void) {
	struct wtwm_icon_layout_region geometry = region(5, 7, 80, 60,
		WTWM_ICON_LAYOUT_SOUTH, WTWM_ICON_LAYOUT_WEST, 10, 10);
	struct wtwm_icon_layout *first = wtwm_icon_layout_create(&geometry, 1);
	struct wtwm_icon_layout *second = wtwm_icon_layout_create(&geometry, 1);
	assert(first != NULL);
	assert(second != NULL);
	const int widths[] = {12, 19, 8, 21, 10};
	const int heights[] = {9, 11, 17, 8, 10};
	for (size_t i = 0; i < 4; ++i) {
		struct wtwm_icon_layout_placement a =
			allocate(first, i + 1, widths[i], heights[i]);
		struct wtwm_icon_layout_placement b =
			allocate(second, i + 1, widths[i], heights[i]);
		assert_cell(a, b.region_index, b.cell_x, b.cell_y,
			b.cell_width, b.cell_height);
		assert(a.x == b.x);
		assert(a.y == b.y);
	}
	assert(wtwm_icon_layout_release(first, 2));
	assert(wtwm_icon_layout_release(second, 2));
	assert(wtwm_icon_layout_release(first, 4));
	assert(wtwm_icon_layout_release(second, 4));
	struct wtwm_icon_layout_placement a =
		allocate(first, 5, widths[4], heights[4]);
	struct wtwm_icon_layout_placement b =
		allocate(second, 5, widths[4], heights[4]);
	assert_cell(a, b.region_index, b.cell_x, b.cell_y,
		b.cell_width, b.cell_height);
	assert(a.x == b.x);
	assert(a.y == b.y);
	wtwm_icon_layout_destroy(first);
	wtwm_icon_layout_destroy(second);
}

static void test_invalid_operations_and_regions(void) {
	assert(wtwm_icon_layout_create(NULL, 1) == NULL);
	struct wtwm_icon_layout_region bad = region(0, 0, 0, 10,
		WTWM_ICON_LAYOUT_NORTH, WTWM_ICON_LAYOUT_WEST, 1, 1);
	assert(wtwm_icon_layout_create(&bad, 1) == NULL);
	bad = region(0, 0, 10, 10, WTWM_ICON_LAYOUT_NORTH,
		WTWM_ICON_LAYOUT_SOUTH, 1, 1);
	assert(wtwm_icon_layout_create(&bad, 1) == NULL);
	bad = region(INT_MAX, 0, 10, 10, WTWM_ICON_LAYOUT_NORTH,
		WTWM_ICON_LAYOUT_WEST, 1, 1);
	assert(wtwm_icon_layout_create(&bad, 1) == NULL);

	struct wtwm_icon_layout *empty = wtwm_icon_layout_create(NULL, 0);
	assert(empty != NULL);
	assert(wtwm_icon_layout_allocate(empty, 1, 1, 1, NULL) ==
		WTWM_ICON_LAYOUT_FULL);
	wtwm_icon_layout_destroy(empty);

	struct wtwm_icon_layout_region geometry = region(0, 0, 10, 10,
		WTWM_ICON_LAYOUT_NORTH, WTWM_ICON_LAYOUT_WEST, 0, -1);
	struct wtwm_icon_layout *layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	assert(wtwm_icon_layout_contains_point(layout, 0, 0));
	assert(wtwm_icon_layout_contains_point(layout, 9, 9));
	assert(!wtwm_icon_layout_contains_point(layout, -1, 0));
	assert(!wtwm_icon_layout_contains_point(layout, 10, 9));
	assert(!wtwm_icon_layout_contains_point(layout, 9, 10));
	assert(!wtwm_icon_layout_contains_point(NULL, 0, 0));
	assert(wtwm_icon_layout_allocate(NULL, 1, 1, 1, NULL) ==
		WTWM_ICON_LAYOUT_INVALID);
	assert(wtwm_icon_layout_allocate(layout, 0, 1, 1, NULL) ==
		WTWM_ICON_LAYOUT_INVALID);
	assert(wtwm_icon_layout_allocate(layout, 1, 0, 1, NULL) ==
		WTWM_ICON_LAYOUT_INVALID);
	assert(wtwm_icon_layout_allocate(layout, 1, 1, -1, NULL) ==
		WTWM_ICON_LAYOUT_INVALID);
	struct wtwm_icon_layout_placement placement = allocate(layout, 1, 1, 1);
	assert_cell(placement, 0, 0, 0, 1, 1);
	assert(wtwm_icon_layout_allocate(layout, 1, 1, 1, NULL) ==
		WTWM_ICON_LAYOUT_DUPLICATE);
	assert(wtwm_icon_layout_lookup(layout, 1, &placement));
	assert(!wtwm_icon_layout_lookup(layout, 0, &placement));
	assert(!wtwm_icon_layout_lookup(NULL, 1, &placement));
	assert(!wtwm_icon_layout_release(layout, 0));
	assert(!wtwm_icon_layout_release(NULL, 1));
	wtwm_icon_layout_destroy(layout);
	wtwm_icon_layout_destroy(NULL);
}

static void test_randomized_lifecycle_churn(void) {
	enum { WINDOW_COUNT = 256, OPERATION_COUNT = 2000 };
	struct wtwm_icon_layout_region geometry = region(0, 0, 640, 640,
		WTWM_ICON_LAYOUT_NORTH, WTWM_ICON_LAYOUT_WEST, 20, 20);
	struct wtwm_icon_layout *layout = wtwm_icon_layout_create(&geometry, 1);
	assert(layout != NULL);
	bool occupied[WINDOW_COUNT] = {false};
	uint32_t random = UINT32_C(0x1c07b3a5);
	for (unsigned operation = 0; operation < OPERATION_COUNT; ++operation) {
		random = random * UINT32_C(1664525) + UINT32_C(1013904223);
		unsigned slot = random % WINDOW_COUNT;
		uint64_t key = (uint64_t)slot + 1;
		if (occupied[slot]) {
			assert(wtwm_icon_layout_release(layout, key));
			occupied[slot] = false;
		} else {
			int width = 1 + (int)((random >> 8) % 19u);
			int height = 1 + (int)((random >> 16) % 19u);
			(void)allocate(layout, key, width, height);
			occupied[slot] = true;
		}
		if (operation % 100 != 0) continue;
		for (unsigned i = 0; i < WINDOW_COUNT; ++i) {
			if (!occupied[i]) continue;
			struct wtwm_icon_layout_placement first;
			assert(wtwm_icon_layout_lookup(layout, (uint64_t)i + 1, &first));
			for (unsigned j = i + 1; j < WINDOW_COUNT; ++j) {
				if (!occupied[j]) continue;
				struct wtwm_icon_layout_placement second;
				assert(wtwm_icon_layout_lookup(layout, (uint64_t)j + 1,
					&second));
				assert(!placements_overlap(first, second));
			}
		}
	}
	for (unsigned i = 0; i < WINDOW_COUNT; ++i)
		if (occupied[i]) assert(wtwm_icon_layout_release(layout, (uint64_t)i + 1));
	assert(wtwm_icon_layout_allocation_count(layout) == 0);
	wtwm_icon_layout_destroy(layout);
}

int main(void) {
	test_config_conversion();
	test_malformed_config();
	test_gravity_and_grid();
	test_full_and_succeeding_regions();
	test_release_reuse_and_coalescing();
	test_stable_sequence();
	test_invalid_operations_and_regions();
	test_randomized_lifecycle_churn();
	return 0;
}
