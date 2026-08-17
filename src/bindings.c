/* SPDX-License-Identifier: MIT */
#include "wtwm/bindings.h"

#include <string.h>

#define WTWM_ALL_MODIFIERS \
	(WTWM_MOD_SHIFT | WTWM_MOD_LOCK | WTWM_MOD_CONTROL | WTWM_MOD_META1 | \
	 WTWM_MOD_META2 | WTWM_MOD_META3 | WTWM_MOD_META4 | WTWM_MOD_META5)

static bool concrete_context(uint32_t context) {
	return context != 0 && (context & (context - 1)) == 0 &&
		(context & WTWM_CONTEXT_ALL) != 0;
}

static bool same_trigger(const struct wtwm_binding *binding,
		const struct wtwm_binding_trigger *trigger) {
	if (binding->type != trigger->type) return false;
	if (binding->type == WTWM_BINDING_BUTTON)
		return binding->button == trigger->button;
	return trigger->key != NULL && strcmp(binding->key, trigger->key) == 0;
}

static bool named_binding(const struct wtwm_binding *binding) {
	return binding->type == WTWM_BINDING_KEY && binding->window_name[0] != '\0';
}

static bool named_client_matches(const char *selector,
		const struct wtwm_client_identity *client) {
	if (client == NULL) return false;
	if (client->name != NULL || client->resource_name != NULL ||
		client->resource_class != NULL)
		return wtwm_config_prefix_x11(selector, client->name,
			client->resource_name, client->resource_class);
	return wtwm_config_prefix_native(selector, client->title, client->app_id);
}

uint32_t wtwm_bindings_used_modifiers(const struct wtwm_binding *bindings,
		size_t count) {
	uint32_t used = WTWM_BINDING_BASE_MODIFIERS;
	if (bindings == NULL) return used;
	for (size_t i = 0; i < count; ++i) used |= bindings[i].modifiers;
	return used & WTWM_ALL_MODIFIERS;
}

bool wtwm_binding_matches(const struct wtwm_binding *binding,
		const struct wtwm_binding_trigger *trigger, uint32_t used_modifiers) {
	if (binding == NULL || trigger == NULL ||
		!concrete_context(trigger->context) ||
		(binding->modifiers & ~WTWM_ALL_MODIFIERS) != 0 ||
		!same_trigger(binding, trigger)) return false;

	/*
	 * This is deliberately global rather than per-binding.  In reference twm,
	 * parsing any Lock binding adds LockMask to mods_used, after which Caps Lock
	 * also distinguishes every binding that did not request Lock.
	 */
	used_modifiers = (used_modifiers | WTWM_BINDING_BASE_MODIFIERS) &
		WTWM_ALL_MODIFIERS;
	if (binding->modifiers != (trigger->modifiers & used_modifiers)) return false;

	/* C_NAME is a separate key-binding context in twm, not C_WINDOW. */
	if (named_binding(binding))
		return named_client_matches(binding->window_name, trigger->client);
	return (binding->contexts & trigger->context) != 0;
}

const struct wtwm_binding *wtwm_bindings_select(
		const struct wtwm_binding *bindings, size_t count,
		const struct wtwm_binding_trigger *trigger) {
	if (bindings == NULL || trigger == NULL ||
		!concrete_context(trigger->context)) return NULL;
	uint32_t used_modifiers = wtwm_bindings_used_modifiers(bindings, count);
	bool named_slot_seen = false;

	for (size_t i = count; i > 0; --i) {
		const struct wtwm_binding *binding = &bindings[i - 1];
		bool named = named_binding(binding);
		if (!same_trigger(binding, trigger) ||
			binding->modifiers != (trigger->modifiers & used_modifiers)) continue;
		/*
		 * Reference AddFuncKey identifies a C_NAME slot by keysym and modifiers;
		 * win_name is replacement data, not part of the slot key.  config.c
		 * currently retains different selectors, so suppress the older records
		 * even when the effective later selector finds no client.
		 */
		bool named_match = named && !named_slot_seen &&
			named_client_matches(binding->window_name, trigger->client);
		if (named && !named_slot_seen) named_slot_seen = true;
		if (named_match || (!named &&
			(binding->contexts & trigger->context) != 0))
			return binding;
	}
	return NULL;
}
