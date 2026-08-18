/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L

#include <wtwm/session_state.h>

#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SESSION_FORMAT_VERSION 1u
#define SESSION_COORDINATE_LIMIT 1000000
#define SESSION_DIMENSION_LIMIT 1000000
#define SESSION_PATH_LIMIT 16384u

#define RECORD_ICONIFIED (1u << 0)
#define RECORD_MANUAL_ICON (1u << 1)
#define RECORD_FOCUSED (1u << 2)
#define RECORD_AUTO_RAISE (1u << 3)
#define RECORD_FLAG_MASK (RECORD_ICONIFIED | RECORD_MANUAL_ICON | \
	RECORD_FOCUSED | RECORD_AUTO_RAISE)

static const unsigned char session_magic[8] = {
	'W', 'T', 'W', 'M', 'S', 'T', 'A', 'T',
};

static void clear_error(char *error, size_t error_size) {
	if (error != NULL && error_size != 0) error[0] = '\0';
}

static void set_error(char *error, size_t error_size, const char *format, ...) {
	if (error == NULL || error_size == 0) return;
	va_list arguments;
	va_start(arguments, format);
	(void)vsnprintf(error, error_size, format, arguments);
	va_end(arguments);
}

static bool coordinate_valid(int32_t value) {
	return value >= -SESSION_COORDINATE_LIMIT &&
		value <= SESSION_COORDINATE_LIMIT;
}

static bool dimensions_valid(const struct wtwm_session_box *box) {
	return box->width > 0 && box->width <= SESSION_DIMENSION_LIMIT &&
		box->height > 0 && box->height <= SESSION_DIMENSION_LIMIT;
}

static bool box_valid(const struct wtwm_session_box *box) {
	return coordinate_valid(box->x) && coordinate_valid(box->y) &&
		dimensions_valid(box);
}

static bool box_empty(const struct wtwm_session_box *box) {
	return box->x == 0 && box->y == 0 && box->width == 0 && box->height == 0;
}

static enum wtwm_session_result string_valid(const char *value) {
	if (value == NULL) return WTWM_SESSION_OK;
	size_t length = strnlen(value, WTWM_SESSION_STATE_MAX_STRING + 1u);
	return length <= WTWM_SESSION_STATE_MAX_STRING ? WTWM_SESSION_OK :
		WTWM_SESSION_LIMIT_EXCEEDED;
}

static enum wtwm_session_result identity_valid(
		const struct wtwm_session_identity *identity) {
	if (identity == NULL) return WTWM_SESSION_INVALID_ARGUMENT;
	if (identity->kind == WTWM_SESSION_NATIVE) {
		if (identity->name != NULL || identity->resource_name != NULL ||
				identity->resource_class != NULL) return WTWM_SESSION_MALFORMED;
	} else if (identity->kind == WTWM_SESSION_XWAYLAND) {
		if (identity->title != NULL || identity->app_id != NULL)
			return WTWM_SESSION_MALFORMED;
	} else {
		return WTWM_SESSION_MALFORMED;
	}

	const char *const values[] = {
		identity->title, identity->app_id, identity->name,
		identity->resource_name, identity->resource_class,
	};
	for (size_t index = 0; index < sizeof(values) / sizeof(values[0]); ++index) {
		enum wtwm_session_result result = string_valid(values[index]);
		if (result != WTWM_SESSION_OK) return result;
	}
	return WTWM_SESSION_OK;
}

static enum wtwm_session_result record_valid(
		const struct wtwm_session_record *record) {
	if (record == NULL) return WTWM_SESSION_INVALID_ARGUMENT;
	enum wtwm_session_result result = identity_valid(&record->identity);
	if (result != WTWM_SESSION_OK) return result;
	if (!box_valid(&record->geometry) ||
			!coordinate_valid(record->icon_x) ||
			!coordinate_valid(record->icon_y) ||
			record->stack_rank >= WTWM_SESSION_STATE_MAX_ENTRIES)
		return WTWM_SESSION_LIMIT_EXCEEDED;
	if (record->zoom_mode < WTWM_SESSION_ZOOM_NONE ||
			record->zoom_mode > WTWM_SESSION_ZOOM_BOTTOM)
		return WTWM_SESSION_MALFORMED;
	if (!box_empty(&record->zoom_saved_geometry) &&
			!box_valid(&record->zoom_saved_geometry))
		return WTWM_SESSION_LIMIT_EXCEEDED;
	if (record->zoom_mode != WTWM_SESSION_ZOOM_NONE &&
			box_empty(&record->zoom_saved_geometry))
		return WTWM_SESSION_MALFORMED;
	return WTWM_SESSION_OK;
}

