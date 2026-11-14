/* SPDX-License-Identifier: GPL-3.0-only */
#include <ext4_boot.h>
#include <stdlib.h>
#include <string.h>

static void *allocate(void *ctx, size_t bytes) { (void)ctx; return malloc(bytes); }
static void deallocate(void *ctx, void *p) { (void)ctx; free(p); }
static int result(NH_STATUS s)
{
    switch (s) {
    case NH_OK: return 0;
    case NH_NOT_FOUND: return KSHIM_STORAGE_NOT_FOUND;
    case NH_UNSUPPORTED: return KSHIM_STORAGE_UNSUPPORTED;
    case NH_NOT_READY: return KSHIM_STORAGE_DIRTY;
    case NH_IO: return KSHIM_STORAGE_IO;
    case NH_MEMORY: return KSHIM_STORAGE_MEMORY;
    case NH_TOO_LARGE: return KSHIM_STORAGE_OVERFLOW;
    default: return KSHIM_STORAGE_FORMAT;
    }
}
static NH_STATUS read_bytes(void *ctx, uint64_t offset, void *buffer, size_t bytes)
{
    struct kshim_ext4 *f = ctx;
    uint8_t *dst = buffer;
    uint64_t limit = (f->partition.last_lba - f->partition.first_lba + 1) * f->dev->block_size;
    if (offset > limit || bytes > limit - offset) return NH_CORRUPT;
    while (bytes) {
        uint64_t lba = f->partition.first_lba + offset / f->dev->block_size;
        size_t pos = offset % f->dev->block_size;
        size_t take = f->dev->block_size - pos;
        if (take > bytes) take = bytes;
        if (!f->cached || f->cached_lba != lba) {
            f->cached = 0;
            f->io_error = kshim_block_read(f->dev, lba, 1, f->sector);
            if (f->io_error) return NH_IO;
            f->cached_lba = lba; f->cached = 1;
        }
        memcpy(dst, f->sector + pos, take);
        dst += take; bytes -= take; offset += take;
    }
    return NH_OK;
}
int kshim_ext4_mount(struct kshim_ext4 *f, const struct kshim_blockdev *d,
                      const struct kshim_partition *p)
{
    if (!f || !d || !p || (d->block_size != 512 && d->block_size != 4096) ||
        p->first_lba > p->last_lba || p->last_lba >= d->block_count ||
        p->last_lba - p->first_lba + 1 > UINT64_MAX / d->block_size)
        return KSHIM_STORAGE_ARG;
    memset(f, 0, sizeof(*f)); f->dev = d; f->partition = *p;
    NH_READER reader = {f, read_bytes,
        (p->last_lba - p->first_lba + 1) * d->block_size, allocate, deallocate};
    return result(NhFsOpen(&reader, &f->fs));
}
int kshim_ext4_open(struct kshim_ext4 *fs, const char *path, NH_FILE *file)
{
    int rc = result(NhFileOpen(&fs->fs, path, file));
    if (!rc && (file->Mode & 0170000) != 0100000) return KSHIM_STORAGE_UNSUPPORTED;
    return rc;
}
int kshim_ext4_read(NH_FILE *f, uint64_t at, void *p, size_t n)
{ return result(NhFileRead(f, at, p, n)); }
int kshim_ext4_text(struct kshim_ext4 *fs, const char *path, char *buf, size_t cap)
{
    NH_FILE f;
    int rc = kshim_ext4_open(fs, path, &f);
    if (rc) return rc;
    if (!f.Size || f.Size >= cap || f.Size > KSHIM_BOOT_CONFIG_MAX)
        return KSHIM_STORAGE_OVERFLOW;
    rc = kshim_ext4_read(&f, 0, buf, f.Size);
    if (rc) return rc;
    if (memchr(buf, 0, f.Size)) return KSHIM_STORAGE_FORMAT;
    buf[f.Size] = 0;
    return 0;
}
