/* SPDX-License-Identifier: MIT */
#ifndef WTWM_XBM_H
#define WTWM_XBM_H

#include <stdbool.h>
#include <stddef.h>

/*
 * XBM is intended for small monochrome UI assets.  These limits bound both
 * parser input and allocation even when a file contains hostile dimensions.
 */
#define WTWM_XBM_MAX_DIMENSION 32768u
#define WTWM_XBM_MAX_DATA_BYTES (16u * 1024u * 1024u)
#define WTWM_XBM_MAX_FILE_BYTES (32u * 1024u * 1024u)

struct wtwm_xbm {
	char *name;
	unsigned width;
	unsigned height;
	int x_hot;
	int y_hot;
	size_t stride;
	size_t data_size;
	unsigned char *data;
};

void wtwm_xbm_init(struct wtwm_xbm *xbm);
void wtwm_xbm_finish(struct wtwm_xbm *xbm);

/*
 * Load an XBM file into byte-packed, LSB-first rows owned by xbm.  Hotspots
 * are -1 when the corresponding definition is absent.  The accepted legacy
 * declarations are exactly "static char", "static unsigned char", and
 * "static short"; short data is converted from X10 16-bit scanline units.
 *
 * xbm must have been initialized.  A failed load leaves its old value intact.
 * Diagnostics include filename and, for syntax errors, line and column.
 */
bool wtwm_xbm_load(struct wtwm_xbm *xbm, const char *filename,
	char *error, size_t error_size);

#endif