static enum wtwm_session_result state_valid(
		const struct wtwm_session_state *state) {
	if (state == NULL || (state->record_count != 0 && state->records == NULL))
		return WTWM_SESSION_INVALID_ARGUMENT;
	if (state->record_count > WTWM_SESSION_STATE_MAX_ENTRIES)
		return WTWM_SESSION_LIMIT_EXCEEDED;
	size_t focused = 0;
	for (size_t index = 0; index < state->record_count; ++index) {
		enum wtwm_session_result result = record_valid(&state->records[index]);
		if (result != WTWM_SESSION_OK) return result;
		if (state->records[index].stack_rank >= state->record_count)
			return WTWM_SESSION_LIMIT_EXCEEDED;
		if (state->records[index].focused) ++focused;
	}
	if (focused > 1 || (state->focus_root && focused != 0))
		return WTWM_SESSION_MALFORMED;
	return WTWM_SESSION_OK;
}

static char *copy_string(const char *source) {
	if (source == NULL) return NULL;
	size_t length = strlen(source) + 1u;
	char *copy = malloc(length);
	if (copy != NULL) memcpy(copy, source, length);
	return copy;
}

void wtwm_session_record_finish(struct wtwm_session_record *record) {
	if (record == NULL) return;
	free(record->identity.title);
	free(record->identity.app_id);
	free(record->identity.name);
	free(record->identity.resource_name);
	free(record->identity.resource_class);
	memset(record, 0, sizeof(*record));
}

void wtwm_session_state_finish(struct wtwm_session_state *state) {
	if (state == NULL) return;
	for (size_t index = 0; index < state->record_count; ++index)
		wtwm_session_record_finish(&state->records[index]);
	free(state->records);
	memset(state, 0, sizeof(*state));
}

static enum wtwm_session_result record_copy(
		struct wtwm_session_record *destination,
		const struct wtwm_session_record *source) {
	*destination = *source;
	destination->identity.title = NULL;
	destination->identity.app_id = NULL;
	destination->identity.name = NULL;
	destination->identity.resource_name = NULL;
	destination->identity.resource_class = NULL;

	char **const destinations[] = {
		&destination->identity.title, &destination->identity.app_id,
		&destination->identity.name, &destination->identity.resource_name,
		&destination->identity.resource_class,
	};
	const char *const sources[] = {
		source->identity.title, source->identity.app_id, source->identity.name,
		source->identity.resource_name, source->identity.resource_class,
	};
	for (size_t index = 0; index < sizeof(sources) / sizeof(sources[0]); ++index) {
		if (sources[index] == NULL) continue;
		*destinations[index] = copy_string(sources[index]);
		if (*destinations[index] == NULL) {
			wtwm_session_record_finish(destination);
			return WTWM_SESSION_NO_MEMORY;
		}
	}
	return WTWM_SESSION_OK;
}

enum wtwm_session_result wtwm_session_state_append(
		struct wtwm_session_state *state,
		const struct wtwm_session_record *record) {
	if (state == NULL || state->record_count > WTWM_SESSION_STATE_MAX_ENTRIES ||
			(state->record_count != 0 && state->records == NULL))
		return WTWM_SESSION_INVALID_ARGUMENT;
	enum wtwm_session_result result = record_valid(record);
	if (result != WTWM_SESSION_OK) return result;
	if (state->record_count >= WTWM_SESSION_STATE_MAX_ENTRIES)
		return WTWM_SESSION_LIMIT_EXCEEDED;

	struct wtwm_session_record copy = {0};
	result = record_copy(&copy, record);
	if (result != WTWM_SESSION_OK) return result;
	if (state->record_count == SIZE_MAX / sizeof(*state->records)) {
		wtwm_session_record_finish(&copy);
		return WTWM_SESSION_LIMIT_EXCEEDED;
	}
	struct wtwm_session_record *records = realloc(state->records,
		(state->record_count + 1u) * sizeof(*records));
	if (records == NULL) {
		wtwm_session_record_finish(&copy);
		return WTWM_SESSION_NO_MEMORY;
	}
	state->records = records;
	state->records[state->record_count++] = copy;
	return WTWM_SESSION_OK;
}

