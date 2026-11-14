/* SPDX-License-Identifier: MIT */
#include <oneplus_pad2pro_splash_snapshot.h>
#include <stdio.h>
#include <string.h>

static struct pad2pro_splash_snapshot saved = {.status = CR_BUS_INVALID};

static bool captured_resources(const struct CrSplashResources *r)
{
    static const uint32_t pipes[10] = {0x5000,0x7000,0x9000,0xb000,
        0x25000,0x27000,0x29000,0x2b000,0x2d000,0x2f000};
    if (!r || r->base != 0xae00000 || r->size != 0x93800 ||
        r->reserved_base != 0xfc800000 || r->reserved_size != 0x2b00000 ||
        r->pipe_count != 10 || r->ctl_count != 6 || r->mixer_count != 8 ||
        r->stage_count != 11 || !r->lm_source_select || r->sspp_rec_separated)
        return false;
    for (unsigned i = 0; i < 10; ++i)
        if (r->pipe[i] != pipes[i] || r->pipe_id[i] != i) return false;
    for (unsigned i = 0; i < 6; ++i)
        if (r->ctl[i] != 0x16000 + i * 0x1000) return false;
    for (unsigned i = 0; i < 8; ++i)
        if (r->mixer[i] != 0x45000 + i * 0x1000 || r->mixer_id[i] != i) return false;
    for (unsigned i = 0; i < 11; ++i)
        if (r->stage[i] != 0x40 + i * 0x30) return false;
    return true;
}

struct read_log { uint32_t values[103]; unsigned count; bool overflow; };

static uint32_t read_word(const struct CrSplashResources *r, const struct CrIo *io,
                          struct read_log *log, uint32_t off)
{
    /* All callers use the fixed tables above, wholly inside mdp_phys. */
    if (log->count >= 103) { log->overflow = true; return 0; }
    uint32_t value = io->read32(io->context, r->base + off);
    log->values[log->count++] = value;
    return value;
}

static int capture_once(const struct CrSplashResources *r, const struct CrIo *io,
                         uint32_t *w, struct read_log *log)
{
    static const uint32_t fields[11] = {0,8,12,16,20,36,48,52,56,112,0x170};
    memset(w, 0, PAD2PRO_SPLASH_WORDS * sizeof(*w));
    memset(log, 0, sizeof(*log));
    w[0] = read_word(r, io, log, r->ctl[0] + 0xf4);
    w[1] = read_word(r, io, log, r->ctl[0] + 0x12c);
    w[2] = read_word(r, io, log, r->ctl[0] + 0x130);
    /* Do not read inactive or unrecognized pipe banks. This capture schema
     * covers VIG0..3 and LM0..3 only, and refuses other active masks. */
    if (!w[0] || !w[1] || (w[1] & ~0xf0000u) || !w[2] || (w[2] & ~0xfu))
        return CR_BUS_UNSUPPORTED;
    for (unsigned i = 0; i < 4; ++i) {
        if (!(w[2] & (1u << i))) continue;
        unsigned n = 3 + i * 4, count = 0, selected = 0;
        w[n] = read_word(r, io, log, r->mixer[i]);
        w[n + 1] = read_word(r, io, log, r->mixer[i] + 4);
        for (unsigned s = 0; s <= 11; ++s) {
            uint32_t sel = read_word(r, io, log, r->mixer[i] + (s ? r->stage[s - 1] + 4 : 0x14));
            if (sel == 0xc0c0) continue;
            ++count; selected = s; w[n + 3] = sel;
        }
        w[n + 2] = count | (selected << 16);
    }
    for (unsigned i = 0; i < 4; ++i) {
        if (!(w[1] & (1u << (16 + i)))) continue;
        for (unsigned j = 0; j < 11; ++j)
            w[19 + i * 11 + j] = read_word(r, io, log, r->pipe[i] + fields[j]);
    }
    return log->overflow ? CR_BUS_INVALID : 0;
}

