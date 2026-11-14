/* SPDX-License-Identifier: GPL-3.0-only */
#include <ext4_boot.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct pair { char *key, *value; };
static int parse(char *text, struct pair *out, unsigned cap)
{
    unsigned n = 0;
    size_t bytes = strlen(text);
    if (!bytes || bytes > KSHIM_BOOT_CONFIG_MAX) return -1;
    for (size_t i = 0; i < bytes; ++i)
        if (((unsigned char)text[i] < 32 && text[i] != '\n') || text[i] == 127) return -1;
    while (*text) {
        char *end = strchr(text, '\n');
        if (end) *end = 0;
        if (*text && *text != '#') {
            char *eq = strchr(text, '=');
            if (!eq || eq == text || !eq[1] || n == cap) return -1;
            *eq = 0;
            for (char *p = text; *p; ++p)
                if (!((*p >= 'a' && *p <= 'z') || *p == '_' || (*p >= '0' && *p <= '9'))) return -1;
            for (unsigned i = 0; i < n; ++i) if (!strcmp(out[i].key, text)) return -1;
            out[n++] = (struct pair){text, eq+1};
        }
        if (!end) break;
        text = end+1;
    }
    return (int)n;
}
static const char *get(struct pair *p, unsigned n, const char *key)
{
    for (unsigned i = 0; i < n; ++i) if (!strcmp(p[i].key, key)) return p[i].value;
    return NULL;
}
static int copy(char *out, size_t cap, const char *s)
{
    if (!s || !*s || strlen(s) >= cap) return -1;
    strcpy(out, s); return 0;
}
static int id(const char *s)
{
    if (!s || !*s || strlen(s) >= KSHIM_BOOT_ID_MAX || s[0] == '.') return 0;
    for (; *s; ++s) if (!((*s >= 'a' && *s <= 'z') || (*s >= 'A' && *s <= 'Z') ||
        (*s >= '0' && *s <= '9') || *s == '-' || *s == '_' || *s == '.')) return 0;
    return 1;
}
static int number(const char *s, uint64_t max, uint64_t *out)
{
    uint64_t n = 0;
    if (!s || !*s) return -1;
    for (; *s; ++s) {
        if (*s < '0' || *s > '9' || n > max/10 ||
            (n == max/10 && (unsigned)(*s-'0') > max%10)) return -1;
        n = n*10 + (unsigned)(*s-'0');
    }
    *out = n; return 0;
}
static int hex(char c)
{
    if (c >= '0' && c <= '9') return c-'0';
    if (c >= 'a' && c <= 'f') return c-'a'+10;
    return -1;
}
static int digest(const char *s, uint8_t out[32])
{
    if (!s || strlen(s) != 64) return -1;
    for (unsigned i = 0; i < 32; ++i) {
        int a = hex(s[2*i]), b = hex(s[2*i+1]);
        if (a < 0 || b < 0) return -1;
        out[i] = a*16+b;
    }
    return 0;
}
int kshim_boot_uuid(const char *s, uint8_t out[16])
{
    if (!s || strlen(s) != 36) return KSHIM_STORAGE_FORMAT;
    unsigned j = 0;
    for (unsigned i = 0; i < 36;) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (s[i++] != '-') return KSHIM_STORAGE_FORMAT;
        } else {
            int a = hex(s[i++]), b = hex(s[i++]);
            if (a < 0 || b < 0) return KSHIM_STORAGE_FORMAT;
            out[j++] = a*16+b;
        }
    }
    return 0;
}
int kshim_boot_parse_global(char *text, struct kshim_boot_catalog *out)
{
    struct pair p[4]; int n = parse(text, p, 4); uint64_t timeout;
    if (n != 4 || !get(p,n,"format") || strcmp(get(p,n,"format"),"1") ||
        number(get(p,n,"timeout_ms"),600000,&timeout) ||
        copy(out->default_entry,sizeof(out->default_entry),get(p,n,"default")))
        return KSHIM_STORAGE_FORMAT;
    out->timeout_ms = timeout; out->count = out->system_count = 0;
    char *systems = (char *)get(p,n,"systems");
    if (!systems) return KSHIM_STORAGE_FORMAT;
    for (;;) {
        char *end = strchr(systems, ','); if (end) *end = 0;
        if (!id(systems) || out->system_count == KSHIM_BOOT_SYSTEMS_MAX) return KSHIM_STORAGE_FORMAT;
        for (unsigned i = 0; i < out->system_count; ++i)
            if (!strcmp(out->systems[i],systems)) return KSHIM_STORAGE_CONFLICT;
        strcpy(out->systems[out->system_count++],systems);
        if (!end) break;
        systems = end+1;
    }
    if (strcmp(out->default_entry,"android")) {
        char *slash = strchr(out->default_entry,'/');
        if (!slash || !id(slash+1) || !strcmp(slash+1,"none")) return KSHIM_STORAGE_FORMAT;
        int found = 0;
        for (unsigned i = 0; i < out->system_count; ++i)
            if (strlen(out->systems[i]) == (size_t)(slash-out->default_entry) &&
                !memcmp(out->systems[i],out->default_entry,slash-out->default_entry)) found = 1;
        if (!found) return KSHIM_STORAGE_FORMAT;
    }
    return 0;
}
struct kshim_boot_versions {
    const char *current, *previous, *ids;
    unsigned count;
};