static bool strings_equal(const char *left, const char *right) {
	if (left == NULL || right == NULL) return left == right;
	return strcmp(left, right) == 0;
}

static bool identities_equal(const struct wtwm_session_identity *left,
		const struct wtwm_session_identity *right) {
	return left->kind == right->kind &&
		strings_equal(left->title, right->title) &&
		strings_equal(left->app_id, right->app_id) &&
		strings_equal(left->name, right->name) &&
		strings_equal(left->resource_name, right->resource_name) &&
		strings_equal(left->resource_class, right->resource_class);
}

enum wtwm_session_match_result wtwm_session_state_take_unique(
		struct wtwm_session_state *state,
		const struct wtwm_session_identity *identity,
		struct wtwm_session_record *out) {
	if (state == NULL || identity == NULL || out == NULL ||
			state->record_count > WTWM_SESSION_STATE_MAX_ENTRIES ||
			(state->record_count != 0 && state->records == NULL) ||
			identity_valid(identity) != WTWM_SESSION_OK)
		return WTWM_SESSION_MATCH_NONE;
	size_t match = 0;
	size_t matches = 0;
	for (size_t index = 0; index < state->record_count; ++index) {
		if (!identities_equal(&state->records[index].identity, identity)) continue;
		match = index;
		if (++matches > 1) return WTWM_SESSION_MATCH_AMBIGUOUS;
	}
	if (matches == 0) return WTWM_SESSION_MATCH_NONE;
	*out = state->records[match];
	if (match + 1u < state->record_count) {
		memmove(&state->records[match], &state->records[match + 1u],
			(state->record_count - match - 1u) * sizeof(*state->records));
	}
	--state->record_count;
	return WTWM_SESSION_MATCH_UNIQUE;
}

static bool path_is_absolute(const char *path) {
	return path != NULL && path[0] == '/';
}

enum wtwm_session_result wtwm_session_state_default_path(
		char **path, char *error, size_t error_size) {
	clear_error(error, error_size);
	if (path == NULL) {
		set_error(error, error_size, "state path output is NULL");
		return WTWM_SESSION_INVALID_ARGUMENT;
	}
	*path = NULL;
	const char *root = getenv("XDG_STATE_HOME");
	const char *suffix = "/wtwm/state";
	if (root == NULL || root[0] == '\0') {
		root = getenv("HOME");
		suffix = "/.local/state/wtwm/state";
		if (root == NULL || root[0] == '\0') {
			set_error(error, error_size,
				"neither XDG_STATE_HOME nor HOME is set");
			return WTWM_SESSION_INVALID_ARGUMENT;
		}
	}
	if (!path_is_absolute(root)) {
		set_error(error, error_size, "state directory must be an absolute path");
		return WTWM_SESSION_INVALID_ARGUMENT;
	}
	size_t root_length = strlen(root);
	size_t suffix_length = strlen(suffix);
	if (root_length > SESSION_PATH_LIMIT || suffix_length > SESSION_PATH_LIMIT ||
			root_length + suffix_length + 1u > SESSION_PATH_LIMIT) {
		set_error(error, error_size, "derived state path is too long");
		return WTWM_SESSION_LIMIT_EXCEEDED;
	}
	char *derived = malloc(root_length + suffix_length + 1u);
	if (derived == NULL) {
		set_error(error, error_size, "could not allocate state path");
		return WTWM_SESSION_NO_MEMORY;
	}
	memcpy(derived, root, root_length);
	memcpy(derived + root_length, suffix, suffix_length + 1u);
	*path = derived;
	return WTWM_SESSION_OK;
}

static void put_u16(unsigned char output[2], uint16_t value) {
	output[0] = (unsigned char)(value >> 8);
	output[1] = (unsigned char)value;
}

static void put_u32(unsigned char output[4], uint32_t value) {
	output[0] = (unsigned char)(value >> 24);
	output[1] = (unsigned char)(value >> 16);
	output[2] = (unsigned char)(value >> 8);
	output[3] = (unsigned char)value;
}

static uint16_t get_u16(const unsigned char input[2]) {
	return ((uint16_t)input[0] << 8) | input[1];
}

