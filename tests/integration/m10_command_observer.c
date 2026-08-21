/* SPDX-License-Identifier: MIT */
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum { MAX_RECORD_BYTES = 32768 };

int main(int argc, char **argv) {
	if (argc < 3) {
		fprintf(stderr, "usage: m10-command-observer LOG PHASE [ARGUMENT ...]\n");
		return EXIT_FAILURE;
	}
	static const char digits[] = "0123456789abcdef";
	char record[MAX_RECORD_BYTES];
	size_t used = 0;
	int length = snprintf(record, sizeof(record), "%d", argc);
	if (length < 0 || (size_t)length >= sizeof(record)) return EXIT_FAILURE;
	used = (size_t)length;
	for (int index = 0; index < argc; ++index) {
		if (used >= sizeof(record) - 2) return EXIT_FAILURE;
		record[used++] = '\t';
		for (const unsigned char *byte = (const unsigned char *)argv[index];
				*byte != '\0'; ++byte) {
			if (used >= sizeof(record) - 3) return EXIT_FAILURE;
			record[used++] = digits[*byte >> 4];
			record[used++] = digits[*byte & 15];
		}
	}
	record[used++] = '\n';
	int descriptor = open(argv[1], O_WRONLY | O_CREAT | O_APPEND, 0600);
	if (descriptor < 0) return EXIT_FAILURE;
	ssize_t written = write(descriptor, record, used);
	if (close(descriptor) != 0 || written != (ssize_t)used) return EXIT_FAILURE;
	return EXIT_SUCCESS;
}
