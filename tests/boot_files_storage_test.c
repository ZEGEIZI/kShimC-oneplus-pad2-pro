/* SPDX-License-Identifier: GPL-3.0-only */
/* Real native session/GPT code; substitute the transport and platform edges. */
#include <boot_files_native.h>
#include <storage_ufs.h>
#include <storage_ufs_dma.h>
#include <storage_ufs_native_io.h>
#include <storage_probe_io.h>
#include <device_info.h>
#include <dt.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { SUCCESS, BAD_PROFILE, BAD_DMA, BAD_SMMU, CLAIM_FAIL, CLAIM_PARTIAL,
       NOP_FAIL, READ_FAIL, BAD_GPT_CRC, MISSING, DUPLICATE, RELEASE_FAIL,
       RESTORE_MISMATCH, RESTORE_IO, BAD_DESCRIPTOR, CASES };
static int scenario;
static unsigned claims, releases, mounts, capacities, descriptor_calls;
static uint8_t *dma_arena;
static struct kshim_ufs_host *active_host;
static fdt32_t iommu[3];
static uint8_t fake_fdt;
static void put32(uint8_t *p,uint32_t v)
{ for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i)); }
static void put64(uint8_t *p,uint64_t v)
{ for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(v>>(8*i)); }
static void table(uint8_t *p)
{
    static const uint8_t id[16]={0x33,0x22,0x11,0,0x55,0x44,0x77,0x66,0x88,0x99,0xaa,0xbb,0xcc,0xdd,0xee,0xff};
    memset(p,0,4096);memset(p,0xab,16);memcpy(p+16,id,16);
    put64(p+32,16);put64(p+40,255);
}
static int block_read(void *ctx,uint64_t lba,uint32_t count,void *buffer)
{
    struct kshim_ufs_lun *l=ctx;
    assert(l && l->host==active_host && (l->number==0 || l->number==3) && count==1);
    struct kshim_ufs_host *h=l->host;
    h->last_scsi_opcode=0x28;h->last_scsi_lun=l->number;
    memset(buffer,0,4096);
    if(scenario==READ_FAIL && l->number==0) {
        h->last_scsi_status=2;h->last_sense_key=5;
        h->last_sense_asc=0x20;h->last_sense_ascq=0;
        return KSHIM_UFS_SCSI;
    }
    if(scenario==MISSING || (l->number==0 && scenario!=DUPLICATE))return 0;
    if(lba==2)table(buffer);
    else if(lba==1) {
        uint8_t entries[4096];table(entries);uint8_t *p=buffer;
        memcpy(p,"EFI PART",8);put32(p+8,0x10000);put32(p+12,92);
        put64(p+24,1);put64(p+32,4095);put64(p+40,3);put64(p+48,4093);
        memset(p+56,1,16);put64(p+72,2);put32(p+80,8);put32(p+84,128);
        put32(p+88,kshim_crc32(entries,1024));put32(p+16,kshim_crc32(p,92));
        if(scenario==BAD_GPT_CRC)p[16]^=1;
    } else ((uint8_t *)buffer)[0]=l->number;
    return 0;
}
void device_info_read(const void *fdt,struct device_info *out)
{
    assert(fdt==&fake_fdt);memset(out,0,sizeof(*out));
    out->board=scenario==BAD_PROFILE ? DEVICE_BOARD_UNKNOWN : DEVICE_BOARD_ONEPLUS_PAD2PRO;
}
int fdt_node_offset_by_compatible(const void *fdt,int start,const char *name)
{ assert(fdt==&fake_fdt && start==-1 && !strcmp(name,"qcom,sm8750-ufshc"));return 1; }
const void *fdt_getprop(const void *fdt,int node,const char *name,int *len)
{ assert(fdt==&fake_fdt && node==1 && !strcmp(name,"iommus"));*len=12;return iommu; }
int fdt_node_offset_by_phandle(const void *fdt,uint32_t phandle)
{ assert(fdt==&fake_fdt && phandle==42);return 2; }
int dt_reg(const void *fdt,int node,unsigned index,struct dt_range *out)
{
    assert(fdt==&fake_fdt && !index && (node==1 || node==2));
    *out=node==1 ? (struct dt_range){0x1d84000,0x3000} : (struct dt_range){0x15000000,0x100000};
    return 0;
}
uint64_t arm64_read_cntfrq(void){return 19200000;}
uint64_t get_current_time(void){return 1;}
uint64_t delay(uint64_t us){return us;}
int storage_ufs_native_dma_address(void *arena,size_t bytes,uint64_t *physical)
{
    assert(arena && !((uintptr_t)arena&4095) && bytes==8192);
    dma_arena=arena;*physical=0x90000000;
    return scenario==BAD_DMA ? KSHIM_STORAGE_RANGE : 0;
}
void storage_probe_native_capture(enum device_board board,struct storage_probe_snapshot *out)
{ assert(board==DEVICE_BOARD_ONEPLUS_PAD2PRO);memset(out,0,sizeof(*out));out->board=board; }
bool kshim_ufs_dma_is_identity(const struct storage_probe_snapshot *s,uint64_t pa,uint64_t bytes)
{ assert(s->board==DEVICE_BOARD_ONEPLUS_PAD2PRO && pa==0x90000000 && bytes==8192);return scenario!=BAD_SMMU; }
int storage_ufs_native_read32(void *ctx,uint32_t offset,uint32_t *value)
{
    (void)ctx;
    switch(offset) {
    case 0x50:*value=0x12340000;break;case 0x54:*value=0;break;
    case 0x60:*value=1;break;case 0x24:*value=0x400;break;case 0x18:*value=0x123;break;
    case 0x58:case 0x78:*value=0;break;default:assert(0);
    }
    if(offset==0x50 && scenario==RESTORE_MISMATCH)*value^=1;
    return offset==0x50 && scenario==RESTORE_IO ? -1 : 0;
}
int storage_ufs_native_write32(void *ctx,uint32_t o,uint32_t v)
{ (void)ctx;(void)o;(void)v;assert(0);return -1; }
void storage_ufs_native_sync_device(void *ctx,void *buffer,size_t bytes)
{ (void)ctx;(void)buffer;(void)bytes;assert(0); }
void storage_ufs_native_sync_cpu(void *ctx,void *buffer,size_t bytes)
{ (void)ctx;(void)buffer;(void)bytes;assert(0); }
int kshim_ufs_claim(struct kshim_ufs_host *h,const struct kshim_ufs_ops *ops,
                    void *arena,size_t bytes,uint64_t address)
{
    ++claims;assert(!h->owned && ops->manage_link && arena==dma_arena && bytes==8192 && address==0x90000000);
    assert(ops->read32 && ops->write32 && ops->sync_cpu && ops->sync_device);
    active_host=h;
    if(scenario==CLAIM_FAIL)return KSHIM_UFS_BUSY;
    h->owned=1;h->arena=arena;
    h->saved_base[0]=0x12340000;h->saved_base[1]=0;
    h->saved_run=1;h->saved_ie=0x400;h->saved_ahit=0x123;
    return scenario==CLAIM_PARTIAL ? KSHIM_UFS_BUSY : 0;
}
int kshim_ufs_nop(struct kshim_ufs_host *h)
{ assert(h==active_host && h->owned);return scenario==NOP_FAIL ? KSHIM_UFS_RESPONSE : 0; }
int kshim_ufs_prepare_device(struct kshim_ufs_host *h)
{ assert(h==active_host && h->owned);return 0; }
int kshim_ufs_read_descriptor(struct kshim_ufs_host *h,uint8_t id,uint8_t index,void *out,uint16_t *length)
{
    assert(h==active_host && h->owned && *length==255);++descriptor_calls;
    uint8_t *p=out;memset(p,0,255);p[0]=8;p[1]=id;*length=8;
    if(id==0){assert(!index);p[6]=2;}
    else {assert(id==2 && index<=3);p[2]=index;p[3]=index==0 || index==3;}
    if(scenario==BAD_DESCRIPTOR && id==2)p[2]=7;
    return 0;
}
int kshim_ufs_open_lun(struct kshim_ufs_host *h,uint8_t number,bool writes,struct kshim_ufs_lun *out)
{
    assert(h==active_host && !writes && (number==0 || number==3));++capacities;
    *out=(struct kshim_ufs_lun){.host=h,.number=number};
    out->block=(struct kshim_blockdev){.ctx=out,.block_size=4096,.block_count=4096,.read=block_read};
    return 0;
}
int kshim_ufs_release(struct kshim_ufs_host *h)
{
    assert(h==active_host && h->owned);++releases;
    /* Release may overwrite the live command state. Error reporting must
     * retain the pre-release SCSI command, never this cleanup command. */
    h->last_scsi_opcode=0x1b;
    if(scenario==RELEASE_FAIL)return KSHIM_UFS_QUARANTINED;
    h->owned=0;return 0;
}
int kshim_ext4_mount(struct kshim_ext4 *fs,const struct kshim_blockdev *dev,const struct kshim_partition *part)
{
    ++mounts;assert(!dev->write && !dev->flush && part->first_lba==16 && part->last_lba==255);
    memset(fs,0,sizeof(*fs));fs->dev=dev;fs->partition=*part;
    return 0;
}
static void verify_saved_block_context(struct kshim_ext4 *fs)
{
    uint8_t data[4096];
    assert(!kshim_block_read(fs->dev,16,1,data) && data[0]==3);
}
int main(int argc,char **argv)
{
    assert(argc==2);scenario=atoi(argv[1]);assert(scenario>=0 && scenario<CASES);
    iommu[0]=cpu_to_fdt32(42);iommu[1]=cpu_to_fdt32(0x60);iommu[2]=0;
    struct kshim_ext4 *fs=(void *)(uintptr_t)1;
    int rc=kshim_boot_storage_open(&fake_fdt,&fs);
    static const int expected[CASES]={0,KSHIM_STORAGE_UNSUPPORTED,KSHIM_STORAGE_RANGE,KSHIM_UFS_UNSUPPORTED,
        KSHIM_UFS_BUSY,KSHIM_UFS_BUSY,KSHIM_UFS_RESPONSE,KSHIM_STORAGE_IO,KSHIM_STORAGE_CRC,
        KSHIM_STORAGE_NOT_FOUND,KSHIM_STORAGE_CONFLICT,0,0,0,KSHIM_STORAGE_FORMAT};
    assert(rc==expected[scenario]);
    if(rc)assert(!fs);
    else {
        assert(fs && mounts==1 && capacities==2 && descriptor_calls==5);
        verify_saved_block_context(fs);
    }
    unsigned expected_releases=scenario==SUCCESS || scenario>=CLAIM_PARTIAL;
    int close=kshim_boot_storage_close();
    if(scenario==RELEASE_FAIL || scenario==RESTORE_MISMATCH || scenario==RESTORE_IO) {
        assert(close==KSHIM_UFS_QUARANTINED);
        unsigned before=claims;
        assert(kshim_boot_storage_open(&fake_fdt,&fs)==KSHIM_UFS_QUARANTINED && claims==before);
    } else {
        assert(!close);
        assert(!kshim_boot_storage_close());
    }
    assert(releases==expected_releases);
    if(scenario>=BAD_PROFILE && scenario<=BAD_SMMU)assert(!claims);
    else assert(claims==1);
    if(scenario==READ_FAIL)assert(strstr(kshim_boot_storage_detail(),"L0 op28 s2 k5 20/00"));
    printf("native storage scenario %d passed\n",scenario);
    return 0;
}
