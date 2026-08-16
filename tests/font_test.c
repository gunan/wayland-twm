/* SPDX-License-Identifier: MIT */
#include <wtwm/font.h>

#include <assert.h>
#include <string.h>

int main(void) {
	assert(wtwm_x11_bitmap_font_height("fixed") == 13);
	assert(wtwm_x11_bitmap_font_height("9x15") == 15);
	assert(wtwm_x11_bitmap_font_height("10x20") == 20);
	assert(wtwm_x11_bitmap_font_height("variable") == 0);
	assert(wtwm_x11_bitmap_font_height("9x") == 0);
	assert(wtwm_x11_bitmap_font_height(NULL) == 0);
	assert(strcmp(wtwm_pango_font_description("fixed"), "Monospace 8") == 0);
	assert(strcmp(wtwm_pango_font_description("9x15"), "Monospace 9") == 0);
	assert(strcmp(wtwm_pango_font_description("variable"), "variable") == 0);
	assert(strcmp(wtwm_pango_font_description("-misc-fixed"), "Sans Bold 10") == 0);
	return 0;
}
