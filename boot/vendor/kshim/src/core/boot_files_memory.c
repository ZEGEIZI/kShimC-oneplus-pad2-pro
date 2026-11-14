/* SPDX-License-Identifier: GPL-3.0-only */
#include <boot_files_memory.h>
#include <ext4_boot.h>
#include <string.h>
int kshim_boot_memory_reserve(struct kshim_boot_memory *m, uint64_t base, uint64_t size)
{
    if (!size) return 0;
    if (base > UINT64_MAX-size || m->reserved_count == KSHIM_BOOT_RANGES)
        return KSHIM_STORAGE_RANGE;
    m->reserved[m->reserved_count++] = (struct dt_range){base,size};
    return 0;
}
int kshim_boot_memory_init(struct kshim_boot_memory *m, const void *fdt)
{
    bool no_map[KSHIM_BOOT_RANGES];
    memset(m,0,sizeof(*m));
    int rc = dt_reservations(fdt,m->reserved,no_map,KSHIM_BOOT_RANGES,&m->reserved_count);
    if (rc) return rc;
    int node;
    fdt_for_each_subnode(node,fdt,0) {
        const char *type = dt_string(fdt,node,"device_type");
        if (!type || strcmp(type,"memory") || !dt_available(fdt,node)) continue;
        int len; const fdt32_t *reg = fdt_getprop(fdt,node,"reg",&len);
        int ac = fdt_address_cells(fdt,0), sc = fdt_size_cells(fdt,0);
        if (!reg || ac < 1 || ac > 2 || sc < 1 || sc > 2 || len <= 0 || len % (4*(ac+sc)))
            return KSHIM_STORAGE_FORMAT;
        unsigned count = len/(4*(ac+sc));
        for (unsigned i = 0; i < count; ++i) {
            if (m->ram_count == 64) return KSHIM_STORAGE_OVERFLOW;
            struct dt_range *r = &m->ram[m->ram_count];
            if (dt_reg(fdt,node,i,r) || !r->size || r->base > UINT64_MAX-r->size)
                return KSHIM_STORAGE_RANGE;
            ++m->ram_count;
        }
    }
    return m->ram_count ? 0 : KSHIM_STORAGE_MEMORY;
}
int kshim_boot_memory_alloc(struct kshim_boot_memory *m, uint64_t bytes,
                             uint64_t align, uint64_t offset, uint64_t *out)
{
    if (!bytes || !align || (align & (align-1)) || offset >= align ||
        bytes > KSHIM_BOOT_TOTAL_MAX) return KSHIM_STORAGE_RANGE;
    /* Reserve complete 64 KiB pages: an initrd copy by any ARM64 granule
     * cannot clobber the next allocation. Kernel placement retains text_offset. */
    if (bytes > UINT64_MAX-65535) return KSHIM_STORAGE_RANGE;
    bytes = (bytes+65535)&~UINT64_C(65535);
    for (size_t i = 0; i < m->ram_count; ++i) {
        uint64_t cursor = m->ram[i].base, limit = cursor+m->ram[i].size;
        for (size_t attempt = 0; attempt <= m->reserved_count; ++attempt) {
            if (cursor > UINT64_MAX-(align-1)) break;
            uint64_t base = (cursor+align-1)&~(align-1);
            if (base > UINT64_MAX-offset) break;
            base += offset;
            if (base >= limit || bytes > limit-base) break;
            uint64_t next = base;
            for (size_t j = 0; j < m->reserved_count; ++j) {
                struct dt_range r = m->reserved[j];
                if (r.base < base+bytes && base < r.base+r.size && next < r.base+r.size)
                    next = r.base+r.size;
            }
            if (next == base) {
                int rc = kshim_boot_memory_reserve(m,base,bytes);
                if (!rc) *out = base;
                return rc;
            }
            cursor = next;
        }
    }
    return KSHIM_STORAGE_MEMORY;
}
int kshim_boot_image_header(const uint8_t h[64], uint64_t file_size,
                             uint64_t *memory_size, uint64_t *text_offset)
{
    uint64_t size = NhU64(h+16), offset = NhU64(h+8), flags = NhU64(h+24);
    if (NhU32(h+56) != 0x644d5241 || file_size < 64 || !size ||
        size > KSHIM_BOOT_TOTAL_MAX || offset >= 0x200000 || (offset & 65535) ||
        (flags&1) || (flags&~UINT64_C(15))) return KSHIM_STORAGE_FORMAT;
    *memory_size = size > file_size ? size : file_size;
    *text_offset = offset;
    return 0;
}
