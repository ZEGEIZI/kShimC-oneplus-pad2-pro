/* SPDX-License-Identifier: GPL-3.0-only */
/* Host-only: exercise the exact runtime parsers through a read-only image. */
#define _POSIX_C_SOURCE 200809L
#include <ext4_boot.h>
#include <boot_files_menu.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
struct image { int fd; uint32_t sector; uint64_t bytes, reads; };
static int read_blocks(void *ctx,uint64_t lba,uint32_t count,void *p)
{
    struct image *image=ctx;
    ++image->reads;
    return pread(image->fd,p,(size_t)count*image->sector,lba*image->sector) == (ssize_t)((size_t)count*image->sector) ? 0 : -1;
}
static void json_string(const char *text)
{
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x",*p);
        else putchar(*p);
    }
    putchar('"');
}
struct choices { const char *next; };
static int choose_menu(void *opaque, const char *const *names,
    const char *const *descriptions, size_t count, size_t initial,
    uint32_t timeout, size_t *selected)
{
    (void)names; (void)descriptions; (void)count; (void)timeout;
    struct choices *choices=opaque;
    const char *next=choices->next;
    if (!next || !*next) return KSHIM_STORAGE_ARG;
    char *end;
    if (!strncmp(next,"default",7)) { *selected=initial; end=(char *)next+7; }
    else {
        if (*next < '0' || *next > '9') return KSHIM_STORAGE_ARG;
        *selected=strtoul(next,&end,10);
    }
    if (*end && *end != ',') return KSHIM_STORAGE_ARG;
    choices->next=*end ? end+1 : end;
    return 0;
}
int main(int argc,char **argv)
{
    const char *script=NULL;
    if (argc >= 4 && !strcmp(argv[argc-2],"--choose")) {
        script=argv[argc-1]; argc-=2;
    }
    if (argc<2 || argc>4) return 2;
    struct image image={.fd=open(argv[1],O_RDONLY),.sector=argc>2 ? (uint32_t)strtoul(argv[2],NULL,10) : 512};
    struct stat st;
    if (image.fd<0 || fstat(image.fd,&st)) return 2;
    image.bytes=st.st_size;
    struct kshim_blockdev block={.ctx=&image,.block_size=image.sector,.block_count=image.bytes/image.sector,.read=read_blocks};
    struct kshim_partition part={0,block.block_count-1,{0}};
    int rc=0;
    if (argc==4) {
        uint8_t uuid[16],scratch[8192];
        rc=kshim_boot_uuid(argv[3],uuid);
        if (!rc) rc=kshim_gpt_find(&block,uuid,NULL,&part,scratch,sizeof(scratch));
    }
    struct kshim_ext4 *fs=calloc(1,sizeof(*fs));
    struct kshim_boot_catalog *catalog=calloc(1,sizeof(*catalog));
    if (!fs || !catalog) return 2;
    if (!rc) rc=kshim_ext4_mount(fs,&block,&part);
    /* A fifth mode is unnecessary: a valid ext4 image without kshim config
     * still reports NOT_FOUND, distinguishing it from a rejected mount. */
    if (!rc) rc=kshim_boot_discover(fs,catalog);
    size_t selected=SIZE_MAX;
    if (!rc && script) {
        struct choices choices={script};
        rc=kshim_boot_choose(catalog,choose_menu,&choices,&selected);
        if (!rc && *choices.next) rc=KSHIM_STORAGE_ARG;
    }
    int *payload_status=calloc(catalog->count ? catalog->count : 1,sizeof(*payload_status));
    if (!payload_status) return 2;
    struct kshim_boot_entry selected_entry={0};
    char observed[3][65]={{0}};
    int discovered=rc == 0;
    for (unsigned i=0; discovered && i<catalog->count; ++i) {
        if (script && i != selected) continue;
        const struct kshim_boot_summary *row=&catalog->entries[i];
        struct kshim_boot_entry entry={0}, *e=&entry;
        int status=row->error;
        if (!status) status=kshim_boot_open_entry(fs,catalog->systems[row->system],row->version,e);
        if (!status && i == selected) selected_entry=entry;
        const struct kshim_boot_file *files[]={&e->image,&e->dtb,&e->initrd};
        for (unsigned j=0; !status && j<3; ++j) {
            if (!files[j]->size) continue;
            void *data=malloc(files[j]->size);
            if (!data) { status=KSHIM_STORAGE_MEMORY; break; }
            status=kshim_boot_read_payload(fs,e,files[j],data,files[j]->size);
            if (!status && script) {
                uint8_t digest[32]; NhSha256(data,files[j]->size,digest);
                for (unsigned k=0; k<32; ++k) snprintf(observed[j]+k*2,3,"%02x",digest[k]);
            }
            free(data);
        }
        payload_status[i]=status;
        if (!rc) rc=status;
    }
    printf("{\"status\":%d,\"entries\":%u,\"block_reads\":%llu,\"catalog\":[",rc,catalog->count,(unsigned long long)image.reads);
    for (unsigned i=0; i<catalog->count; ++i) {
        if (i) putchar(',');
        printf("{\"system\":"); json_string(catalog->systems[catalog->entries[i].system]);
        printf(",\"version\":"); json_string(catalog->entries[i].version);
        printf(",\"release\":"); json_string(catalog->entries[i].release);
        printf(",\"current\":%u,\"previous\":%u,\"payload_status\":%d,\"payload_checked\":%s}",
               catalog->entries[i].current,catalog->entries[i].previous,payload_status[i],
               discovered && (!script || i == selected) ? "true" : "false");
    }
    printf("],\"selection\":");
    if (selected >= catalog->count) printf("null");
    else {
        const struct kshim_boot_entry *e=&selected_entry;
        printf("{\"system\":"); json_string(catalog->systems[catalog->entries[selected].system]);
        printf(",\"version\":"); json_string(catalog->entries[selected].version);
        printf(",\"cmdline\":"); json_string(e->cmdline);
        printf(",\"payload_sha256\":{\"image\":"); json_string(observed[0]);
        printf(",\"dtb\":"); json_string(observed[1]);
        printf(",\"initrd\":");
        if (e->initrd.size) json_string(observed[2]); else printf("null");
        printf("}}");
    }
    printf("}\n");
    free(payload_status);
    kshim_boot_catalog_free(catalog);
    free(fs);free(catalog);close(image.fd);
    return rc ? 1 : 0;
}
