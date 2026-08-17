/* SPDX-License-Identifier: MIT */
#ifndef WTWM_BINDINGS_H
#define WTWM_BINDINGS_H

#include <wtwm/config.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * A trigger context is one concrete event context, not a configuration mask.
 * For a named key binding, client is the candidate client to which the action
 * would be applied.  It may be NULL for ordinary context bindings.
 */
struct wtwm_binding_trigger {
	enum wtwm_binding_type type;
	unsigned button;
	const char *key;
	uint32_t modifiers;
	uint32_t context;
	const struct wtwm_client_identity *client;
};

/* twm initially observes Shift, Control and Meta/Mod1 globally. */
#define WTWM_BINDING_BASE_MODIFIERS \
	(WTWM_MOD_SHIFT | WTWM_MOD_CONTROL | WTWM_MOD_META1)

/* Compute twm's global mods_used mask for a complete stored binding set. */
uint32_t wtwm_bindings_used_modifiers(const struct wtwm_binding *bindings,
	size_t count);

/*
 * Match one binding after masking the runtime state with used_modifiers.
 * Callers matching a complete configuration should pass the value returned by
 * wtwm_bindings_used_modifiers().
 */
bool wtwm_binding_matches(const struct wtwm_binding *binding,
	const struct wtwm_binding_trigger *trigger, uint32_t used_modifiers);

/* Select the effective binding, with later overlapping records taking priority. */
const struct wtwm_binding *wtwm_bindings_select(
	const struct wtwm_binding *bindings, size_t count,
	const struct wtwm_binding_trigger *trigger);

#endif