static uint32_t get_u32(const unsigned char input[4]) {
	return ((uint32_t)input[0] << 24) | ((uint32_t)input[1] << 16) |
		((uint32_t)input[2] << 8) | input[3];
}

static bool write_bytes(FILE *file, const void *bytes, size_t length) {
	return length == 0 || fwrite(bytes, 1, length, file) == length;
}

static bool write_u16(FILE *file, uint16_t value) {
	unsigned char bytes[2];
	put_u16(bytes, value);
	return write_bytes(file, bytes, sizeof(bytes));
}

static bool write_u32(FILE *file, uint32_t value) {
	unsigned char bytes[4];
	put_u32(bytes, value);
	return write_bytes(file, bytes, sizeof(bytes));
}

static bool write_i32(FILE *file, int32_t value) {
	return write_u32(file, (uint32_t)value);
}

static bool write_string(FILE *file, const char *value) {
	if (value == NULL) return write_u16(file, UINT16_MAX);
	size_t length = strlen(value);
	return write_u16(file, (uint16_t)length) && write_bytes(file, value, length);
}

static bool write_box(FILE *file, const struct wtwm_session_box *box) {
	return write_i32(file, box->x) && write_i32(file, box->y) &&
		write_i32(file, box->width) && write_i32(file, box->height);
}

static bool write_record(FILE *file, const struct wtwm_session_record *record) {
	unsigned char header[4] = {
		(unsigned char)record->identity.kind,
		(record->iconified ? RECORD_ICONIFIED : 0) |
			(record->has_manual_icon_position ? RECORD_MANUAL_ICON : 0) |
			(record->focused ? RECORD_FOCUSED : 0) |
			(record->auto_raise ? RECORD_AUTO_RAISE : 0),
		(unsigned char)record->zoom_mode,
		0,
	};
	return write_bytes(file, header, sizeof(header)) &&
		write_box(file, &record->geometry) &&
		write_i32(file, record->icon_x) && write_i32(file, record->icon_y) &&
		write_u32(file, record->stack_rank) &&
		write_box(file, &record->zoom_saved_geometry) &&
		write_string(file, record->identity.title) &&
		write_string(file, record->identity.app_id) &&
		write_string(file, record->identity.name) &&
		write_string(file, record->identity.resource_name) &&
		write_string(file, record->identity.resource_class);
}

static bool write_state(FILE *file, const struct wtwm_session_state *state) {
	if (!write_bytes(file, session_magic, sizeof(session_magic)) ||
			!write_u32(file, SESSION_FORMAT_VERSION) ||
			!write_u32(file, state->focus_root ? 1u : 0u) ||
			!write_u32(file, (uint32_t)state->record_count) ||
			!write_u32(file, 0)) return false;
	for (size_t index = 0; index < state->record_count; ++index) {
		if (!write_record(file, &state->records[index])) return false;
	}
	return true;
}

static enum wtwm_session_result ensure_directory(
		const char *path, char *error, size_t error_size) {
	if (mkdir(path, 0700) == 0) return WTWM_SESSION_OK;
	if (errno != EEXIST) {
		set_error(error, error_size, "could not create state directory %s: %s",
			path, strerror(errno));
		return WTWM_SESSION_IO_ERROR;
	}
	struct stat status;
	if (stat(path, &status) != 0 || !S_ISDIR(status.st_mode)) {
		set_error(error, error_size,
			"state path component is not a directory: %s", path);
		return WTWM_SESSION_IO_ERROR;
	}
	return WTWM_SESSION_OK;
}

static bool path_has_parent_component(const char *path) {
	const char *component = path;
	for (const char *cursor = path;; ++cursor) {
		if (*cursor != '/' && *cursor != '\0') continue;
		if ((size_t)(cursor - component) == 2u && component[0] == '.' &&
				component[1] == '.') return true;
		if (*cursor == '\0') return false;
		component = cursor + 1;
	}
}

