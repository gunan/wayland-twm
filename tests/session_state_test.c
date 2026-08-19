/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE

#include <wtwm/session_state.h>

#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static char test_directory[] = "/tmp/wtwm-session-state-XXXXXX";

static struct wtwm_session_record native_record(
		const char *title, const char *app_id, uint32_t rank) {
	return (struct wtwm_session_record){
		.identity = {
			.kind = WTWM_SESSION_NATIVE,
			.title = (char *)title,
			.app_id = (char *)app_id,
		},
		.geometry = {-120, 34, 640, 480},
		.iconified = true,
		.has_manual_icon_position = true,
		.icon_x = -18,
		.icon_y = 911,
		.stack_rank = rank,
		.focused = rank == 0,
		.auto_raise = true,
		.zoom_mode = WTWM_SESSION_ZOOM_LEFT,
		.zoom_saved_geometry = {10, 20, 300, 200},
	};
}

static struct wtwm_session_record xwayland_record(
		const char *name, const char *instance, const char *class_name,
		uint32_t rank) {
	return (struct wtwm_session_record){
		.identity = {
			.kind = WTWM_SESSION_XWAYLAND,
			.name = (char *)name,
			.resource_name = (char *)instance,
			.resource_class = (char *)class_name,
		},
		.geometry = {44, -52, 800, 600},
		.icon_x = 0,
		.icon_y = 0,
		.stack_rank = rank,
		.zoom_mode = WTWM_SESSION_ZOOM_NONE,
	};
}

static char *join_path(const char *left, const char *right) {
	size_t left_length = strlen(left);
	size_t right_length = strlen(right);
	char *path = malloc(left_length + right_length + 2u);
	assert(path != NULL);
	memcpy(path, left, left_length);
	path[left_length] = '/';
	memcpy(path + left_length + 1u, right, right_length + 1u);
	return path;
}

static unsigned char *read_file(const char *path, size_t *length) {
	FILE *file = fopen(path, "rb");
	assert(file != NULL);
	assert(fseek(file, 0, SEEK_END) == 0);
	long size = ftell(file);
	assert(size >= 0);
	assert(fseek(file, 0, SEEK_SET) == 0);
	unsigned char *bytes = malloc((size_t)size + 1u);
	assert(bytes != NULL);
	assert(fread(bytes, 1, (size_t)size, file) == (size_t)size);
	assert(fclose(file) == 0);
	*length = (size_t)size;
	return bytes;
}

static void write_file(const char *path, const unsigned char *bytes,
		size_t length) {
	FILE *file = fopen(path, "wb");
	assert(file != NULL);
	assert(fwrite(bytes, 1, length, file) == length);
	assert(fclose(file) == 0);
}

static void assert_box(const struct wtwm_session_box *actual,
		int32_t x, int32_t y, int32_t width, int32_t height) {
	assert(actual->x == x);
	assert(actual->y == y);
	assert(actual->width == width);
	assert(actual->height == height);
}

