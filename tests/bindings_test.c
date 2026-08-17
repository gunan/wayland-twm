/* SPDX-License-Identifier: MIT */
#include "wtwm/bindings.h"

#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static struct wtwm_binding button_binding(unsigned button, uint32_t modifiers,
		uint32_t contexts, enum wtwm_action_type action) {
	struct wtwm_binding binding = {
		.type = WTWM_BINDING_BUTTON,
		.button = button,
		.modifiers = modifiers,
		.contexts = contexts,
	};
	binding.action.type = action;
	return binding;
}

static struct wtwm_binding key_binding(const char *key, uint32_t modifiers,
		uint32_t contexts, const char *window_name,
		enum wtwm_action_type action) {
	struct wtwm_binding binding = {
		.type = WTWM_BINDING_KEY,
		.modifiers = modifiers,
		.contexts = contexts,
	};
	assert(strlen(key) < sizeof(binding.key));
	strcpy(binding.key, key);
	if (window_name != NULL) {
		assert(strlen(window_name) < sizeof(binding.window_name));
		strcpy(binding.window_name, window_name);
	}
	binding.action.type = action;
	return binding;
}

static void matches_every_context_and_all_context(void) {
	static const uint32_t contexts[] = {
		WTWM_CONTEXT_ROOT,
		WTWM_CONTEXT_WINDOW,
		WTWM_CONTEXT_TITLE,
		WTWM_CONTEXT_FRAME,
		WTWM_CONTEXT_ICON,
		WTWM_CONTEXT_ICONMGR,
	};
	for (size_t i = 0; i < sizeof(contexts) / sizeof(contexts[0]); ++i) {
		struct wtwm_binding exact = button_binding(1, 0, contexts[i],
			WTWM_ACTION_RAISE);
		struct wtwm_binding all = button_binding(2, 0, WTWM_CONTEXT_ALL,
			WTWM_ACTION_LOWER);
		for (size_t j = 0; j < sizeof(contexts) / sizeof(contexts[0]); ++j) {
			struct wtwm_binding_trigger trigger = {
				.type = WTWM_BINDING_BUTTON,
				.button = 1,
				.context = contexts[j],
			};
			assert(wtwm_binding_matches(&exact, &trigger,
				WTWM_BINDING_BASE_MODIFIERS) == (i == j));
			trigger.button = 2;
			assert(wtwm_binding_matches(&all, &trigger,
				WTWM_BINDING_BASE_MODIFIERS));
		}
	}
}

static void matches_every_modifier_bit_exactly(void) {
	static const uint32_t modifiers[] = {
		WTWM_MOD_SHIFT,
		WTWM_MOD_LOCK,
		WTWM_MOD_CONTROL,
		WTWM_MOD_META1,
		WTWM_MOD_META2,
		WTWM_MOD_META3,
		WTWM_MOD_META4,
		WTWM_MOD_META5,
	};
	struct wtwm_binding all_bindings[
		sizeof(modifiers) / sizeof(modifiers[0])];
	uint32_t all_modifiers = 0;
	for (size_t i = 0; i < sizeof(modifiers) / sizeof(modifiers[0]); ++i) {
		struct wtwm_binding binding = button_binding(3, modifiers[i],
			WTWM_CONTEXT_ROOT, WTWM_ACTION_NOP);
		all_bindings[i] = binding;
		all_modifiers |= modifiers[i];
		struct wtwm_binding_trigger trigger = {
			.type = WTWM_BINDING_BUTTON,
			.button = 3,
			.modifiers = modifiers[i],
			.context = WTWM_CONTEXT_ROOT,
		};
		assert(wtwm_binding_matches(&binding, &trigger, modifiers[i]));
		trigger.modifiers = 0;
		assert(!wtwm_binding_matches(&binding, &trigger, modifiers[i]));
		trigger.modifiers = modifiers[i] |
			modifiers[(i + 1) % (sizeof(modifiers) / sizeof(modifiers[0]))];
		uint32_t extra =
			modifiers[(i + 1) % (sizeof(modifiers) / sizeof(modifiers[0]))];
		bool extra_is_used =
			((WTWM_BINDING_BASE_MODIFIERS | modifiers[i]) & extra) != 0;
		assert(wtwm_binding_matches(&binding, &trigger, modifiers[i]) ==
			!extra_is_used);
	}
	assert(wtwm_bindings_used_modifiers(all_bindings,
		sizeof(all_bindings) / sizeof(all_bindings[0])) == all_modifiers);

	struct wtwm_binding combination = button_binding(4,
		WTWM_MOD_SHIFT | WTWM_MOD_CONTROL | WTWM_MOD_META4,
		WTWM_CONTEXT_ROOT, WTWM_ACTION_NOP);
	struct wtwm_binding_trigger trigger = {
		.type = WTWM_BINDING_BUTTON,
		.button = 4,
		.modifiers = combination.modifiers,
		.context = WTWM_CONTEXT_ROOT,
	};
	assert(wtwm_binding_matches(&combination, &trigger,
		combination.modifiers));
	trigger.modifiers &= ~WTWM_MOD_CONTROL;
	assert(!wtwm_binding_matches(&combination, &trigger,
		combination.modifiers));
}