static enum wtwm_session_result make_parent_directories(
		const char *path, char **parent_out, char *error, size_t error_size) {
	if (path == NULL || path[0] == '\0' || strlen(path) >= SESSION_PATH_LIMIT) {
		set_error(error, error_size, "state path is empty or too long");
		return WTWM_SESSION_INVALID_ARGUMENT;
	}
	if (path_has_parent_component(path)) {
		set_error(error, error_size,
			"state path may not contain a parent-directory component");
		return WTWM_SESSION_INVALID_ARGUMENT;
	}
	char *copy = copy_string(path);
	if (copy == NULL) {
		set_error(error, error_size, "could not allocate state parent path");
		return WTWM_SESSION_NO_MEMORY;
	}
	char *slash = strrchr(copy, '/');
	if (slash == NULL) {
		free(copy);
		copy = copy_string(".");
		if (copy == NULL) {
			set_error(error, error_size, "could not allocate state parent path");
			return WTWM_SESSION_NO_MEMORY;
		}
	} else if (slash == copy) {
		slash[1] = '\0';
	} else {
		*slash = '\0';
	}

	char *cursor = copy;
	if (*cursor == '/') ++cursor;
	for (;; ++cursor) {
		if (*cursor != '/' && *cursor != '\0') continue;
		char saved = *cursor;
		*cursor = '\0';
		const char *component = strrchr(copy, '/');
		component = component != NULL ? component + 1 : copy;
		if (copy[0] != '\0' && strcmp(component, ".") != 0) {
			enum wtwm_session_result result =
				ensure_directory(copy, error, error_size);
			if (result != WTWM_SESSION_OK) {
				free(copy);
				return result;
			}
		}
		*cursor = saved;
		if (saved == '\0') break;
	}
	*parent_out = copy;
	return WTWM_SESSION_OK;
}

enum wtwm_session_result wtwm_session_state_save(
		const char *path, const struct wtwm_session_state *state,
		char *error, size_t error_size) {
	clear_error(error, error_size);
	enum wtwm_session_result result = state_valid(state);
	if (result != WTWM_SESSION_OK) {
		set_error(error, error_size, "invalid session state: %s",
			wtwm_session_result_message(result));
		return result;
	}
	char *parent = NULL;
	result = make_parent_directories(path, &parent, error, error_size);
	if (result != WTWM_SESSION_OK) return result;
	free(parent);

	size_t length = strlen(path);
	static const char suffix[] = ".tmp.XXXXXX";
	if (length + sizeof(suffix) > SESSION_PATH_LIMIT) {
		set_error(error, error_size, "state temporary path is too long");
		return WTWM_SESSION_LIMIT_EXCEEDED;
	}
	char *temporary = malloc(length + sizeof(suffix));
	if (temporary == NULL) return WTWM_SESSION_NO_MEMORY;
	memcpy(temporary, path, length);
	memcpy(temporary + length, suffix, sizeof(suffix));

	int descriptor = mkstemp(temporary);
	if (descriptor < 0) {
		set_error(error, error_size, "could not create state file: %s",
			strerror(errno));
		free(temporary);
		return WTWM_SESSION_IO_ERROR;
	}
	if (fchmod(descriptor, 0600) != 0) {
		set_error(error, error_size, "could not secure state file: %s",
			strerror(errno));
		(void)close(descriptor);
		(void)unlink(temporary);
		free(temporary);
		return WTWM_SESSION_IO_ERROR;
	}
	FILE *file = fdopen(descriptor, "wb");
	if (file == NULL) {
		set_error(error, error_size, "could not open state stream: %s",
			strerror(errno));
		(void)close(descriptor);
		(void)unlink(temporary);
		free(temporary);
		return WTWM_SESSION_IO_ERROR;
	}

	bool written = write_state(file, state);
	if (written && fflush(file) != 0) written = false;
	if (written && fsync(fileno(file)) != 0) written = false;
	int saved_errno = written ? 0 : (errno != 0 ? errno : EIO);
	if (fclose(file) != 0 && written) {
		written = false;
		saved_errno = errno;
	}
	if (!written) {
		set_error(error, error_size, "could not write state file: %s",
			strerror(saved_errno));
		(void)unlink(temporary);
		free(temporary);
		return WTWM_SESSION_IO_ERROR;
	}
	if (rename(temporary, path) != 0) {
		set_error(error, error_size, "could not replace state file: %s",
			strerror(errno));
		(void)unlink(temporary);
		free(temporary);
		return WTWM_SESSION_IO_ERROR;
	}
	free(temporary);
	return WTWM_SESSION_OK;
}

static int read_bytes(FILE *file, void *bytes, size_t length) {
	if (length == 0) return 1;
	if (fread(bytes, 1, length, file) == length) return 1;
	return ferror(file) ? -1 : 0;
}