static void test_round_trip(void) {
	char error[256];
	char *path = join_path(test_directory, "round-trip/state");
	struct wtwm_session_state saved = {0};
	struct wtwm_session_record native = native_record("native title", "org.wtwm", 0);
	struct wtwm_session_record x11 =
		xwayland_record("xterm title", "terminal", "XTerm", 1);
	assert(wtwm_session_state_append(&saved, &native) == WTWM_SESSION_OK);
	assert(wtwm_session_state_append(&saved, &x11) == WTWM_SESSION_OK);
	enum wtwm_session_result save_result =
		wtwm_session_state_save(path, &saved, error, sizeof(error));
	if (save_result != WTWM_SESSION_OK)
		fprintf(stderr, "round-trip save: %s\n", error);
	assert(save_result == WTWM_SESSION_OK);

	struct wtwm_session_state loaded = {.focus_root = true};
	assert(wtwm_session_state_load(path, &loaded, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	assert(!loaded.focus_root && loaded.record_count == 2);
	const struct wtwm_session_record *first = &loaded.records[0];
	assert(first->identity.kind == WTWM_SESSION_NATIVE);
	assert(strcmp(first->identity.title, "native title") == 0);
	assert(strcmp(first->identity.app_id, "org.wtwm") == 0);
	assert(first->identity.name == NULL);
	assert_box(&first->geometry, -120, 34, 640, 480);
	assert(first->iconified && first->has_manual_icon_position);
	assert(first->icon_x == -18 && first->icon_y == 911);
	assert(first->stack_rank == 0 && first->focused && first->auto_raise);
	assert(first->zoom_mode == WTWM_SESSION_ZOOM_LEFT);
	assert_box(&first->zoom_saved_geometry, 10, 20, 300, 200);

	const struct wtwm_session_record *second = &loaded.records[1];
	assert(second->identity.kind == WTWM_SESSION_XWAYLAND);
	assert(strcmp(second->identity.name, "xterm title") == 0);
	assert(strcmp(second->identity.resource_name, "terminal") == 0);
	assert(strcmp(second->identity.resource_class, "XTerm") == 0);
	assert(second->identity.title == NULL && second->identity.app_id == NULL);
	assert_box(&second->geometry, 44, -52, 800, 600);
	assert(second->stack_rank == 1 && !second->focused);
	assert(second->zoom_mode == WTWM_SESSION_ZOOM_NONE);
	assert_box(&second->zoom_saved_geometry, 0, 0, 0, 0);

	wtwm_session_state_finish(&loaded);
	wtwm_session_state_finish(&saved);
	free(path);
}

static void test_default_path(void) {
	char error[256];
	char *path = NULL;
	assert(setenv("XDG_STATE_HOME", "/tmp/wtwm-xdg", 1) == 0);
	assert(setenv("HOME", "/tmp/wtwm-home", 1) == 0);
	assert(wtwm_session_state_default_path(&path, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	assert(strcmp(path, "/tmp/wtwm-xdg/wtwm/state") == 0);
	free(path);

	assert(setenv("XDG_STATE_HOME", "", 1) == 0);
	assert(wtwm_session_state_default_path(&path, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	assert(strcmp(path, "/tmp/wtwm-home/.local/state/wtwm/state") == 0);
	free(path);

	assert(setenv("XDG_STATE_HOME", "relative", 1) == 0);
	assert(wtwm_session_state_default_path(&path, error, sizeof(error)) ==
		WTWM_SESSION_INVALID_ARGUMENT);
	assert(path == NULL && strstr(error, "absolute") != NULL);
	assert(unsetenv("XDG_STATE_HOME") == 0);
	assert(unsetenv("HOME") == 0);
	assert(wtwm_session_state_default_path(&path, error, sizeof(error)) ==
		WTWM_SESSION_INVALID_ARGUMENT);
	assert(path == NULL && strstr(error, "neither") != NULL);
}

static void assert_no_temporary_files(const char *directory) {
	DIR *stream = opendir(directory);
	assert(stream != NULL);
	struct dirent *entry;
	while ((entry = readdir(stream)) != NULL)
		assert(strstr(entry->d_name, ".tmp.") == NULL);
	assert(closedir(stream) == 0);
}

static void test_atomic_save_and_mode(void) {
	char error[256];
	char *path = join_path(test_directory, "atomic/deep/state");
	struct wtwm_session_state state = {.focus_root = true};
	struct wtwm_session_record record = native_record("atomic", "app", 0);
	record.focused = false;
	assert(wtwm_session_state_append(&state, &record) == WTWM_SESSION_OK);
	assert(wtwm_session_state_save(path, &state, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	struct stat first_status;
	assert(stat(path, &first_status) == 0);
	assert((first_status.st_mode & 0777) == 0600);
	size_t original_length;
	unsigned char *original = read_file(path, &original_length);

	state.records[0].geometry.width = 0;
	assert(wtwm_session_state_save(path, &state, error, sizeof(error)) ==
		WTWM_SESSION_LIMIT_EXCEEDED);
	size_t after_failure_length;
	unsigned char *after_failure = read_file(path, &after_failure_length);
	assert(after_failure_length == original_length);
	assert(memcmp(after_failure, original, original_length) == 0);
	free(after_failure);
	state.records[0].geometry.width = 777;
	assert(chmod(path, 0644) == 0);
	assert(wtwm_session_state_save(path, &state, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	struct stat second_status;
	assert(stat(path, &second_status) == 0);
	assert((second_status.st_mode & 0777) == 0600);
	assert(second_status.st_ino != first_status.st_ino);
	char *parent = join_path(test_directory, "atomic/deep");
	struct stat parent_status;
	assert(stat(parent, &parent_status) == 0);
	assert(S_ISDIR(parent_status.st_mode));
	assert((parent_status.st_mode & 0777) == 0700);
	assert_no_temporary_files(parent);
	free(parent);
	free(original);
	wtwm_session_state_finish(&state);
	free(path);
}

static void test_unsafe_parent_paths(void) {
	char error[256];
	struct wtwm_session_state state = {.focus_root = true};
	char *plain_file = join_path(test_directory, "plain-file");
	static const unsigned char byte = 0;
	write_file(plain_file, &byte, 1);
	char *child = join_path(plain_file, "state");
	assert(wtwm_session_state_save(child, &state, error, sizeof(error)) ==
		WTWM_SESSION_IO_ERROR);
	assert(strstr(error, "not a directory") != NULL);
	free(child);
	free(plain_file);

	char *traversal = join_path(test_directory, "../outside/state");
	assert(wtwm_session_state_save(traversal, &state, error, sizeof(error)) ==
		WTWM_SESSION_INVALID_ARGUMENT);
	assert(strstr(error, "parent-directory") != NULL);
	free(traversal);
}

static void test_missing_file(void) {
	char error[256];
	char *path = join_path(test_directory, "missing/state");
	struct wtwm_session_state state = {0};
	struct wtwm_session_record record = native_record("old", "old.app", 0);
	assert(wtwm_session_state_append(&state, &record) == WTWM_SESSION_OK);
	assert(wtwm_session_state_load(path, &state, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	assert(state.focus_root && state.record_count == 0 && state.records == NULL);
	wtwm_session_state_finish(&state);
	free(path);
}

static void test_unique_matching(void) {
	struct wtwm_session_state state = {.focus_root = true};
	struct wtwm_session_record record = native_record(NULL, "org.exact", 0);
	record.focused = false;
	assert(wtwm_session_state_append(&state, &record) == WTWM_SESSION_OK);
	struct wtwm_session_identity empty_title = {
		.kind = WTWM_SESSION_NATIVE,
		.title = "",
		.app_id = "org.exact",
	};
	struct wtwm_session_record taken = {0};
	assert(wtwm_session_state_take_unique(&state, &empty_title, &taken) ==
		WTWM_SESSION_MATCH_NONE);
	struct wtwm_session_identity exact = {
		.kind = WTWM_SESSION_NATIVE,
		.app_id = "org.exact",
	};
	assert(wtwm_session_state_take_unique(&state, &exact, &taken) ==
		WTWM_SESSION_MATCH_UNIQUE);
	assert(state.record_count == 0);
	assert(taken.identity.title == NULL);
	assert(strcmp(taken.identity.app_id, "org.exact") == 0);
	assert(wtwm_session_state_take_unique(&state, &exact, &record) ==
		WTWM_SESSION_MATCH_NONE);
	wtwm_session_record_finish(&taken);
	wtwm_session_state_finish(&state);
}

static void test_ambiguous_matching(void) {
	struct wtwm_session_state state = {.focus_root = true};
	struct wtwm_session_record first = xwayland_record("same", "same", "Same", 0);
	struct wtwm_session_record second = first;
	second.stack_rank = 1;
	assert(wtwm_session_state_append(&state, &first) == WTWM_SESSION_OK);
	assert(wtwm_session_state_append(&state, &second) == WTWM_SESSION_OK);
	struct wtwm_session_record taken = {0};
	assert(wtwm_session_state_take_unique(&state, &first.identity, &taken) ==
		WTWM_SESSION_MATCH_AMBIGUOUS);
	assert(state.record_count == 2 && taken.identity.name == NULL);
	wtwm_session_state_finish(&state);
}

static void put_u32(unsigned char *bytes, uint32_t value) {
	bytes[0] = (unsigned char)(value >> 24);
	bytes[1] = (unsigned char)(value >> 16);
	bytes[2] = (unsigned char)(value >> 8);
	bytes[3] = (unsigned char)value;
}

static void expect_failed_load(const char *path,
		enum wtwm_session_result expected) {
	char error[256];
	struct wtwm_session_state preserved = {0};
	struct wtwm_session_record old = native_record("preserved", "old.app", 0);
	assert(wtwm_session_state_append(&preserved, &old) == WTWM_SESSION_OK);
	assert(wtwm_session_state_load(path, &preserved, error, sizeof(error)) ==
		expected);
	assert(error[0] != '\0');
	assert(!preserved.focus_root && preserved.record_count == 1);
	assert(strcmp(preserved.records[0].identity.title, "preserved") == 0);
	assert(preserved.records[0].geometry.width == 640);
	wtwm_session_state_finish(&preserved);
}

static void test_malformed_files_and_preservation(void) {
	char error[256];
	char *valid_path = join_path(test_directory, "malformed/valid");
	char *case_path = join_path(test_directory, "malformed/case");
	struct wtwm_session_state state = {0};
	struct wtwm_session_record record = native_record("native", "app", 0);
	assert(wtwm_session_state_append(&state, &record) == WTWM_SESSION_OK);
	assert(wtwm_session_state_save(valid_path, &state, error, sizeof(error)) ==
		WTWM_SESSION_OK);
	size_t length;
	unsigned char *valid = read_file(valid_path, &length);
	assert(length > 80);
	unsigned char *modified = malloc(length + 1u);
	assert(modified != NULL);

	write_file(case_path, valid, length / 2u);
	expect_failed_load(case_path, WTWM_SESSION_MALFORMED);

	memcpy(modified, valid, length);
	put_u32(modified + 8, 2);
	write_file(case_path, modified, length);
	expect_failed_load(case_path, WTWM_SESSION_UNSUPPORTED_VERSION);

	memcpy(modified, valid, length);
	modified[24] = 3;
	write_file(case_path, modified, length);
	expect_failed_load(case_path, WTWM_SESSION_MALFORMED);

	memcpy(modified, valid, length);
	put_u32(modified + 36, 1000001u);
	write_file(case_path, modified, length);
	expect_failed_load(case_path, WTWM_SESSION_LIMIT_EXCEEDED);

	memcpy(modified, valid, length);
	modified[72] = 0x10;
	modified[73] = 0x01;
	write_file(case_path, modified, length);
	expect_failed_load(case_path, WTWM_SESSION_LIMIT_EXCEEDED);

	memcpy(modified, valid, length);
	put_u32(modified + 16, WTWM_SESSION_STATE_MAX_ENTRIES + 1u);
	write_file(case_path, modified, length);
	expect_failed_load(case_path, WTWM_SESSION_LIMIT_EXCEEDED);

	memcpy(modified, valid, length);
	modified[length] = 0xff;
	write_file(case_path, modified, length + 1u);
	expect_failed_load(case_path, WTWM_SESSION_MALFORMED);

	memcpy(modified, valid, length);
	modified[27] = 1;
	write_file(case_path, modified, length);
	expect_failed_load(case_path, WTWM_SESSION_MALFORMED);

	char oversized[WTWM_SESSION_STATE_MAX_STRING + 2u];
	memset(oversized, 'x', sizeof(oversized) - 1u);
	oversized[sizeof(oversized) - 1u] = '\0';
	struct wtwm_session_record too_long = native_record(oversized, "app", 0);
	assert(wtwm_session_state_append(&state, &too_long) ==
		WTWM_SESSION_LIMIT_EXCEEDED);

	free(modified);
	free(valid);
	wtwm_session_state_finish(&state);
	free(case_path);
	free(valid_path);
}

int main(void) {
	assert(mkdtemp(test_directory) != NULL);
	test_round_trip();
	test_default_path();
	test_atomic_save_and_mode();
	test_unsafe_parent_paths();
	test_missing_file();
	test_unique_matching();
	test_ambiguous_matching();
	test_malformed_files_and_preservation();
	return 0;
}
