/* SPDX-License-Identifier: GPL-3.0-only */
#include <boot_files_dt.h>
#include <device_info.h>
#include <storage_block.h>
#include <dt.h>
#include <dt_handoff.h>
#include <dt_simplefb.h>
#include <ext4_boot.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static _Alignas(8) uint8_t blob[4096];
static void tree(const char *compatible,size_t bytes)
{
    assert(!fdt_create_empty_tree(blob,sizeof(blob)));
    assert(!fdt_setprop(blob,0,"compatible",compatible,bytes));
    assert(!fdt_setprop_string(blob,0,"model","OnePlus Pad 2 Pro (OPD2413) bootc rootfs study"));
}
static void check(const char *compatible,size_t bytes,int expected)
{
    tree(compatible,bytes);
    assert(kshim_boot_validate_dtb(blob,sizeof(blob))==expected);
}
#define CHECK(s,expected) check(s,sizeof(s),expected)
static struct kshim_boot_entry entry;
static uint64_t property64(const void *dtb,const char *name)
{
    int len;const fdt64_t *value=fdt_getprop(dtb,fdt_path_offset(dtb,"/chosen"),name,&len);
    assert(value && len==8);return fdt64_ld(value);
}
static void chosen_tests(void)
{
    tree("oneplus,opd2413\0qcom,sm8750",sizeof("oneplus,opd2413\0qcom,sm8750"));
    int chosen=fdt_add_subnode(blob,0,"chosen");assert(chosen>=0);
    assert(!fdt_setprop_string(blob,chosen,"bootargs","old"));
    assert(!fdt_setprop_string(blob,chosen,"stdout-path","serial0"));
    assert(!fdt_setprop_u32(blob,chosen,"kshim,initrd-entry",3));
    assert(!fdt_setprop_u32(blob,chosen,"linux,initrd-start",0));
    assert(!fdt_setprop_u32(blob,chosen,"linux,initrd-end",0));
    assert(!fdt_pack(blob));
    /* Reproduce the old -NOSPACE: the array is large, but its packed FDT
     * header advertises no free space for a longer command line. */
    assert(fdt_setprop_string(blob,fdt_path_offset(blob,"/chosen"),"bootargs",
        "root=UUID=example rootflags=subvol=/root rw") == -FDT_ERR_NOSPACE);
    memset(&entry,0,sizeof(entry));
    strcpy(entry.cmdline,"root=UUID=example rootflags=subvol=/root rw");
    strcpy(entry.system,"example");strcpy(entry.version,"version-1");entry.initrd.size=12345;
    assert(!kshim_boot_chosen(blob,sizeof(blob),&entry,0x98000000));
    chosen=fdt_path_offset(blob,"/chosen");
    assert(!strcmp(dt_string(blob,chosen,"bootargs"),entry.cmdline));
    assert(!strcmp(dt_string(blob,chosen,"stdout-path"),"serial0"));
    assert(!strcmp(dt_string(blob,chosen,"kshim,boot-source"),"ext4"));
    assert(!strcmp(dt_string(blob,chosen,"kshim,system-id"),entry.system));
    assert(!strcmp(dt_string(blob,chosen,"kshim,boot-id"),entry.version));
    int len;assert(!fdt_getprop(blob,chosen,"kshim,initrd-entry",&len) && len==-FDT_ERR_NOTFOUND);
    assert(property64(blob,"linux,initrd-start")==0x98000000);
    assert(property64(blob,"linux,initrd-end")==0x98000000+12345);
    assert(!fdt_pack(blob));entry.initrd.size=0;
    assert(!kshim_boot_chosen(blob,sizeof(blob),&entry,0));
    chosen=fdt_path_offset(blob,"/chosen");
    assert(!fdt_getprop(blob,chosen,"linux,initrd-start",&len) && len==-FDT_ERR_NOTFOUND);
    assert(!fdt_getprop(blob,chosen,"linux,initrd-end",&len) && len==-FDT_ERR_NOTFOUND);
    entry.initrd.size=16;
    assert(kshim_boot_chosen(blob,sizeof(blob),&entry,UINT64_MAX-1)==-FDT_ERR_BADVALUE);
    assert(kshim_boot_chosen(blob,sizeof(blob),&entry,0)==-FDT_ERR_BADVALUE);
}

