/* SPDX-License-Identifier: MIT */
/* Synthetic register values: hardware layout constants come from OPD2413 DT. */
#include <oneplus_pad2pro_splash_snapshot.h>
#include <qcom_dt.h>
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "fixtures/oneplus-pad2pro-observed-splash.h"

struct mock { unsigned reads, pipe_mask, lm_mask; int mutation; bool multi, replay; };
static uint32_t mock_read(void *context, uintptr_t address)
{
    struct mock *m = context;
    assert(address >= 0xae00000 && address - 0xae00000 <= 0x93800 - 4 && !(address & 3));
    unsigned off = (unsigned)(address - 0xae00000), index = m->reads++;
    uint32_t value = 0;
    if (off == 0x160f4) value = 6;
    else if (off == 0x1612c) value = m->pipe_mask;
    else if (off == 0x16130) value = m->lm_mask;
    else {
        bool found = false;
        for (unsigned i = 0; i < 4; ++i) {
            unsigned base = 0x45000 + i * 0x1000;
            if (off >= base && off <= base + 0x224) {
                assert(m->lm_mask & (1u << i));
                unsigned delta = off - base;
                if (delta == 0) value = i & 1 ? 0x80000000 : 0;
                else if (delta == 4) value = 0x09600350;
                else {
                    assert(delta == 0x14 || (delta >= 0x44 && delta <= 0x224 && (delta - 0x44) % 0x30 == 0));
                    value = (delta == 0x74 || (m->multi && delta == 0x44)) ? 0xc040 + i : 0xc0c0;
                    if(m->replay) value=delta==0x134?observed_pad2pro_words[6+i*4]:0xc0c0;
                }
                found = true;
            }
            base = 0x5000 + i * 0x2000;
            if (off >= base && off <= base + 0x170) {
                static const unsigned valid[] = {0,8,12,16,20,36,48,52,56,112,0x170};
                bool valid_offset = false;
                for (unsigned j = 0; j < 11; ++j) valid_offset |= off - base == valid[j];
                assert(valid_offset && (m->pipe_mask & (1u << (16 + i))));
                value = 0x10000000 + off;
                if(m->replay) for(unsigned j=0;j<11;++j)
                    if(off-base==valid[j]) value=observed_pad2pro_words[19+i*11+j];
                found = true;
            }
        }
        assert(found);
    }
    if ((int)index == m->mutation) value ^= 1;
    return value;
}
static void no_write(void *context, uintptr_t address, uint32_t value)
{ (void)context; (void)address; (void)value; assert(0); }

static struct CrSplashResources resources(void)
{
    struct CrSplashResources r = {.base=0xae00000,.size=0x93800,
        .reserved_base=0xfc800000,.reserved_size=0x2b00000,
        .pipe_count=10,.ctl_count=6,.mixer_count=8,.stage_count=11,.lm_source_select=true};
    const uint32_t pipes[10]={0x5000,0x7000,0x9000,0xb000,0x25000,0x27000,0x29000,0x2b000,0x2d000,0x2f000};
    for (unsigned i=0;i<10;++i) { r.pipe[i]=pipes[i];r.pipe_id[i]=(uint8_t)i; }
    for (unsigned i=0;i<6;++i) r.ctl[i]=0x16000+i*0x1000;
    for (unsigned i=0;i<8;++i) { r.mixer[i]=0x45000+i*0x1000;r.mixer_id[i]=(uint8_t)i; }
    for (unsigned i=0;i<11;++i) r.stage[i]=0x40+i*0x30;
    return r;
}