static int read_u16(FILE *file, uint16_t *value) {
	unsigned char bytes[2];
	int result = read_bytes(file, bytes, sizeof(bytes));
	if (result == 1) *value = get_u16(bytes);
	return result;
}

static int read_u32(FILE *file, uint32_t *value) {
	unsigned char bytes[4];
	int result = read_bytes(file, bytes, sizeof(bytes));
	if (result == 1) *value = get_u32(bytes);
	return result;
}

static int read_i32(FILE *file, int32_t *value) {
	uint32_t encoded;
	int result = read_u32(file, &encoded);
	if (result == 1) {
		if (encoded <= INT32_MAX) *value = (int32_t)encoded;
		else *value = -1 - (int32_t)(UINT32_MAX - encoded);
	}
	return result;
}

static int read_string(FILE *file, char **value) {
	uint16_t length;
	int result = read_u16(file, &length);
	if (result != 1) return result;
	if (length == UINT16_MAX) {
		*value = NULL;
		return 1;
	}
	if (length > WTWM_SESSION_STATE_MAX_STRING) return -4;
	char *string = malloc((size_t)length + 1u);
	if (string == NULL) return -3;
	result = read_bytes(file, string, length);
	if (result != 1) {
		free(string);
		return result;
	}
	if (memchr(string, '\0', length) != NULL) {
		free(string);
		return -2;
	}
	string[length] = '\0';
	*value = string;
	return 1;
}

static int read_box(FILE *file, struct wtwm_session_box *box) {
	int result = read_i32(file, &box->x);
	if (result == 1) result = read_i32(file, &box->y);
	if (result == 1) result = read_i32(file, &box->width);
	if (result == 1) result = read_i32(file, &box->height);
	return result;
}

static int read_record(FILE *file, struct wtwm_session_record *record) {
	unsigned char header[4];
	int result = read_bytes(file, header, sizeof(header));
	if (result != 1) return result;
	if ((header[1] & ~RECORD_FLAG_MASK) != 0 || header[3] != 0) return -2;
	record->identity.kind = (enum wtwm_session_client_kind)header[0];
	record->iconified = (header[1] & RECORD_ICONIFIED) != 0;
	record->has_manual_icon_position = (header[1] & RECORD_MANUAL_ICON) != 0;
	record->focused = (header[1] & RECORD_FOCUSED) != 0;
	record->auto_raise = (header[1] & RECORD_AUTO_RAISE) != 0;
	record->zoom_mode = (enum wtwm_session_zoom_mode)header[2];
	result = read_box(file, &record->geometry);
	if (result == 1) result = read_i32(file, &record->icon_x);
	if (result == 1) result = read_i32(file, &record->icon_y);
	if (result == 1) result = read_u32(file, &record->stack_rank);
	if (result == 1) result = read_box(file, &record->zoom_saved_geometry);
	char **const strings[] = {
		&record->identity.title, &record->identity.app_id,
		&record->identity.name, &record->identity.resource_name,
		&record->identity.resource_class,
	};
	for (size_t index = 0;
			result == 1 && index < sizeof(strings) / sizeof(strings[0]); ++index)
		result = read_string(file, strings[index]);
	return result;
}

