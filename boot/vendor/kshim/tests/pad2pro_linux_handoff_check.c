/* SPDX-License-Identifier: MIT */
/* Offline acceptance against real firmware FDT: no MMIO or device writes. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <device_info.h>
#include <dt.h>
#include <dt_handoff.h>
#include <dt_simplefb.h>

static void *read_blob(const char *path,size_t *bytes)
{
    FILE *f=fopen(path,"rb");assert(f && !fseek(f,0,SEEK_END));
    long n=ftell(f);assert(n>0 && !fseek(f,0,SEEK_SET));
    void *p=malloc((size_t)n);assert(p && fread(p,1,(size_t)n,f)==(size_t)n);fclose(f);
    *bytes=(size_t)n;assert(!dt_validate(p,*bytes));return p;
}
int main(int argc,char **argv)
{
    assert(argc==4);
    size_t nr,np;void *runtime=read_blob(argv[1],&nr),*payload=read_blob(argv[2],&np);
    void *rt_copy=malloc(nr),*pl_copy=malloc(np);assert(rt_copy && pl_copy);
    memcpy(rt_copy,runtime,nr);memcpy(pl_copy,payload,np);
    void *saved=calloc(1,DT_MEMORY_SNAPSHOT_BYTES),*out=calloc(1,256*1024),*overlay=calloc(1,DT_MEMORY_OVERLAY_BYTES);
    assert(saved && out && overlay);
    int rc=dt_memory_capture(runtime,nr,saved,DT_MEMORY_SNAPSHOT_BYTES);
    printf("capture=%d\n",rc);assert(!rc);
    rc=dt_memory_apply(saved,DT_MEMORY_SNAPSHOT_BYTES,payload,np,out,256*1024,overlay,DT_MEMORY_OVERLAY_BYTES);
    printf("memory_apply=%d\n",rc);assert(!rc);
    const kshim_framebuffer_config_t fb={.render_address=0xfc800000,.width=3392,.height=2400,
        .stride=13568,.buffer_size=32563200,.format=KSHIM_FB_FORMAT_ARGB8888,.bpp=32};
    rc=dt_simplefb_apply(out,256*1024,&fb);printf("simplefb=%d\n",rc);assert(!rc);
    struct device_info info;device_info_read(out,&info);
    assert(info.ram_known && info.dt_reported_ram_bytes==UINT64_C(16586620928));
    int chosen=fdt_path_offset(out,"/chosen"),fbnode=-1;
    fdt_for_each_subnode(fbnode,out,chosen)
        if(!fdt_node_check_compatible(out,fbnode,"simple-framebuffer"))break;
    assert(fbnode>=0);
    uint32_t value;assert(!dt_u32(out,fbnode,"width",&value) && value==3392);
    assert(!dt_u32(out,fbnode,"height",&value) && value==2400);
    assert(!dt_u32(out,fbnode,"stride",&value) && value==13568);
    int log=fdt_path_offset(out,"/reserved-memory/ramoops@880000000");struct dt_range region;
    assert(log>=0 && !dt_reg(out,log,0,&region));
    assert(region.base==UINT64_C(0x880000000) && region.size==0x240000);
    assert(!memcmp(runtime,rt_copy,nr) && !memcmp(payload,pl_copy,np));
    assert(!fdt_pack(out));FILE *f=fopen(argv[3],"wb");assert(f);
    size_t n=(size_t)fdt_totalsize(out);assert(fwrite(out,1,n,f)==n);fclose(f);
    printf("OPD2413 Linux handoff: RAM=%llu, real reservations, framebuffer, ramoops retained; inputs unchanged\n",
        (unsigned long long)info.dt_reported_ram_bytes);
    free(runtime);free(payload);free(rt_copy);free(pl_copy);free(saved);free(out);free(overlay);
    return 0;
}
