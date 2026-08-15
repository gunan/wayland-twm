/* SPDX-License-Identifier: MIT */
#include "wtwm/config.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static const char baseline[] =
	"BorderWidth 7\n"
	"Menu \"baseline\" { \"Noop\" f.nop }\n";

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
	if (size > 1024 * 1024) return 0;
	char *text = malloc(size + 1);
	if (text == NULL) return 0;
	memcpy(text, data, size);
	text[size] = '\0';

	char error[512];
	struct wtwm_config replacement;
	wtwm_config_init(&replacement);
	if (!wtwm_config_parse(&replacement, "baseline", baseline,
		error, sizeof(error))) abort();
	if (!wtwm_config_parse(&replacement, "fuzz-reload", text,
		error, sizeof(error)) &&
		(replacement.border_width != 7 || replacement.menu_count != 1)) abort();
	wtwm_config_finish(&replacement);

	struct wtwm_config fresh;
	wtwm_config_init(&fresh);
	(void)wtwm_config_parse(&fresh, "fuzz-fresh", text, error, sizeof(error));
	wtwm_config_finish(&fresh);
	free(text);
	return 0;
}