static int parse_versions(char *text, struct kshim_boot_versions *out)
{
    struct pair p[4]; int n = parse(text,p,4);
    if (n < 0) return KSHIM_STORAGE_FORMAT;
    const char *format = get(p,n,"format");
    const char *a = get(p,n,"current"), *b = get(p,n,"previous");
    if (!format || !id(a) || !id(b) || !strcmp(a,"none") || !strcmp(a,b))
        return KSHIM_STORAGE_FORMAT;
    *out = (struct kshim_boot_versions){.current = a, .previous = b};
    if (!strcmp(format,"1")) {
        if (n != 3) return KSHIM_STORAGE_FORMAT;
        out->count = strcmp(b,"none") ? 2 : 1;
        return 0;
    }
    char *list = (char *)get(p,n,"versions");
    if (strcmp(format,"2") || n != 4 || !list) return KSHIM_STORAGE_FORMAT;
    out->ids = list;
    int found_current = 0, found_previous = !strcmp(b,"none");
    for (;;) {
        char *end = strchr(list,','); if (end) *end = 0;
        if (!id(list) || !strcmp(list,"none")) return KSHIM_STORAGE_FORMAT;
        for (const char *earlier = out->ids; earlier < list; earlier += strlen(earlier)+1)
            if (!strcmp(earlier,list)) return KSHIM_STORAGE_CONFLICT;
        ++out->count;
        if (!strcmp(list,a)) found_current = 1;
        if (!strcmp(list,b)) found_previous = 1;
        if (!end) break;
        list = end+1;
    }
    return found_current && found_previous ? 0 : KSHIM_STORAGE_FORMAT;
}
static int file_fields(struct pair *p, unsigned n, const char *key, struct kshim_boot_file *f)
{
    char field[32]; const char *path = get(p,n,key);
    if (copy(f->path,sizeof(f->path),path) || NhPathCheck(path,0) != NH_OK) return -1;
    snprintf(field,sizeof(field),"%s_size",key);
    if (number(get(p,n,field),KSHIM_BOOT_FILE_MAX,&f->size) || !f->size) return -1;
    snprintf(field,sizeof(field),"%s_sha256",key);
    return digest(get(p,n,field),f->sha256);
}
int kshim_boot_parse_manifest(char *text, struct kshim_boot_entry *out)
{
    struct pair p[18]; int n = parse(text,p,18);
    memset(out,0,sizeof(*out));
    if (n < 0 || !get(p,n,"format") || strcmp(get(p,n,"format"),"1") ||
        copy(out->system,sizeof(out->system),get(p,n,"system_id")) || !id(out->system) ||
        copy(out->version,sizeof(out->version),get(p,n,"boot_id")) || !id(out->version) ||
        copy(out->title,sizeof(out->title),get(p,n,"title")) ||
        copy(out->release,sizeof(out->release),get(p,n,"kernel_release")) ||
        copy(out->device,sizeof(out->device),get(p,n,"device")) ||
        strcmp(out->device,"oneplus,opd2413") ||
        copy(out->cmdline,sizeof(out->cmdline),get(p,n,"cmdline")) ||
        file_fields(p,n,"image",&out->image) || file_fields(p,n,"dtb",&out->dtb) ||
        !get(p,n,"initrd")) return KSHIM_STORAGE_FORMAT;
    int external = strcmp(get(p,n,"initrd"),"none") != 0;
    if (n != (external ? 16 : 14) || (external && file_fields(p,n,"initrd",&out->initrd)))
        return KSHIM_STORAGE_FORMAT;
    if (out->dtb.size > KSHIM_BOOT_DTB_MAX || out->image.size < 64 ||
        out->image.size + out->dtb.size + out->initrd.size > KSHIM_BOOT_TOTAL_MAX)
        return KSHIM_STORAGE_OVERFLOW;
    return 0;
}
int kshim_boot_open_entry(struct kshim_ext4 *fs, const char *system,
                          const char *version, struct kshim_boot_entry *entry)
{
    char text[KSHIM_BOOT_CONFIG_MAX+1], path[KSHIM_BOOT_PATH_MAX];
    snprintf(path,sizeof(path),"kshim/systems/%s/versions/%s/manifest.conf",system,version);
    int rc = kshim_ext4_text(fs,path,text,sizeof(text));
    if (!rc) rc = kshim_boot_parse_manifest(text,entry);
    if (!rc && (strcmp(entry->system,system) || strcmp(entry->version,version)))
        rc = KSHIM_STORAGE_CONFLICT;
    return rc;
}

