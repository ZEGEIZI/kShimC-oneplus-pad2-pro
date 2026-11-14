/* SPDX-License-Identifier: GPL-3.0-only */
#pragma once
#include <stddef.h>
#include <stdint.h>
/* Linux payload identity uses declared board+SoC compatibles. The stock ABL
 * fingerprint remains authoritative only for actual-hardware admission. */
int kshim_boot_validate_dtb(const void *dtb, size_t bytes);
struct kshim_boot_entry;
/* Expands a packed private DT before updating chosen; discard it on error. */
int kshim_boot_chosen(void *dtb, size_t capacity,
                       const struct kshim_boot_entry *, uint64_t initrd_start);
