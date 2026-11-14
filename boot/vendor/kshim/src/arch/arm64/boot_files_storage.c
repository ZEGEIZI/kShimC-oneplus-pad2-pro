/* SPDX-License-Identifier: GPL-3.0-only */
#include <config.h>
#include <boot_files_native.h>
#include <storage_ufs.h>
#include <storage_ufs_dma.h>
#include <storage_ufs_native_io.h>
#include <storage_probe_io.h>
#include <device_info.h>
#include <dt.h>
#include <timer.h>
#include <string.h>
#include <stdio.h>

static _Alignas(4096) uint8_t arena[KSHIM_UFS_DMA_BYTES];
static uint8_t scratch[KSHIM_STORAGE_SCRATCH_BYTES];
static struct storage_probe_snapshot snapshot;
static struct kshim_ufs_host host;
static struct kshim_ufs_lun selected_lun;
static struct kshim_ext4 filesystem;
static const char *stage = "idle";
static char detail[80];
static int restore_failed;
const char *kshim_boot_storage_stage(void) { return stage; }
const char *kshim_boot_storage_detail(void) { return detail; }
static uint64_t now(void *ctx) { (void)ctx; return get_current_time(); }
static void pause_us(void *ctx, uint32_t us) { (void)ctx; (void)delay(us); }
static const struct kshim_ufs_ops ops = {
    .read32=storage_ufs_native_read32, .write32=storage_ufs_native_write32,
    .sync_device=storage_ufs_native_sync_device, .sync_cpu=storage_ufs_native_sync_cpu,
    .now_ms=now, .delay_us=pause_us, .manage_link=true
};
/* Prove the documented board windows from the incoming, validated DT before
 * native helpers use the fixed MMIO whitelist. Do not infer them from a menu. */
