/* SPDX-License-Identifier: GPL-3.0-only */
#include <boot_files_dt.h>
#include <device_info.h>
#include <storage_block.h>
#include <dt.h>
#include <ext4_boot.h>
#include <limits.h>
#include <string.h>

int kshim_boot_validate_dtb(const void *dtb, size_t bytes)
{
    int rc = dt_validate(dtb,bytes);
    if (rc) return rc;
    struct device_info info;
    device_info_read(dtb,&info);
    /* A Linux DT does not carry ABL's stock model/panel-selection fingerprint.
     * Require its explicit OPD2413 board and SM8750 SoC declarations instead.
     * device_info_read validates the full compatible string list and rejects
     * mixed SoC families; use exact entries, never model text or substrings. */
    if (!info.compatible_known || info.soc != DEVICE_SOC_SM8750 ||
        fdt_node_check_compatible(dtb,0,"oneplus,opd2413") ||
        fdt_node_check_compatible(dtb,0,"qcom,sm8750"))
        return KSHIM_STORAGE_UNSUPPORTED;
    const char *conflicts[] = {"lenovo,elden","lenovo,tb323fu","lenovo,baldur"};
    for (unsigned i = 0; i < sizeof(conflicts)/sizeof(conflicts[0]); ++i)
        if (!fdt_node_check_compatible(dtb,0,conflicts[i]))
            return KSHIM_STORAGE_UNSUPPORTED;
    return 0;
}

int kshim_boot_chosen(void *dtb, size_t capacity,
                       const struct kshim_boot_entry *entry, uint64_t initrd)
{
    if (!entry || !entry->cmdline[0] ||
        !memchr(entry->cmdline,0,sizeof(entry->cmdline)) ||
        !memchr(entry->system,0,sizeof(entry->system)) ||
        !memchr(entry->version,0,sizeof(entry->version)) ||
        capacity > INT_MAX ||
        ((!initrd) != (!entry->initrd.size)) ||
        initrd > UINT64_MAX-entry->initrd.size)
        return -FDT_ERR_BADVALUE;
    int rc = dt_validate(dtb,capacity);
    if (rc) return rc;
    /* dt_memory_apply() packs its output. The backing array may have ample
     * room while totalsize still advertises only that packed length. Restore
     * the writable capacity before adding bootargs, initrd or source fields. */
    rc = fdt_open_into(dtb,dtb,(int)capacity);
    if (rc) return rc;
    int chosen = fdt_path_offset(dtb,"/chosen");
    if (chosen == -FDT_ERR_NOTFOUND) chosen = fdt_add_subnode(dtb,0,"chosen");
    if (chosen < 0) return chosen;
    rc = fdt_setprop_string(dtb,chosen,"bootargs",entry->cmdline);
    const char *remove[] = {"kshim,initrd-entry","linux,initrd-start","linux,initrd-end"};
    for (unsigned i = 0; !rc && i < sizeof(remove)/sizeof(remove[0]); ++i) {
        int dr = fdt_delprop(dtb,fdt_path_offset(dtb,"/chosen"),remove[i]);
        if (dr && dr != -FDT_ERR_NOTFOUND) rc = dr;
    }
    if (!rc && initrd) rc = fdt_setprop_u64(dtb,fdt_path_offset(dtb,"/chosen"),"linux,initrd-start",initrd);
    if (!rc && initrd) rc = fdt_setprop_u64(dtb,fdt_path_offset(dtb,"/chosen"),"linux,initrd-end",initrd+entry->initrd.size);
    if (!rc) rc = fdt_setprop_string(dtb,fdt_path_offset(dtb,"/chosen"),"kshim,boot-source","ext4");
    if (!rc) rc = fdt_setprop_string(dtb,fdt_path_offset(dtb,"/chosen"),"kshim,system-id",entry->system);
    if (!rc) rc = fdt_setprop_string(dtb,fdt_path_offset(dtb,"/chosen"),"kshim,boot-id",entry->version);
    return rc;
}
