/* SPDX-License-Identifier: GPL-3.0-only */
#include <config.h>
#include <boot_files_native.h>
#include <boot_files_memory.h>
#include <boot_files_dt.h>
#include <boot_files_menu.h>
#include <kshim.h>
#include <kshim_mmu.h>
#include <kshim_console.h>
#include <arm64/boot.h>
#include <platform.h>
#include <dt_handoff.h>
#include <dt_simplefb.h>
#include <device_info.h>
#include <qcom_dt.h>
#include <timer.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
extern unsigned char __image_start_address__[], __runtime_end_address__[];
static struct kshim_boot_catalog catalog;
static struct kshim_boot_memory memory;
static _Alignas(8) uint8_t snapshot[DT_MEMORY_SNAPSHOT_BYTES], overlay[DT_MEMORY_OVERLAY_BYTES];
static _Alignas(8) uint8_t output[KSHIM_BOOT_DTB_OUTPUT_BYTES];
static const char *payload_stage = "payload";
static void unsafe(void) __attribute__((noreturn));
static void unsafe(void)
{
    printf("External boot: unsafe storage/UI shutdown; stopped\n");
    __asm__ volatile("msr daifset, #0xf" ::: "memory");
    for (;;) __asm__ volatile("wfe");
}
static int load(struct kshim_ext4 *fs, const struct kshim_boot_entry *e,
                 uint64_t runtime, uint64_t packed, uint64_t packed_bytes,
                 uint64_t *kernel, void *dtb, size_t dtb_capacity)
{
    uint8_t header[64]; NH_FILE file; char path[512];
    payload_stage = "Image header";
    int n = snprintf(path,sizeof(path),"kshim/systems/%s/versions/%s/%s",e->system,e->version,e->image.path);
    if (n < 0 || (size_t)n >= sizeof(path)) return KSHIM_STORAGE_RANGE;
    int rc = kshim_ext4_open(fs,path,&file);
    if (!rc) rc = kshim_ext4_read(&file,0,header,sizeof(header));
    uint64_t size, offset, initrd = 0;
    if (!rc) rc = kshim_boot_image_header(header,e->image.size,&size,&offset);
    if (rc) return rc;
    if (size + e->dtb.size + e->initrd.size > KSHIM_BOOT_TOTAL_MAX) return KSHIM_STORAGE_OVERFLOW;
    if (e->dtb.size > dtb_capacity) return KSHIM_STORAGE_OVERFLOW;
    payload_stage = "DTB SHA256";
    rc = kshim_boot_read_payload(fs,e,&e->dtb,dtb,e->dtb.size);
    if (rc) return rc;
    payload_stage = "DTB identity";
    rc = kshim_boot_validate_dtb(dtb,e->dtb.size);
    if (rc) return rc;
    payload_stage = "memory DT";
    if (!rc) rc = dt_memory_capture((void *)(uintptr_t)runtime,fdt_totalsize((void *)(uintptr_t)runtime),snapshot,sizeof(snapshot));
    if (!rc) rc = dt_memory_apply(snapshot,sizeof(snapshot),dtb,e->dtb.size,output,sizeof(output),overlay,sizeof(overlay));
    if (rc) return rc;
    payload_stage = "RAM placement";
    rc = kshim_boot_memory_init(&memory,output);
    if (!rc) rc = kshim_boot_memory_reserve(&memory,(uintptr_t)__image_start_address__,
        (uintptr_t)__runtime_end_address__-(uintptr_t)__image_start_address__);
    if (!rc) rc = kshim_boot_memory_reserve(&memory,packed,packed_bytes);
    if (!rc) rc = kshim_boot_memory_reserve(&memory,runtime,fdt_totalsize((void *)(uintptr_t)runtime));
    struct kshim_resources *resources = kshim_resources_get();
    if (!rc && resources && resources->splash_status == 0) {
        const kshim_framebuffer_config_t *fb = &resources->framebuffer;
        rc = kshim_boot_memory_reserve(&memory,fb->render_address,
            fb->buffer_size ? fb->buffer_size : (uint64_t)fb->stride*fb->height);
    }
    if (!rc && resources) rc = kshim_boot_memory_reserve(&memory,
        resources->ui_scratch.base,resources->ui_scratch.size);
    if (!rc) rc = kshim_boot_memory_alloc(&memory,size,0x200000,offset,kernel);
    if (!rc && e->initrd.size) rc = kshim_boot_memory_alloc(&memory,e->initrd.size,65536,0,&initrd);
    if (rc) return rc;
    /* The initrd and kernel must fit the ARM64 1 GiB aligned 32 GiB window. */
    if (initrd) {
        uint64_t low = (*kernel < initrd ? *kernel : initrd)&~UINT64_C(0x3fffffff);
        uint64_t high = *kernel+size > initrd+e->initrd.size ? *kernel+size : initrd+e->initrd.size;
        if (high-low > UINT64_C(0x800000000)) return KSHIM_STORAGE_RANGE;
    }
    /* Register each new CPU mapping for cache clean at the final handoff. */
    payload_stage = "CPU map";
    rc = kshim_mmu_add_region(*kernel,size,KSHIM_MMU_NORMAL_WB,KSHIM_MMU_READ|KSHIM_MMU_WRITE|KSHIM_MMU_EXECUTE);
    if (!rc && initrd) rc = kshim_mmu_add_region(initrd,e->initrd.size,KSHIM_MMU_NORMAL_WB,KSHIM_MMU_READ|KSHIM_MMU_WRITE);
    if (rc) return rc;
    payload_stage = "Image SHA256";
    rc = kshim_boot_read_payload(fs,e,&e->image,(void *)(uintptr_t)*kernel,size);
    if (!rc && memcmp(header,(void *)(uintptr_t)*kernel,64)) rc = KSHIM_STORAGE_FORMAT;
    if (!rc && size > e->image.size) memset((void *)(uintptr_t)(*kernel+e->image.size),0,size-e->image.size);
    if (!rc && initrd) {
        payload_stage = "initrd SHA256";
        rc = kshim_boot_read_payload(fs,e,&e->initrd,(void *)(uintptr_t)initrd,e->initrd.size);
    }
    if (rc) return rc;
    payload_stage = "chosen";
    rc = kshim_boot_chosen(output,sizeof(output),e,initrd);
    if (rc) return rc;
    payload_stage = "simplefb";
    rc = dt_simplefb_apply(output,sizeof(output),resources && resources->splash_status == 0 ? &resources->framebuffer : NULL);
    if (rc) return rc;
    payload_stage = "DTB pack";
    if (!rc) rc = fdt_pack(output);
    if (!rc) rc = dt_validate(output,sizeof(output));
    return rc;
}
struct menu_context { uint64_t runtime; struct device_info info; };
static int select_menu(void *opaque, const char *const *names,
    const char *const *descriptions, size_t count, size_t initial,
    uint32_t timeout_ms, size_t *selected)
{
    struct menu_context *context = opaque;
    kshim_menu_role_t roles[KSHIM_BOOT_MENU_ROWS];
    if (count > KSHIM_BOOT_MENU_ROWS) return KSHIM_STORAGE_RANGE;
    for (size_t i = 0; i < count; ++i) roles[i] = KSHIM_MENU_ROLE_UNKNOWN;
    /* kshim_boot_choose always puts its parent-menu return entry first. */
    if (count) roles[0] = KSHIM_MENU_ROLE_BACK;
    return kshim_platform_select_localized_info(context->runtime,names,descriptions,
        roles,&context->info,count,initial,timeout_ms,0,selected);
}
int kshim_boot_external(uint64_t runtime, uint64_t packed, uint64_t packed_bytes,
                         void *dtb_source, size_t capacity)
{
    struct kshim_ext4 *fs = NULL; uint64_t kernel = 0;
    if (kshim_mmu_enable_current_cpu()) return KSHIM_STORAGE_MEMORY;
    int rc = kshim_boot_storage_open((void *)(uintptr_t)runtime,&fs);
    const char *stage = kshim_boot_storage_stage();
    if (!rc) { stage = "catalog"; rc = kshim_boot_discover(fs,&catalog); }
    if (kshim_boot_storage_close()) unsafe();
    if (!rc) {
        size_t selected = SIZE_MAX;
        struct menu_context context = {.runtime = runtime};
        device_info_read((void *)(uintptr_t)runtime,&context.info);
        if (kshim_boot_choose(&catalog,select_menu,&context,&selected)) unsafe();
        if (selected == SIZE_MAX) {
            kshim_boot_catalog_free(&catalog);
            return 0;
        }
        if (kshim_mmu_enable_current_cpu()) unsafe();
        struct kshim_boot_summary row = catalog.entries[selected];
        kshim_boot_catalog_free(&catalog);
        rc = row.error;
        if (!rc) rc = kshim_boot_storage_open((void *)(uintptr_t)runtime,&fs);
        stage = kshim_boot_storage_stage();
        if (!rc) {
            struct kshim_boot_entry entry;
            stage = "selected manifest";
            rc = kshim_boot_open_entry(fs,catalog.systems[row.system],row.version,&entry);
            if (!rc) {
                rc = load(fs,&entry,runtime,packed,packed_bytes,&kernel,dtb_source,capacity);
                stage = payload_stage;
            }
        }
        if (kshim_boot_storage_close()) unsafe();
        if (!rc) {
            if (kshim_platform_prepare_handoff() || kshim_console_quiesce()) unsafe();
            __asm__ volatile("dsb sy\n\tic iallu\n\tdsb sy\n\tisb" ::: "memory");
            arm64_boot_linux(kernel,(uintptr_t)output,0);
        }
    }
    if (kshim_platform_prepare_handoff()) unsafe();
    /* Error remains visible until a key selects the original menu. */
    char error[96]; snprintf(error,sizeof(error),"%s %d %.60s; return",stage,rc,kshim_boot_storage_detail());
    const char *name[] = {error}; size_t selected = 0;
    if (kshim_platform_select(runtime,name,1,0,0,&selected)) unsafe();
    return rc;
}