static int profile(const void *fdt)
{
    struct device_info info; struct dt_range r;
    device_info_read(fdt,&info);
    if (info.board != DEVICE_BOARD_ONEPLUS_PAD2PRO) return KSHIM_STORAGE_UNSUPPORTED;
    int ufs = fdt_node_offset_by_compatible(fdt,-1,"qcom,sm8750-ufshc");
    if (ufs < 0) ufs = fdt_node_offset_by_compatible(fdt,-1,"qcom,ufshc");
    if (ufs < 0 || dt_reg(fdt,ufs,0,&r) || r.base != 0x1d84000 || r.size != 0x3000)
        return KSHIM_STORAGE_UNSUPPORTED;
    int len; const fdt32_t *iommu = fdt_getprop(fdt,ufs,"iommus",&len);
    if (!iommu || len != 12 || fdt32_to_cpu(iommu[1]) != 0x60 || iommu[2])
        return KSHIM_STORAGE_UNSUPPORTED;
    int smmu = fdt_node_offset_by_phandle(fdt,fdt32_to_cpu(iommu[0]));
    if (smmu < 0 || dt_reg(fdt,smmu,0,&r) || r.base != 0x15000000 || r.size != 0x100000)
        return KSHIM_STORAGE_UNSUPPORTED;
    return 0;
}
int kshim_boot_storage_close(void)
{
    /* Release preserves poisoned/owned state on failure; never clear it. */
    if (restore_failed) return KSHIM_UFS_QUARANTINED;
    if (!host.owned) return 0;
    /* Preserve completed-command evidence before release submits any power
     * restoration command. Pure RAM reads add no diagnostic MMIO. */
    snprintf(detail,sizeof(detail),"L%u op%x s%x k%x %02x/%02x o%x r%x f%x",
        host.last_scsi_lun,host.last_scsi_opcode,host.last_scsi_status,
        host.last_sense_key,host.last_sense_asc,host.last_sense_ascq,
        arena[8]&15,arena[1536+6],arena[1536+1]);
    int rc = kshim_ufs_release(&host);
    if (rc) return rc;
    const uint32_t offsets[] = {0x50,0x54,0x60,0x24,0x18,0x58,0x78};
    const uint32_t expected[] = {host.saved_base[0],host.saved_base[1],
        host.saved_run,host.saved_ie,host.saved_ahit,0,0};
    for (unsigned i = 0; i < sizeof(offsets)/sizeof(offsets[0]); ++i) {
        uint32_t value;
        if (ops.read32(ops.ctx,offsets[i],&value) || value != expected[i]) {
            restore_failed = 1;
            return KSHIM_UFS_QUARANTINED;
        }
    }
    return 0;
}
int kshim_boot_storage_open(const void *fdt, struct kshim_ext4 **out)
{
    uint64_t physical; uint8_t uuid[16];
    *out = NULL;
    detail[0] = 0;
    if (host.owned || restore_failed) return KSHIM_UFS_QUARANTINED;
    stage = "profile";
    int rc = profile(fdt);
    if (rc) return rc;
    if (!arm64_read_cntfrq()) return KSHIM_STORAGE_UNSUPPORTED;
    stage = "CPU mapping";
    rc = storage_ufs_native_dma_address(arena,sizeof(arena),&physical);
    if (rc) return rc;
    stage = "SMMU";
    storage_probe_native_capture(DEVICE_BOARD_ONEPLUS_PAD2PRO,&snapshot);
    if (!kshim_ufs_dma_is_identity(&snapshot,physical,sizeof(arena))) return KSHIM_UFS_UNSUPPORTED;
    stage = "claim";
    rc = kshim_ufs_claim(&host,&ops,arena,sizeof(arena),physical);
    if (!rc) { stage = "NOP"; rc = kshim_ufs_nop(&host); }
    if (!rc) { stage = "power"; rc = kshim_ufs_prepare_device(&host); }
    if (rc) return rc;
    const char *name = NULL; const uint8_t *wanted = NULL;
    if (CONFIG_KSHIM_BOOT_PARTUUID[0]) {
        rc = kshim_boot_uuid(CONFIG_KSHIM_BOOT_PARTUUID,uuid);
        if (rc) return rc;
        wanted = uuid;
    } else name = CONFIG_KSHIM_BOOT_PARTLABEL;
    unsigned matches = 0;
    struct kshim_partition partition = {0};
    uint8_t device_descriptor[255]; uint16_t device_length = sizeof(device_descriptor);
    stage = "device descriptor";
    rc = kshim_ufs_read_descriptor(&host,0,0,device_descriptor,&device_length);
    if (rc) return rc;
    if (device_length < 8 || !device_descriptor[6] || device_descriptor[6] > 8)
        return KSHIM_STORAGE_FORMAT;
    unsigned enabled = 0, total_luns = device_descriptor[6];
    /* UFS general-purpose LUNs 0..7. Enumerate descriptors first: absence is
     * distinct from a failed READ CAPACITY and never masks a timeout. */
    for (unsigned i = 0; i < 8 && enabled < total_luns; ++i) {
        stage = "LUN descriptor";
        uint8_t descriptor[255]; uint16_t len = sizeof(descriptor);
        rc = kshim_ufs_read_descriptor(&host,2,i,descriptor,&len);
        if (rc) return rc;
        if (len < 4 || descriptor[2] != i) return KSHIM_STORAGE_FORMAT;
        if (!descriptor[3]) continue; /* bLUEnable */
        ++enabled;
        struct kshim_ufs_lun lun;
        stage = "LUN capacity";
        rc = kshim_ufs_open_lun(&host,i,false,&lun);
        if (rc) return rc;
        struct kshim_partition p;
        stage = "GPT";
        rc = kshim_gpt_find(&lun.block,wanted,name,&p,scratch,sizeof(scratch));
        /* An enabled raw LUN may have no GPT, but a corrupt GPT is an error.
         * Only lack of its signature is an absence; inspect exact bytes. */
        if (rc == KSHIM_STORAGE_FORMAT) {
            int rr = kshim_block_read(&lun.block,1,1,scratch);
            if (rr) return rr;
            if (memcmp(scratch,"EFI PART",8)) continue;
        }
        if (rc == KSHIM_STORAGE_NOT_FOUND) continue;
        if (rc) return rc;
        if (++matches > 1) return KSHIM_STORAGE_CONFLICT;
        selected_lun = lun; selected_lun.block.ctx = &selected_lun;
        partition = p;
    }
    if (enabled != total_luns) return KSHIM_STORAGE_FORMAT;
    if (!matches) return KSHIM_STORAGE_NOT_FOUND;
    stage = "ext4";
    rc = kshim_ext4_mount(&filesystem,&selected_lun.block,&partition);
    if (!rc) *out = &filesystem;
    return rc;
}
