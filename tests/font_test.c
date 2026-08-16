/* SPDX-License-Identifier: MIT */
#include <wtwm/font.h>

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

static void expect_description(const char *font, const char *expected) {
	char description[WTWM_PANGO_FONT_DESCRIPTION_MAX];
	size_t required = wtwm_pango_font_description(font, description,
		sizeof(description));
	assert(required == strlen(expected));
	assert(strcmp(description, expected) == 0);
	assert(wtwm_pango_font_description(font, NULL, 0) == required);
}

static void test_bitmap_heights(void) {
	assert(wtwm_x11_bitmap_font_height("fixed") == 13);
	assert(wtwm_x11_bitmap_font_height("FIXED") == 13);
	assert(wtwm_x11_bitmap_font_height("9x15") == 15);
	assert(wtwm_x11_bitmap_font_height("10x20") == 20);
	assert(wtwm_x11_bitmap_font_height("2147483647x2147483647") == INT_MAX);
	assert(wtwm_x11_bitmap_font_height(
		"-misc-fixed-medium-r-normal--13-120-75-75-c-60-iso10646-1") == 13);
	assert(wtwm_x11_bitmap_font_height(
		"-adobe-helvetica-bold-r-normal--14-100-100-100-p-82-iso8859-1") == 14);
	assert(wtwm_x11_bitmap_font_height(
		"-*-helvetica-medium-o-normal--0-125-*-*-p-*-iso8859-1") == 0);
	assert(wtwm_x11_bitmap_font_height(
		"-*-fixed-medium-r-normal--*-120-*-*-c-*-iso8859-1") == 0);
	assert(wtwm_x11_bitmap_font_height("variable") == 0);
	assert(wtwm_x11_bitmap_font_height("9x") == 0);
	assert(wtwm_x11_bitmap_font_height("0x10") == 0);
	assert(wtwm_x11_bitmap_font_height("999999999999999999999x10") == 0);
	assert(wtwm_x11_bitmap_font_height("-misc-fixed") == 0);
	assert(wtwm_x11_bitmap_font_height(NULL) == 0);
}

static void test_descriptions(void) {
	expect_description(NULL, "Sans Bold 10");
	expect_description("", "Sans Bold 10");
	expect_description("fixed", "Monospace 13px");
	expect_description("FIXED", "Monospace 13px");
	expect_description("9x15", "Monospace 15px");
	expect_description("10x20", "Monospace 20px");
	expect_description("variable", "variable");
	expect_description("DejaVu Sans 10", "DejaVu Sans 10");
	expect_description("-misc-fixed", "Sans Bold 10");
	expect_description(
		"-adobe-helvetica-bold-r-normal--*-120-*-*-*-*-*-*",
		"Sans Bold 12");
	expect_description(
		"-misc-fixed-medium-r-normal--13-120-75-75-c-60-iso10646-1",
		"Monospace 13px");
	expect_description(
		"-adobe-times-bold-i-normal--17-170-75-75-p-90-iso8859-1",
		"Serif Bold Italic 17px");
	expect_description(
		"-*-helvetica-medium-o-normal--0-125-*-*-p-*-iso8859-1",
		"Sans Oblique 12.5");
	expect_description(
		"-foundry-futura-light-r-normal--*-90-75-75-p-*-iso8859-1",
		"futura Light 9");
	expect_description(
		"-foundry-unmapped-medium-r-normal--16-160-75-75-m-80-iso8859-1",
		"Monospace 16px");
	expect_description("-*-*-*-*-*-*-*-*-*-*-*-*-*-*", "Sans 10");
	expect_description(
		"-foundry-family-heavy-ro-normal--0-0-75-75-p-80-registry-encoding",
		"family Heavy Oblique 10");
	expect_description(
		"-foundry-family-medium-r-normal--12oops-120-75-75-p-80-registry-encoding",
		"Sans Bold 10");
	expect_description(
		"-foundry-family-medium-r-normal--12-120-75-75-p-80-registry-encoding-extra",
		"Sans Bold 10");
}

static void test_output_lifetime_and_bounds(void) {
	char first[WTWM_PANGO_FONT_DESCRIPTION_MAX];
	char second[WTWM_PANGO_FONT_DESCRIPTION_MAX];
	wtwm_pango_font_description("fixed", first, sizeof(first));
	wtwm_pango_font_description("9x15", second, sizeof(second));
	assert(strcmp(first, "Monospace 13px") == 0);
	assert(strcmp(second, "Monospace 15px") == 0);

	char tiny[5];
	assert(wtwm_pango_font_description("fixed", tiny, sizeof(tiny)) ==
		strlen("Monospace 13px"));
	assert(strcmp(tiny, "Mono") == 0);
	char sentinel = 'x';
	assert(wtwm_pango_font_description("fixed", &sentinel, 0) ==
		strlen("Monospace 13px"));
	assert(sentinel == 'x');

	char huge[512];
	int prefix = snprintf(huge, sizeof(huge), "-foundry-");
	assert(prefix > 0);
	memset(huge + prefix, 'a', 256);
	strcpy(huge + prefix + 256,
		"-medium-r-normal--13-120-75-75-p-80-registry-encoding");
	expect_description(huge, "Sans Bold 10");
}

int main(void) {
	test_bitmap_heights();
	test_descriptions();
	test_output_lifetime_and_bounds();
	return 0;
}
