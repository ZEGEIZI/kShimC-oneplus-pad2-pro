/* SPDX-License-Identifier: MIT */
/* Match Python gzip.compress(level=9, mtime=0) with the pinned zlib-ng. */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <zlib.h>

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    FILE *input = fopen(argv[1], "rb");
    if (!input || fseek(input, 0, SEEK_END)) return 3;
    long length = ftell(input);
    if (length < 0 || length > 16 * 1024 * 1024 || fseek(input, 0, SEEK_SET)) return 4;
    unsigned char *raw = malloc(length ? (size_t)length : 1);
    if (!raw || fread(raw, 1, (size_t)length, input) != (size_t)length || fclose(input)) return 5;
    z_stream stream = {0};
    if (deflateInit2(&stream, 9, Z_DEFLATED, 31, 8, Z_DEFAULT_STRATEGY) != Z_OK) return 6;
    uLong capacity = deflateBound(&stream, (uLong)length);
    if (capacity > UINT_MAX) return 7;
    unsigned char *output = malloc(capacity);
    if (!output) return 8;
    stream.next_in = raw; stream.avail_in = (uInt)length;
    stream.next_out = output; stream.avail_out = (uInt)capacity;
    if (deflate(&stream, Z_FINISH) != Z_STREAM_END) return 9;
    size_t bytes = stream.total_out;
    if (bytes < 18 || deflateEnd(&stream) != Z_OK) return 10;
    output[9] = 255; /* Portable gzip OS field, independent of Python version. */
    int result = fwrite(output, 1, bytes, stdout) == bytes && !fflush(stdout) ? 0 : 11;
    free(output); free(raw);
    return result;
}
