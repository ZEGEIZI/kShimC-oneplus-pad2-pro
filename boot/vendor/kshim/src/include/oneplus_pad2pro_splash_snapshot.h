/* SPDX-License-Identifier: MIT */
#pragma once
#include <Library/cr_splash.h>
#define PAD2PRO_SPLASH_WORDS 63
struct pad2pro_splash_snapshot {
    uint32_t words[PAD2PRO_SPLASH_WORDS];
    bool captured, stable;
    int status;
};
/* Opt-in diagnostic only: exact captured Sun resource layout, reads only.
 * Words 0..2: CTL0 INTF/PIPE_ACTIVE/LM_ACTIVE.
 * Words 3..18: LM0..3, four words each: OP/OUT/(count | stage<<16)/selector.
 * Words 19..62: VIG0..3, eleven words each: SRC/XY/OUT/OUT_XY/ADDR/STRIDE/
 * FORMAT/UNPACK/OP/SECURE/RECT. Inactive LM/pipe records stay zero.
 */
int pad2pro_splash_snapshot_capture(const struct CrSplashResources *, const struct CrIo *);
const struct pad2pro_splash_snapshot *pad2pro_splash_snapshot_get(void);
int pad2pro_splash_snapshot_report(unsigned slot, char *out, size_t capacity);
/* Pure, bounded decoder for the measured four-LM source-split linear layout.
 * Failure zeroes the output and never accepts a partial or unstable capture. */
int pad2pro_splash_decode(const struct CrSplashResources *,
                         const struct pad2pro_splash_snapshot *, struct CrSplash *);