int pad2pro_splash_snapshot_capture(const struct CrSplashResources *r, const struct CrIo *io)
{
    uint32_t again[PAD2PRO_SPLASH_WORDS];
    struct read_log first_reads, second_reads;
    memset(&saved, 0, sizeof(saved));
    saved.status = CR_BUS_INVALID;
    if (!captured_resources(r) || !io || !io->read32) return saved.status;
    saved.status = capture_once(r, io, saved.words, &first_reads);
    if (saved.status) return saved.status;
    saved.status = capture_once(r, io, again, &second_reads);
    if (saved.status) return saved.status;
    saved.captured = true;
    saved.stable = !memcmp(saved.words, again, sizeof(again)) &&
        first_reads.count == second_reads.count &&
        !memcmp(first_reads.values, second_reads.values, sizeof(first_reads.values));
    saved.status = saved.stable ? 0 : CR_BUS_AGAIN;
    return saved.status;
}

const struct pad2pro_splash_snapshot *pad2pro_splash_snapshot_get(void) { return &saved; }

int pad2pro_splash_snapshot_report(unsigned slot, char *out, size_t capacity)
{
    if (!saved.captured || slot >= 8 || !out || capacity < 81) return -1;
    int n = snprintf(out, capacity, "p2s1:%u:%u:", slot, saved.stable ? 1u : 0u);
    if (n != 9) return -1;
    for (unsigned i = 0; i < 8; ++i) {
        unsigned index = slot * 8 + i;
        int m = snprintf(out + n, capacity - (size_t)n, "%08x",
                         index < PAD2PRO_SPLASH_WORDS ? saved.words[index] : 0u);
        if (m != 8) return -1;
        n += m;
    }
    return n;
}

int pad2pro_splash_decode(const struct CrSplashResources *r,
                          const struct pad2pro_splash_snapshot *s, struct CrSplash *fb)
{
    if (!fb) return CR_BUS_INVALID;
    memset(fb, 0, sizeof(*fb));
    if (!captured_resources(r) || !s || !s->captured) return CR_BUS_INVALID;
    if (!s->stable || s->status) return CR_BUS_AGAIN;
    const uint32_t *w = s->words;
    /* Measured CTL0 only: all four VIGs feed two source-split LM pairs.
     * No fanout, extra source, background composition or unknown OP bits. */
    if (w[0] != 6 || w[1] != 0xf0000 || w[2] != 0xf) return CR_BUS_UNSUPPORTED;
    uint32_t quarter = w[4] & 0xffff, height = w[4] >> 16;
    if (!quarter || quarter > 2048 || !height || height > 8192) return CR_BUS_INVALID;
    for (unsigned i = 0; i < 4; ++i) {
        unsigned n = 3 + i * 4;
        uint32_t stage = w[n + 2] >> 16;
        if (w[n] != ((i & 1) ? 0x80000000u : 0) || w[n + 1] != w[4] ||
            (w[n + 2] & 0xffff) != 1 || !stage || stage > 11 ||
            w[n + 3] != (i < 2 ? 0x4140u : 0x4342u)) return CR_BUS_UNSUPPORTED;
        if ((i & 1) && w[n + 2] != w[n - 2]) return CR_BUS_UNSUPPORTED;
    }
    const uint32_t *first = w + 19;
    uint32_t width = quarter * 4, address = first[4], stride = first[5];
    if (!address || (address & 3) || (stride & 3) || (stride >> 16) ||
        stride < width * 4) return CR_BUS_INVALID;
    for (unsigned i = 0; i < 4; ++i) {
        const uint32_t *p = w + 19 + i * 11;
        if (p[0] != w[4] || p[2] != p[0] || p[1] != i * quarter ||
            p[3] != (i & 1) * quarter || p[4] != address || p[5] != stride ||
            p[6] != 0x237ff || p[7] != 0x03020001 || p[8] != 0x80000000 ||
            p[9] || p[10]) return CR_BUS_UNSUPPORTED;
    }
    uint64_t size = (uint64_t)stride * height;
    if (address < r->reserved_base || size > r->reserved_size ||
        address - r->reserved_base > r->reserved_size - size) return CR_BUS_INVALID;
    *fb = (struct CrSplash){.address=address,.size=(size_t)size,.width=width,
                           .height=height,.stride=stride,.format=CR_SPLASH_ARGB8888};
    return 0;
}
