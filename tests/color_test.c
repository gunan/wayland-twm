/* SPDX-License-Identifier: MIT */
#include <wtwm/color.h>

#include <assert.h>
#include <math.h>
#include <stddef.h>

static void expect(const char *name, uint16_t red, uint16_t green, uint16_t blue) {
	struct wtwm_color color;
	assert(wtwm_color_parse_literal(name, &color));
	assert(color.red == red && color.green == green && color.blue == blue);
}

int main(void) {
	expect("#fff", 65535, 65535, 65535);
	expect("#123456", 0x1212, 0x3434, 0x5656);
	expect("#abc012def", 0xabca, 0x0120, 0xdefd);
	expect("#1234abcdFFFF", 0x1234, 0xabcd, 0xffff);
	expect("rgb:f/80/0000", 65535, 0x8080, 0);
	expect("rgbi:1/.5/0", 65535, 32768, 0);
	expect("gray85", 217 * 257, 217 * 257, 217 * 257);
	expect("GREY0", 0, 0, 0);
	expect("green", 0, 128 * 257, 0);
	struct wtwm_color ignored;
	assert(!wtwm_color_parse_literal(NULL, &ignored));
	assert(!wtwm_color_parse_literal("#12", &ignored));
	assert(!wtwm_color_parse_literal("#ggg", &ignored));
	assert(!wtwm_color_parse_literal("rgb:1/2", &ignored));
	assert(!wtwm_color_parse_literal("rgb:1/2/12345", &ignored));
	assert(!wtwm_color_parse_literal("rgbi:nan/0/0", &ignored));
	assert(!wtwm_color_parse_literal("rgbi:1.1/0/0", &ignored));
	assert(!wtwm_color_parse_literal("gray101", &ignored));
	assert(!wtwm_color_parse_literal("slategrey", &ignored));

	struct wtwm_color first = {100, 300, 500};
	struct wtwm_color last = {0, 900, 200};
	struct wtwm_color middle = wtwm_color_interpolate(first, last, 1, 3);
	assert(middle.red == 67 && middle.green == 500 && middle.blue == 400);
	struct wtwm_color end = wtwm_color_interpolate(first, last, 3, 3);
	assert(end.red == last.red && end.green == last.green && end.blue == last.blue);

	float normalized[4];
	wtwm_color_to_float(&(struct wtwm_color){65535, 32768, 0}, normalized);
	assert(normalized[0] == 1.0f && normalized[2] == 0.0f && normalized[3] == 1.0f);
	assert(fabsf(normalized[1] - 0.5000076f) < 0.000001f);
	return 0;
}