void kshim_boot_catalog_free(struct kshim_boot_catalog *catalog)
{
    free(catalog->entries);
    catalog->entries = NULL;
    catalog->count = 0;
}

int kshim_boot_discover(struct kshim_ext4 *fs, struct kshim_boot_catalog *out)
{
    char text[KSHIM_BOOT_CONFIG_MAX+1], path[KSHIM_BOOT_PATH_MAX];
    int rc = kshim_ext4_text(fs,"kshim/boot.conf",text,sizeof(text));
    if (!rc) rc = kshim_boot_parse_global(text,out);
    if (rc) return rc;
    for (unsigned i = 0; i < out->system_count; ++i) {
        struct kshim_boot_versions versions;
        snprintf(path,sizeof(path),"kshim/systems/%s/entries.conf",out->systems[i]);
        rc = kshim_ext4_text(fs,path,text,sizeof(text));
        if (!rc) rc = parse_versions(text,&versions);
        unsigned count = rc ? 1 : versions.count;
        struct kshim_boot_summary *entries =
            realloc(out->entries,(out->count+count)*sizeof(*entries));
        if (!entries) {
            kshim_boot_catalog_free(out);
            return KSHIM_STORAGE_MEMORY;
        }
        out->entries = entries;
        if (rc) {
            struct kshim_boot_summary *row = &entries[out->count++];
            *row = (struct kshim_boot_summary){.system = i, .current = 1, .error = rc};
            snprintf(row->title,sizeof(row->title),"%.63s metadata error",out->systems[i]);
            continue;
        }

        const char *version = versions.ids ? versions.ids : versions.current;
        for (unsigned j = 0; j < count; ++j) {
            struct kshim_boot_entry entry;
            struct kshim_boot_summary *row = &entries[out->count++];
            rc = kshim_boot_open_entry(fs,out->systems[i],version,&entry);
            *row = (struct kshim_boot_summary){
                .system = i, .error = rc,
                .current = !strcmp(version,versions.current),
                .previous = !strcmp(version,versions.previous),
            };
            strcpy(row->version,version);
            if (rc) {
                snprintf(row->title,sizeof(row->title),"%.63s manifest error",out->systems[i]);
            } else {
                strcpy(row->title,entry.title);
                strcpy(row->release,entry.release);
            }
            version = versions.ids ? version+strlen(version)+1 : versions.previous;
        }
    }
    return 0;
}
int kshim_boot_read_payload(struct kshim_ext4 *fs, const struct kshim_boot_entry *e,
                             const struct kshim_boot_file *f, void *out, size_t cap)
{
    char path[KSHIM_BOOT_PATH_MAX]; uint8_t sha[32]; NH_FILE file;
    int len = snprintf(path,sizeof(path),"kshim/systems/%s/versions/%s/%s",e->system,e->version,f->path);
    if (len < 0 || (size_t)len >= sizeof(path) || f->size > cap) return KSHIM_STORAGE_RANGE;
    int rc = kshim_ext4_open(fs,path,&file);
    if (rc) return rc;
    if (file.Size != f->size) return KSHIM_STORAGE_FORMAT;
    rc = kshim_ext4_read(&file,0,out,file.Size);
    if (rc) return rc;
    NhSha256(out,file.Size,sha);
    return memcmp(sha,f->sha256,32) ? KSHIM_STORAGE_HASH : 0;
}