static enum wtwm_session_result parse_state(FILE *file,
		struct wtwm_session_state *state, char *error, size_t error_size) {
	unsigned char magic[sizeof(session_magic)];
	uint32_t version;
	uint32_t flags;
	uint32_t count;
	uint32_t reserved;
	int read = read_bytes(file, magic, sizeof(magic));
	if (read == 1) read = read_u32(file, &version);
	if (read == 1) read = read_u32(file, &flags);
	if (read == 1) read = read_u32(file, &count);
	if (read == 1) read = read_u32(file, &reserved);
	if (read != 1) {
		set_error(error, error_size, read < 0 ?
			"could not read state file" : "state file is truncated");
		return read < 0 ? WTWM_SESSION_IO_ERROR : WTWM_SESSION_MALFORMED;
	}
	if (memcmp(magic, session_magic, sizeof(magic)) != 0) {
		set_error(error, error_size, "state file has an invalid signature");
		return WTWM_SESSION_MALFORMED;
	}
	if (version != SESSION_FORMAT_VERSION) {
		set_error(error, error_size, "unsupported state file version %u", version);
		return WTWM_SESSION_UNSUPPORTED_VERSION;
	}
	if ((flags & ~1u) != 0 || reserved != 0) {
		set_error(error, error_size, "state file header has invalid flags");
		return WTWM_SESSION_MALFORMED;
	}
	if (count > WTWM_SESSION_STATE_MAX_ENTRIES) {
		set_error(error, error_size, "state file contains too many records");
		return WTWM_SESSION_LIMIT_EXCEEDED;
	}
	state->focus_root = (flags & 1u) != 0;
	for (uint32_t index = 0; index < count; ++index) {
		struct wtwm_session_record record = {0};
		read = read_record(file, &record);
		if (read != 1) {
			wtwm_session_record_finish(&record);
			set_error(error, error_size, read == -3 ?
				"could not allocate state record" : read == -2 ?
				"state record is malformed" : read == -4 ?
				"state record exceeds a format bound" : read < 0 ?
				"could not read state record" : "state file is truncated");
			return read == -3 ? WTWM_SESSION_NO_MEMORY : read == -2 ?
				WTWM_SESSION_MALFORMED : read == -4 ?
				WTWM_SESSION_LIMIT_EXCEEDED : read < 0 ?
				WTWM_SESSION_IO_ERROR : WTWM_SESSION_MALFORMED;
		}
		if (record.stack_rank >= count) {
			wtwm_session_record_finish(&record);
			set_error(error, error_size, "state record has invalid stack rank");
			return WTWM_SESSION_LIMIT_EXCEEDED;
		}
		enum wtwm_session_result result =
			wtwm_session_state_append(state, &record);
		wtwm_session_record_finish(&record);
		if (result != WTWM_SESSION_OK) {
			set_error(error, error_size, "invalid state record: %s",
				wtwm_session_result_message(result));
			return result;
		}
	}
	unsigned char trailing;
	read = read_bytes(file, &trailing, 1);
	if (read != 0) {
		set_error(error, error_size, read < 0 ?
			"could not finish reading state file" :
			"state file has trailing data");
		return read < 0 ? WTWM_SESSION_IO_ERROR : WTWM_SESSION_MALFORMED;
	}
	enum wtwm_session_result result = state_valid(state);
	if (result != WTWM_SESSION_OK) {
		set_error(error, error_size, "invalid complete state: %s",
			wtwm_session_result_message(result));
	}
	return result;
}

enum wtwm_session_result wtwm_session_state_load(
		const char *path, struct wtwm_session_state *state,
		char *error, size_t error_size) {
	clear_error(error, error_size);
	if (path == NULL || path[0] == '\0' || state == NULL) {
		set_error(error, error_size, "state path or destination is invalid");
		return WTWM_SESSION_INVALID_ARGUMENT;
	}
	FILE *file = fopen(path, "rb");
	if (file == NULL) {
		if (errno == ENOENT) {
			wtwm_session_state_finish(state);
			state->focus_root = true;
			return WTWM_SESSION_OK;
		}
		set_error(error, error_size, "could not open state file: %s",
			strerror(errno));
		return WTWM_SESSION_IO_ERROR;
	}
	struct wtwm_session_state loaded = {0};
	enum wtwm_session_result result =
		parse_state(file, &loaded, error, error_size);
	if (fclose(file) != 0 && result == WTWM_SESSION_OK) {
		set_error(error, error_size, "could not close state file: %s",
			strerror(errno));
		result = WTWM_SESSION_IO_ERROR;
	}
	if (result != WTWM_SESSION_OK) {
		wtwm_session_state_finish(&loaded);
		return result;
	}
	wtwm_session_state_finish(state);
	*state = loaded;
	return WTWM_SESSION_OK;
}

const char *wtwm_session_result_message(enum wtwm_session_result result) {
	switch (result) {
	case WTWM_SESSION_OK:
		return "success";
	case WTWM_SESSION_INVALID_ARGUMENT:
		return "invalid argument";
	case WTWM_SESSION_NO_MEMORY:
		return "out of memory";
	case WTWM_SESSION_IO_ERROR:
		return "input/output error";
	case WTWM_SESSION_MALFORMED:
		return "malformed state";
	case WTWM_SESSION_UNSUPPORTED_VERSION:
		return "unsupported state version";
	case WTWM_SESSION_LIMIT_EXCEEDED:
		return "state bound exceeded";
	}
	return "unknown session-state result";
}
