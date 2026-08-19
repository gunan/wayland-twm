/* SPDX-License-Identifier: MIT */
#ifndef WTWM_SESSION_STATE_H
#define WTWM_SESSION_STATE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WTWM_SESSION_STATE_MAX_ENTRIES 4096u
#define WTWM_SESSION_STATE_MAX_STRING 4096u

enum wtwm_session_client_kind {
	WTWM_SESSION_NATIVE = 1,
	WTWM_SESSION_XWAYLAND = 2,
};

/* Stable storage values; do not substitute enum wtwm_action_type on disk. */
enum wtwm_session_zoom_mode {
	WTWM_SESSION_ZOOM_NONE,
	WTWM_SESSION_ZOOM_VERTICAL,
	WTWM_SESSION_ZOOM_HORIZONTAL,
	WTWM_SESSION_ZOOM_FULL,
	WTWM_SESSION_ZOOM_LEFT,
	WTWM_SESSION_ZOOM_RIGHT,
	WTWM_SESSION_ZOOM_TOP,
	WTWM_SESSION_ZOOM_BOTTOM,
};

struct wtwm_session_box {
	int32_t x;
	int32_t y;
	int32_t width;
	int32_t height;
};

/*
 * Native identities use title/app_id.  Xwayland identities use name,
 * resource_name, and resource_class.  NULL and an empty string are distinct.
 * A state or record owns all non-NULL strings stored in it.
 */
struct wtwm_session_identity {
	enum wtwm_session_client_kind kind;
	char *title;
	char *app_id;
	char *name;
	char *resource_name;
	char *resource_class;
};

struct wtwm_session_record {
	struct wtwm_session_identity identity;
	struct wtwm_session_box geometry;
	bool iconified;
	bool has_manual_icon_position;
	int32_t icon_x;
	int32_t icon_y;
	uint32_t stack_rank;
	bool focused;
	bool auto_raise;
	enum wtwm_session_zoom_mode zoom_mode;
	struct wtwm_session_box zoom_saved_geometry;
};

struct wtwm_session_state {
	bool focus_root;
	struct wtwm_session_record *records;
	size_t record_count;
};

enum wtwm_session_result {
	WTWM_SESSION_OK,
	WTWM_SESSION_INVALID_ARGUMENT,
	WTWM_SESSION_NO_MEMORY,
	WTWM_SESSION_IO_ERROR,
	WTWM_SESSION_MALFORMED,
	WTWM_SESSION_UNSUPPORTED_VERSION,
	WTWM_SESSION_LIMIT_EXCEEDED,
};

enum wtwm_session_match_result {
	WTWM_SESSION_MATCH_NONE,
	WTWM_SESSION_MATCH_UNIQUE,
	WTWM_SESSION_MATCH_AMBIGUOUS,
};

void wtwm_session_record_finish(struct wtwm_session_record *record);
void wtwm_session_state_finish(struct wtwm_session_state *state);

/* Deep-copy record onto the end of state after validating its bounds. */
enum wtwm_session_result wtwm_session_state_append(
	struct wtwm_session_state *state,
	const struct wtwm_session_record *record);

/*
 * On a unique exact identity match, transfer the owned record to out and
 * remove it from state.  Ambiguous matches are deliberately left untouched.
 */
enum wtwm_session_match_result wtwm_session_state_take_unique(
	struct wtwm_session_state *state,
	const struct wtwm_session_identity *identity,
	struct wtwm_session_record *out);

/*
 * Derive $XDG_STATE_HOME/wtwm/state, falling back to
 * $HOME/.local/state/wtwm/state.  The caller owns *path.
 */
enum wtwm_session_result wtwm_session_state_default_path(
	char **path, char *error, size_t error_size);

/*
 * Save is an atomic same-directory replacement and creates missing parent
 * directories.  Load commits only after the whole file validates; ENOENT is
 * a successful empty state.  error may be NULL when error_size is zero.
 */
enum wtwm_session_result wtwm_session_state_save(
	const char *path, const struct wtwm_session_state *state,
	char *error, size_t error_size);
enum wtwm_session_result wtwm_session_state_load(
	const char *path, struct wtwm_session_state *state,
	char *error, size_t error_size);

const char *wtwm_session_result_message(enum wtwm_session_result result);

#endif
