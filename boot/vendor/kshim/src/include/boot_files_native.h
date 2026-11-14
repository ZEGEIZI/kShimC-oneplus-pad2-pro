/* SPDX-License-Identifier: GPL-3.0-only */
#pragma once
#include <ext4_boot.h>
/* OnePlus-only, read-only session. Every attempted open must be closed,
 * including a failed claim. A nonzero close prohibits ALL payload handoff. */
int kshim_boot_storage_open(const void *runtime_fdt, struct kshim_ext4 **);
int kshim_boot_storage_close(void);
const char *kshim_boot_storage_stage(void);
const char *kshim_boot_storage_detail(void);
/* Returns to the original Android/memory menu on safe cancellation/failure.
 * A successful Linux boot never returns. */
int kshim_boot_external(uint64_t runtime_fdt, uint64_t packed_base,
                         uint64_t packed_size, void *dtb_source, size_t capacity);
