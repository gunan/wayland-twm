/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include "wtwm/xbm.h"

#include <assert.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static const char *fixture(const char *name) {
	static char paths[32][1024];
	static size_t next_path;
	assert(next_path < sizeof(paths) / sizeof(paths[0]));
	char *path = paths[next_path++];
	const char *source_root = getenv("WTWM_SOURCE_ROOT");
	if (source_root == NULL || source_root[0] == '\0') source_root = ".";
	int written = snprintf(path, sizeof(paths[0]), "%s/tests/fixtures/xbm/%s.xbm",
		source_root, name);
	assert(written >= 0 && (size_t)written < sizeof(paths[0]));
	return path;
}

#define FIXTURE(name) fixture(name)

static void assert_failure(struct wtwm_xbm *xbm, const char *fixture,
		const char *message) {
	char error[512];
	assert(!wtwm_xbm_load(xbm, fixture, error, sizeof(error)));
	assert(strstr(error, fixture) != NULL);
	assert(strstr(error, message) != NULL);
}

static void loads_odd_width_with_hotspots_and_comments(void) {
	static const unsigned char expected[] = {
		0x01, 0x10,
		0xaa, 0x0a,
		0xff, 0x1f,
	};
	struct wtwm_xbm xbm;
	wtwm_xbm_init(&xbm);
	char error[512];
	assert(wtwm_xbm_load(&xbm, FIXTURE("odd_width"), error, sizeof(error)));
	assert(strcmp(xbm.name, "odd") == 0);
	assert(xbm.width == 13);
	assert(xbm.height == 3);
	assert(xbm.x_hot == 12);
	assert(xbm.y_hot == 1);
	assert(xbm.stride == 2);
	assert(xbm.data_size == sizeof(expected));
	assert(memcmp(xbm.data, expected, sizeof(expected)) == 0);
	/* XBM bit zero is the left-most pixel. */
	assert((xbm.data[0] & (1u << 0)) != 0);
	assert((xbm.data[1] & (1u << 4)) != 0);
	wtwm_xbm_finish(&xbm);
}

static void loads_both_classic_storage_forms(void) {
	struct wtwm_xbm xbm;
	wtwm_xbm_init(&xbm);
	char error[512];
	assert(wtwm_xbm_load(&xbm, FIXTURE("classic_char"), error, sizeof(error)));
	assert(xbm.x_hot == -1 && xbm.y_hot == -1);
	assert(xbm.stride == 1 && xbm.data_size == 2);
	assert(xbm.data[0] == 0x81 && xbm.data[1] == 0x42);

	/* X10 shorts are low-byte first and restart at each scanline. */
	assert(wtwm_xbm_load(&xbm, FIXTURE("classic_short"), error, sizeof(error)));
	static const unsigned char expected[] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0xff };
	assert(xbm.width == 17 && xbm.height == 2);
	assert(xbm.stride == 3 && xbm.data_size == sizeof(expected));
	assert(memcmp(xbm.data, expected, sizeof(expected)) == 0);
	wtwm_xbm_finish(&xbm);
}

static void rejects_malformed_and_bounded_inputs_atomically(void) {
	const struct {
		const char *fixture;
		const char *message;
	} cases[] = {
		{FIXTURE("mismatched_prefix"), "prefix does not match"},
		{FIXTURE("truncated"), "truncated bitmap data"},
		{FIXTURE("excessive"), "excessive bitmap data"},
		{FIXTURE("invalid_token"), "invalid bitmap data value"},
		{FIXTURE("zero_width"), "invalid bitmap dimension"},
		{FIXTURE("dimension_limit"), "dimension exceeds limit"},
		{FIXTURE("data_limit"), "data exceeds limit"},
		{FIXTURE("dimension_overflow"), "invalid bitmap dimension"},
		{FIXTURE("missing_height"), "width and height must precede data"},
		{FIXTURE("unsigned_short"), "unsupported XBM declaration"},
		{FIXTURE("unterminated_comment"), "unterminated comment"},
	};

	struct wtwm_xbm xbm;
	wtwm_xbm_init(&xbm);
	char error[512];
	assert(wtwm_xbm_load(&xbm, FIXTURE("classic_char"), error, sizeof(error)));
	unsigned char *original_data = xbm.data;
	char *original_name = xbm.name;
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
		assert_failure(&xbm, cases[i].fixture, cases[i].message);
		assert(xbm.data == original_data);
		assert(xbm.name == original_name);
		assert(xbm.width == 8 && xbm.height == 2);
	}
	assert_failure(&xbm, FIXTURE("does-not-exist"), "unable to open");
	assert(xbm.data == original_data);

	const char *temporary_root = getenv("TMPDIR");
	if (temporary_root == NULL || temporary_root[0] == '\0') temporary_root = "/tmp";
	char path[1024];
	int written = snprintf(path, sizeof(path), "%s/wtwm-xbm-test-XXXXXX",
		temporary_root);
	assert(written >= 0 && (size_t)written < sizeof(path));
	int descriptor = mkstemp(path);
	assert(descriptor >= 0);
	assert(ftruncate(descriptor, (off_t)WTWM_XBM_MAX_FILE_BYTES + 1) == 0);
	assert(close(descriptor) == 0);
	assert_failure(&xbm, path, "file exceeds limit");
	assert(xbm.data == original_data && xbm.name == original_name);
	assert(unlink(path) == 0);

	assert(!wtwm_xbm_load(NULL, FIXTURE("classic_char"), error, sizeof(error)));
	assert(strstr(error, "invalid loader argument") != NULL);
	assert(!wtwm_xbm_load(&xbm, NULL, error, sizeof(error)));
	assert(strstr(error, "invalid loader argument") != NULL);
	wtwm_xbm_finish(&xbm);
}

int main(void) {
	loads_odd_width_with_hotspots_and_comments();
	loads_both_classic_storage_forms();
	rejects_malformed_and_bounded_inputs_atomically();
	puts("xbm tests passed");
	return 0;
}
