/* SPDX-License-Identifier: GPL-3.0-only */
#pragma once
#include <storage_block.h>
#include <Library/FirmwareLoaderLib/NhFs.h>
#define KSHIM_BOOT_CONFIG_MAX 8192u
#define KSHIM_BOOT_SYSTEMS_MAX 4u
#define KSHIM_BOOT_CMDLINE_MAX 4096u
#define KSHIM_BOOT_PATH_MAX 512u
#define KSHIM_BOOT_ID_MAX 64u
#define KSHIM_BOOT_FILE_MAX (128u * 1024u * 1024u)
#define KSHIM_BOOT_TOTAL_MAX (256u * 1024u * 1024u)
/* Input size and writable handoff capacity are separate budgets. */
#define KSHIM_BOOT_DTB_MAX (1024u * 1024u)
#define KSHIM_BOOT_DTB_OUTPUT_BYTES (1280u * 1024u)
struct kshim_ext4 {
    NH_FS fs;
    const struct kshim_blockdev *dev;
    struct kshim_partition partition;
    uint64_t cached_lba;
    int cached, io_error;
    uint8_t sector[4096];
};
struct kshim_boot_file {
    char path[KSHIM_BOOT_PATH_MAX];
    uint64_t size;
    uint8_t sha256[32];
};
struct kshim_boot_entry {
    char system[KSHIM_BOOT_ID_MAX], version[KSHIM_BOOT_ID_MAX];
    char title[96], release[128], device[64];
    char cmdline[KSHIM_BOOT_CMDLINE_MAX];
    struct kshim_boot_file image, dtb, initrd;
};
struct kshim_boot_summary {
    char version[KSHIM_BOOT_ID_MAX];
    char title[96], release[128];
    unsigned system;
    int error;
    uint8_t current, previous;
};
struct kshim_boot_catalog {
    char systems[KSHIM_BOOT_SYSTEMS_MAX][KSHIM_BOOT_ID_MAX];
    unsigned system_count, count;
    uint32_t timeout_ms;
    char default_entry[144]; /* android or system/current|previous|boot_id */
    struct kshim_boot_summary *entries;
};
int kshim_ext4_mount(struct kshim_ext4 *, const struct kshim_blockdev *,
                      const struct kshim_partition *);
int kshim_ext4_open(struct kshim_ext4 *, const char *, NH_FILE *);
int kshim_ext4_read(NH_FILE *, uint64_t, void *, size_t);
int kshim_ext4_text(struct kshim_ext4 *, const char *, char *, size_t);
/* Parsers reject unknown/duplicate keys, malformed IDs/paths and overflow. */
int kshim_boot_parse_global(char *, struct kshim_boot_catalog *);
int kshim_boot_parse_manifest(char *, struct kshim_boot_entry *);
/* Discover into a zero-initialized catalog. Release it with catalog_free. */
int kshim_boot_discover(struct kshim_ext4 *, struct kshim_boot_catalog *);
void kshim_boot_catalog_free(struct kshim_boot_catalog *);
int kshim_boot_open_entry(struct kshim_ext4 *, const char *, const char *, struct kshim_boot_entry *);
int kshim_boot_read_payload(struct kshim_ext4 *, const struct kshim_boot_entry *,
                             const struct kshim_boot_file *, void *, size_t);
int kshim_boot_uuid(const char *, uint8_t[16]);