static void observed_decode_tests(void)
{
    struct CrSplashResources r=resources();
    struct pad2pro_splash_snapshot s={.captured=true,.stable=true,.status=0};
    memcpy(s.words,observed_pad2pro_words,sizeof(s.words));
    struct CrSplash fb;
    assert(pad2pro_splash_decode(&r,&s,&fb)==0);
    assert(fb.address==0xfc800000 && fb.width==3392 && fb.height==2400 &&
           fb.stride==13568 && fb.size==32563200 && fb.format==CR_SPLASH_ARGB8888);
    static const struct {unsigned index;uint32_t value;} bad[]={
        {0,7},{1,0xf0001},{2,3},{7,0},{5,0x60002},{9,0x70001},{14,0x4140},
        {16,0x9600351},{19,0x9600351},{20,1},{33,0},{45,0xfc800004},
        {25,0x23600},{26,0x3010002},{27,0x80000010},{28,1},{29,1},{24,0x1003500},
        {24,13564},{4,0}};
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);++i){
        memcpy(s.words,observed_pad2pro_words,sizeof(s.words));
        s.words[bad[i].index]=bad[i].value;
        assert(pad2pro_splash_decode(&r,&s,&fb)!=0 && !fb.address && !fb.width && !fb.size);
    }
    memcpy(s.words,observed_pad2pro_words,sizeof(s.words));
    for(unsigned i=0;i<4;++i)s.words[23+i*11]=0xff000000;
    assert(pad2pro_splash_decode(&r,&s,&fb)!=0 && !fb.address);
    memcpy(s.words,observed_pad2pro_words,sizeof(s.words));s.stable=false;
    assert(pad2pro_splash_decode(&r,&s,&fb)==CR_BUS_AGAIN && !fb.address);

    FILE *file=fopen(FIXTURE_PATH,"rb");assert(file);
    assert(!fseek(file,0,SEEK_END));long n=ftell(file);assert(n>0);rewind(file);
    void *f=malloc((size_t)n+1024);assert(f && fread(f,1,(size_t)n,file)==(size_t)n);fclose(file);
    assert(!fdt_open_into(f,f,(int)n+1024));
    struct mock m={.pipe_mask=0xf0000,.lm_mask=0xf,.mutation=-1,.replay=true};
    const struct CrIo io={.context=&m,.read32=mock_read,.write32=no_write};
    kshim_framebuffer_config_t config;kshim_mmu_region_t mmio;
    assert(kshim_dt_splash(f,&io,&config,&mmio)==0);
    assert(config.width==3392 && config.height==2400 && config.stride==13568 &&
           config.render_address==0xfc800000 && config.bpp==32 &&
           config.format==KSHIM_FB_FORMAT_ARGB8888 && config.buffer_size==32563200);
    assert(mmio.base==0xae00000 && mmio.size==0x93800);
    static const char *const wrong_args[]={"quiet",
        "msm_drm.dsi_display0=qcom,mdss_dsi_panel_XN242_P_D_A0024_vid_extra:",
        "xmsm_drm.dsi_display0=qcom,mdss_dsi_panel_XN242_P_D_A0024_vid:",
        "msm_drm.dsi_display0=qcom,mdss_dsi_panel_XN242_P_D_A0024_vid: msm_drm.dsi_display0=other:"};
    for(unsigned i=0;i<sizeof(wrong_args)/sizeof(wrong_args[0]);++i){
        int chosen=fdt_path_offset(f,"/chosen");assert(chosen>=0);
        assert(!fdt_setprop_string(f,chosen,"bootargs",wrong_args[i]));
        m.reads=0;
        assert(kshim_dt_splash(f,&io,&config,&mmio)!=0 && !config.render_address);
        assert(m.reads==31); /* old reader only; OPD2413 fallback did not probe */
    }
    free(f);
}

int main(void)
{
    struct CrSplashResources r=resources();
    struct mock m={.pipe_mask=0xf0000,.lm_mask=0xf,.mutation=-1};
    const struct CrIo io={.context=&m,.read32=mock_read,.write32=no_write};
    assert(pad2pro_splash_snapshot_capture(&r,&io)==0 && m.reads==206);
    const struct pad2pro_splash_snapshot *s=pad2pro_splash_snapshot_get();
    assert(s->captured && s->stable && s->words[1]==0xf0000 && s->words[2]==0xf);
    assert(s->words[5]==0x20001 && s->words[6]==0xc040);
    assert(s->words[19]==0x10005000 && s->words[62]==0x1000b170);
    for (unsigned slot=0;slot<8;++slot) {
        char report[81];assert(pad2pro_splash_snapshot_report(slot,report,sizeof(report))==73);
        assert(strlen(report)==73 && report[5]==(char)('0'+slot) && report[7]=='1');
        for (unsigned i=0;i<8;++i) {
            char hex[9];memcpy(hex,report+9+i*8,8);hex[8]=0;
            unsigned idx=slot*8+i;
            assert(strtoul(hex,NULL,16)==(idx<63?s->words[idx]:0));
        }
    }
    /* A changed second snapshot is exported as unstable, never as validated. */
    m.reads=0;m.mutation=103;
    assert(pad2pro_splash_snapshot_capture(&r,&io)==CR_BUS_AGAIN);
    assert(s->captured && !s->stable);
    /* A non-last occupied selector changes while the compact record is
     * identical: stability must compare every read, not just exported words. */
    m=(struct mock){.pipe_mask=0xf0000,.lm_mask=0xf,.mutation=109,.multi=true};
    assert(pad2pro_splash_snapshot_capture(&r,&io)==CR_BUS_AGAIN);
    assert(s->captured && !s->stable && s->words[5]==0x20002);
    /* Do not read inactive VIG banks. */
    m=(struct mock){.pipe_mask=0x30000,.lm_mask=0xf,.mutation=-1};
    assert(pad2pro_splash_snapshot_capture(&r,&io)==0 && m.reads==162);
    for (unsigned i=41;i<63;++i) assert(s->words[i]==0);
    /* Unknown active sources refuse after the three CTL reads. */
    m=(struct mock){.pipe_mask=1,.lm_mask=0xf,.mutation=-1};
    assert(pad2pro_splash_snapshot_capture(&r,&io)==CR_BUS_UNSUPPORTED && m.reads==3);
    assert(!s->captured && !s->stable);
    char report[81];assert(pad2pro_splash_snapshot_report(0,report,sizeof(report))<0);
    /* Wrong resource tables refuse before MMIO. */
    for (unsigned which=0;which<5;++which) {
        struct CrSplashResources bad=r;
        if (which==0) bad.base++;
        if (which==1) bad.size--;
        if (which==2) bad.pipe[0]+=4;
        if (which==3) bad.mixer_id[0]=1;
        if (which==4) bad.stage[0]+=4;
        m.reads=0;
        assert(pad2pro_splash_snapshot_capture(&bad,&io)==CR_BUS_INVALID && !m.reads);
        assert(!s->captured);
    }
    puts("OPD2413 snapshot: bounded read-only capture, inactive-bank exclusion, stability and export passed");
    observed_decode_tests();
    puts("OPD2413 observed four-LM capture: decode, invalid-layout rejection and DT integration passed");
    return 0;
}