static void lock_is_a_global_used_modifier(void) {
	struct wtwm_binding no_lock[] = {
		button_binding(1, 0, WTWM_CONTEXT_ROOT, WTWM_ACTION_RAISE),
		button_binding(2, WTWM_MOD_META4, WTWM_CONTEXT_ROOT, WTWM_ACTION_LOWER),
	};
	struct wtwm_binding_trigger trigger = {
		.type = WTWM_BINDING_BUTTON,
		.button = 1,
		.modifiers = WTWM_MOD_LOCK,
		.context = WTWM_CONTEXT_ROOT,
	};
	assert((wtwm_bindings_used_modifiers(no_lock, 2) & WTWM_MOD_LOCK) == 0);
	assert(wtwm_bindings_select(no_lock, 2, &trigger) == &no_lock[0]);

	struct wtwm_binding with_lock[] = {
		no_lock[0],
		button_binding(2, WTWM_MOD_LOCK, WTWM_CONTEXT_ROOT, WTWM_ACTION_LOWER),
	};
	assert(wtwm_bindings_used_modifiers(with_lock, 2) & WTWM_MOD_LOCK);
	assert(wtwm_bindings_select(with_lock, 2, &trigger) == NULL);
	trigger.button = 2;
	assert(wtwm_bindings_select(with_lock, 2, &trigger) == &with_lock[1]);
	trigger.modifiers = 0;
	assert(wtwm_bindings_select(with_lock, 2, &trigger) == NULL);
}

static void key_names_are_exact_and_case_sensitive(void) {
	struct wtwm_binding bindings[] = {
		key_binding("F1", 0, WTWM_CONTEXT_ROOT, NULL, WTWM_ACTION_RAISE),
		key_binding("f1", 0, WTWM_CONTEXT_ROOT, NULL, WTWM_ACTION_LOWER),
		key_binding("a", WTWM_MOD_SHIFT, WTWM_CONTEXT_ROOT, NULL,
			WTWM_ACTION_BEEP),
	};
	struct wtwm_binding_trigger trigger = {
		.type = WTWM_BINDING_KEY,
		.key = "F1",
		.context = WTWM_CONTEXT_ROOT,
	};
	assert(wtwm_bindings_select(bindings, 3, &trigger) == &bindings[0]);
	trigger.key = "f1";
	assert(wtwm_bindings_select(bindings, 3, &trigger) == &bindings[1]);
	trigger.key = "f1 ";
	assert(wtwm_bindings_select(bindings, 3, &trigger) == NULL);
	trigger.key = "A";
	trigger.modifiers = WTWM_MOD_SHIFT;
	assert(wtwm_bindings_select(bindings, 3, &trigger) == NULL);
	trigger.key = "a";
	assert(wtwm_bindings_select(bindings, 3, &trigger) == &bindings[2]);
}

static void named_keys_use_case_sensitive_prefixes(void) {
	struct wtwm_binding x11_binding = key_binding("F6", WTWM_MOD_META1,
		WTWM_CONTEXT_WINDOW, "Term", WTWM_ACTION_RAISE);
	struct wtwm_client_identity x11 = {
		.name = "Terminal one",
		.resource_name = "terminal",
		.resource_class = "XTerm",
	};
	struct wtwm_binding_trigger trigger = {
		.type = WTWM_BINDING_KEY,
		.key = "F6",
		.modifiers = WTWM_MOD_META1,
		.context = WTWM_CONTEXT_ROOT,
		.client = &x11,
	};
	assert(wtwm_binding_matches(&x11_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));
	x11.name = "terminal one";
	assert(!wtwm_binding_matches(&x11_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));
	x11.resource_name = "TermClient";
	assert(wtwm_binding_matches(&x11_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));
	x11.resource_name = "other";
	x11.resource_class = "TermClass";
	assert(wtwm_binding_matches(&x11_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));
	trigger.client = NULL;
	assert(!wtwm_binding_matches(&x11_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));

	struct wtwm_binding native_binding = key_binding("F7", 0,
		WTWM_CONTEXT_WINDOW, "org.example", WTWM_ACTION_LOWER);
	struct wtwm_client_identity native = {
		.title = "Example",
		.app_id = "org.example.Editor",
	};
	trigger.key = "F7";
	trigger.modifiers = 0;
	trigger.context = WTWM_CONTEXT_TITLE;
	trigger.client = &native;
	assert(wtwm_binding_matches(&native_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));
	native.app_id = "Org.Example.Editor";
	assert(!wtwm_binding_matches(&native_binding, &trigger,
		WTWM_BINDING_BASE_MODIFIERS));
}

