/* SPDX-License-Identifier: MIT */
#include "wtwm/config.h"

#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
	if (argc != 2 || strcmp(argv[1], "--help") == 0) {
		fprintf(argc == 2 ? stdout : stderr, "usage: wtwm-config FILE\n");
		return argc == 2 ? 0 : 2;
	}
	struct wtwm_config config;
	wtwm_config_init(&config);
	char error[1024];
	if (!wtwm_config_load(&config, argv[1], error, sizeof(error))) {
		fprintf(stderr, "wtwm-config: %s\n", error[0] ? error : "unable to read configuration");
		wtwm_config_finish(&config);
		return 1;
	}
	wtwm_config_dump(&config, stdout);
	wtwm_config_finish(&config);
	return 0;
}