static void large_handoff_test(void)
{
    static _Alignas(8) uint8_t input[KSHIM_BOOT_DTB_MAX];
    static _Alignas(8) uint8_t output[KSHIM_BOOT_DTB_OUTPUT_BYTES];
    static _Alignas(8) uint8_t snapshot[DT_MEMORY_SNAPSHOT_BYTES], overlay[DT_MEMORY_OVERLAY_BYTES];
    tree("oneplus,opd2413\0qcom,sm8750",sizeof("oneplus,opd2413\0qcom,sm8750"));
    assert(!fdt_setprop_u32(blob,0,"#address-cells",2));
    assert(!fdt_setprop_u32(blob,0,"#size-cells",2));
    int memory=fdt_add_subnode(blob,0,"memory@80000000");assert(memory>=0);
    assert(!fdt_setprop_string(blob,memory,"device_type","memory"));
    const fdt64_t reg[]={cpu_to_fdt64(0x80000000),cpu_to_fdt64(0x40000000)};
    assert(!fdt_setprop(blob,memory,"reg",reg,sizeof(reg)));
    assert(!dt_memory_capture(blob,sizeof(blob),snapshot,sizeof(snapshot)));
    assert(!fdt_open_into(blob,input,sizeof(input)));
    void *padding;
    const size_t padding_bytes=KSHIM_BOOT_DTB_MAX-1024;
    assert(!fdt_setprop_placeholder(input,0,"large-test-data",padding_bytes,&padding));
    memset(padding,0xa5,padding_bytes);
    assert(!fdt_pack(input));
    size_t bytes=fdt_totalsize(input);
    assert(bytes>320*1024 && bytes<=KSHIM_BOOT_DTB_MAX);
    assert(!kshim_boot_validate_dtb(input,bytes));
    assert(dt_memory_apply(snapshot,sizeof(snapshot),input,bytes,output,320*1024,
        overlay,sizeof(overlay))==-FDT_ERR_NOSPACE);
    assert(!dt_memory_apply(snapshot,sizeof(snapshot),input,bytes,output,sizeof(output),
        overlay,sizeof(overlay)));
    memset(&entry,0,sizeof(entry));
    strcpy(entry.system,"armadaos");strcpy(entry.version,"large-dtb-test");
    memset(entry.cmdline,'x',sizeof(entry.cmdline)-1);entry.initrd.size=26*1024*1024;
    assert(!kshim_boot_chosen(output,sizeof(output),&entry,0x98000000));
    const kshim_framebuffer_config_t fb={.render_address=0x90000000,.width=3392,.height=2400,
        .stride=3392*4,.bpp=32,.format=KSHIM_FB_FORMAT_XRGB8888,.buffer_size=3392*2400*4};
    assert(!dt_simplefb_apply(output,sizeof(output),&fb));
    assert(!fdt_pack(output) && !dt_validate(output,sizeof(output)));
    assert(!kshim_boot_validate_dtb(output,sizeof(output)));
    assert(property64(output,"linux,initrd-end")==0x98000000+entry.initrd.size);
    assert(strlen(dt_string(output,fdt_path_offset(output,"/chosen"),"bootargs"))==4095);
    int len;const uint8_t *saved=fdt_getprop(output,0,"large-test-data",&len);
    assert(saved && (size_t)len==padding_bytes);
    for(int i=0;i<len;++i) assert(saved[i]==0xa5);
    puts("Near-1-MiB DTB: memory merge, 4095-byte bootargs, initrd, simplefb and payload preservation passed");
}
int main(int argc,char **argv)
{
    CHECK("oneplus,opd2413\0qcom,sm8750",0);
    struct device_info info;device_info_read(blob,&info);
    /* Regression: the stock runtime fingerprint intentionally does not claim
     * that a Linux payload DT identifies the actual booted hardware. */
    assert(info.board==DEVICE_BOARD_UNKNOWN && info.soc==DEVICE_SOC_SM8750);
    assert(!fdt_setprop_string(blob,0,"model","Another Linux display name"));
    assert(!kshim_boot_validate_dtb(blob,sizeof(blob)));
    CHECK("qcom,sm8750",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("vendor,oneplus,opd2413\0qcom,sm8750",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413-extra\0qcom,sm8750",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413\0qcom,sm8850",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413\0qcom,sm8750\0qcom,canoep",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413\0qcom,sm8750\0lenovo,elden",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413\0qcom,sm8750\0lenovo,baldur",KSHIM_STORAGE_UNSUPPORTED);
    CHECK("oneplus,opd2413\0\0qcom,sm8750",KSHIM_STORAGE_UNSUPPORTED);
    const char missing_nul[]="oneplus,opd2413\0qcom,sm8750";
    check(missing_nul,sizeof(missing_nul)-1,KSHIM_STORAGE_UNSUPPORTED);
    tree(missing_nul,sizeof(missing_nul));
    assert(kshim_boot_validate_dtb(blob,39));
    blob[0]^=1;assert(kshim_boot_validate_dtb(blob,sizeof(blob)));
    chosen_tests();
    large_handoff_test();
    if(argc>=2) {
        FILE *f=fopen(argv[1],"rb");assert(f && !fseek(f,0,SEEK_END));
        long bytes=ftell(f);assert(bytes>0 && !fseek(f,0,SEEK_SET));
        void *payload=malloc(bytes);assert(payload);
        assert(fread(payload,1,bytes,f)==(size_t)bytes);fclose(f);
        assert(!kshim_boot_validate_dtb(payload,bytes));
        static _Alignas(8) uint8_t expanded[KSHIM_BOOT_DTB_OUTPUT_BYTES];
        assert(!fdt_open_into(payload,expanded,sizeof(expanded)));
        if(argc==3) {
            FILE *rf=fopen(argv[2],"rb");assert(rf && !fseek(rf,0,SEEK_END));
            long rbytes=ftell(rf);assert(rbytes>0 && !fseek(rf,0,SEEK_SET));
            void *runtime=malloc(rbytes);assert(runtime && fread(runtime,1,rbytes,rf)==(size_t)rbytes);fclose(rf);
            static _Alignas(8) uint8_t snapshot[DT_MEMORY_SNAPSHOT_BYTES],overlay[DT_MEMORY_OVERLAY_BYTES];
            assert(!dt_memory_capture(runtime,rbytes,snapshot,sizeof(snapshot)));
            assert(!dt_memory_apply(snapshot,sizeof(snapshot),payload,bytes,expanded,sizeof(expanded),overlay,sizeof(overlay)));
            free(runtime);
        }
        assert(!fdt_pack(expanded));
        memset(&entry,0,sizeof(entry));
        strcpy(entry.system,"armadaos");strcpy(entry.version,"test-version");
        memset(entry.cmdline,'x',sizeof(entry.cmdline)-1);entry.initrd.size=26*1024*1024;
        assert(!kshim_boot_chosen(expanded,sizeof(expanded),&entry,0x98000000));
        assert(!fdt_pack(expanded) && !dt_validate(expanded,sizeof(expanded)));
        assert(property64(expanded,"linux,initrd-end")==0x98000000+26*1024*1024);
        free(payload);
    }
    puts("Linux payload DTB: exact board/SoC declarations, stock-gate regression and malformed/conflicting identities passed");
    return 0;
}