static void later_overlaps_win_deterministically(void) {
	struct wtwm_binding bindings[] = {
		button_binding(1, 0, WTWM_CONTEXT_ALL, WTWM_ACTION_RAISE),
		button_binding(1, 0, WTWM_CONTEXT_ROOT, WTWM_ACTION_LOWER),
		button_binding(1, WTWM_MOD_SHIFT, WTWM_CONTEXT_ROOT, WTWM_ACTION_BEEP),
	};
	struct wtwm_binding_trigger trigger = {
		.type = WTWM_BINDING_BUTTON,
		.button = 1,
		.context = WTWM_CONTEXT_ROOT,
	};
	assert(wtwm_bindings_select(bindings, 3, &trigger) == &bindings[1]);
	trigger.context = WTWM_CONTEXT_TITLE;
	assert(wtwm_bindings_select(bindings, 3, &trigger) == &bindings[0]);
	trigger.context = WTWM_CONTEXT_ROOT;
	trigger.modifiers = WTWM_MOD_SHIFT;
	assert(wtwm_bindings_select(bindings, 3, &trigger) == &bindings[2]);

	struct wtwm_client_identity alpha = {.title = "Alpha editor", .app_id = "a"};
	struct wtwm_binding named[] = {
		key_binding("F8", 0, WTWM_CONTEXT_WINDOW, "Alpha", WTWM_ACTION_RAISE),
		key_binding("F8", 0, WTWM_CONTEXT_WINDOW, "Beta", WTWM_ACTION_LOWER),
	};
	trigger = (struct wtwm_binding_trigger){
		.type = WTWM_BINDING_KEY,
		.key = "F8",
		.context = WTWM_CONTEXT_WINDOW,
		.client = &alpha,
	};
	/* The later C_NAME slot replaces the earlier selector even on a miss. */
	assert(wtwm_bindings_select(named, 2, &trigger) == NULL);
	alpha.title = "Beta editor";
	assert(wtwm_bindings_select(named, 2, &trigger) == &named[1]);
}

static void misses_and_repeated_triggers_are_stateless(void) {
	struct wtwm_binding binding = button_binding(5, WTWM_MOD_CONTROL,
		WTWM_CONTEXT_FRAME, WTWM_ACTION_RAISE);
	struct wtwm_binding_trigger trigger = {
		.type = WTWM_BINDING_BUTTON,
		.button = 5,
		.modifiers = WTWM_MOD_CONTROL,
		.context = WTWM_CONTEXT_FRAME,
	};
	for (unsigned i = 0; i < 32; ++i)
		assert(wtwm_bindings_select(&binding, 1, &trigger) == &binding);
	trigger.button = 4;
	assert(wtwm_bindings_select(&binding, 1, &trigger) == NULL);
	trigger.button = 5;
	trigger.type = WTWM_BINDING_KEY;
	trigger.key = "5";
	assert(wtwm_bindings_select(&binding, 1, &trigger) == NULL);
	trigger.type = WTWM_BINDING_BUTTON;
	trigger.context = 0;
	assert(wtwm_bindings_select(&binding, 1, &trigger) == NULL);
	trigger.context = WTWM_CONTEXT_ROOT | WTWM_CONTEXT_FRAME;
	assert(wtwm_bindings_select(&binding, 1, &trigger) == NULL);
	assert(wtwm_bindings_select(NULL, 0, &trigger) == NULL);
	assert(wtwm_bindings_select(&binding, 1, NULL) == NULL);
}

int main(void) {
	matches_every_context_and_all_context();
	matches_every_modifier_bit_exactly();
	lock_is_a_global_used_modifier();
	key_names_are_exact_and_case_sensitive();
	named_keys_use_case_sensitive_prefixes();
	later_overlaps_win_deterministically();
	misses_and_repeated_triggers_are_stateless();
	puts("binding matching tests passed");
	return 0;
}
