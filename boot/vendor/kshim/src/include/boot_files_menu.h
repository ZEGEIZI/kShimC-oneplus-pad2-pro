/* SPDX-License-Identifier: GPL-3.0-only */
#pragma once
#include <ext4_boot.h>
#define KSHIM_BOOT_MENU_ROWS 9u
/* The same chooser is exercised by host tests and the native UI. A successful
 * cancellation sets *entry to SIZE_MAX; a kernel choice is a catalog index.
 * The callback must finish/quiesce each UI session before returning. */
typedef int (*kshim_boot_menu_select_fn)(void *context,
    const char *const *names, const char *const *descriptions, size_t count,
    size_t initial, uint32_t timeout_ms, size_t *selected);
int kshim_boot_choose(const struct kshim_boot_catalog *,
    kshim_boot_menu_select_fn, void *context, size_t *entry);
