/* SPDX-License-Identifier: GPL-3.0-only */
#pragma once
#include <dt.h>
#define KSHIM_BOOT_RANGES 160u
struct kshim_boot_memory {
    struct dt_range ram[64], reserved[KSHIM_BOOT_RANGES];
    size_t ram_count, reserved_count;
};
int kshim_boot_memory_init(struct kshim_boot_memory *, const void *);
int kshim_boot_memory_reserve(struct kshim_boot_memory *, uint64_t, uint64_t);
/* Return aligned-base+offset, reserving the complete (page-rounded) span. */
int kshim_boot_memory_alloc(struct kshim_boot_memory *, uint64_t bytes,
                             uint64_t alignment, uint64_t offset, uint64_t *);
int kshim_boot_image_header(const uint8_t[64], uint64_t file_size,
                             uint64_t *memory_size, uint64_t *text_offset);
