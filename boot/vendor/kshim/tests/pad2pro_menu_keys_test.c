/* SPDX-License-Identifier: MIT */
static void key_frame_hook(void);
#define KSHIM_TEST_FRAME_HOOK key_frame_hook
#define main unused_shared_suite_main
#include "platform_menu_test.c"
#undef main
static unsigned reports, preparations;
static int prepare_status;
static uint64_t fault_at;
static void key_frame_hook(void)
{
    if(fault_at && h.now>=fault_at){UiPad2proInput.errors=1;UiPad2proInput.status=-6;}
}
void pad2pro_key_probe_run(const void *fdt,const struct kshim_resources *r,
    int mmu,const struct CrIo *io,struct pad2pro_key_probe *p)
{(void)fdt;(void)r;(void)io;assert(mmu==1);*p=(struct pad2pro_key_probe){.status=0};}
void pad2pro_key_input_prepare(const void *fdt,const struct kshim_resources *r,
    int mmu,const struct pad2pro_key_probe *p,QcomKeyRead32Status read,
    void *context,QcomKeys *keys,struct pad2pro_key_input *result)
{
    (void)fdt;(void)r;assert(mmu==1 && !p->status && keys==&Keys && !context);
    assert(read==kshim_qcom_key_read32_status && preparations++==0);
    *result=(struct pad2pro_key_input){.status=prepare_status,.enabled=prepare_status==0};
}
int pad2pro_key_input_report(const struct pad2pro_key_input *p,char *out,size_t capacity)
{return snprintf(out,capacity,"ki1:rc=%d:en=%u:e=%u",p->status,p->enabled?1u:0u,p->errors);}
int dt_probe_report(void *fdt,const char *v){(void)fdt;(void)v;return 0;}
int dt_probe_report_slot(void *fdt,unsigned slot,const char *v){(void)fdt;(void)slot;(void)v;return 0;}
int dt_diagnostic_report_slots(void *fdt,const char *probe,const char *s0)
{
    (void)fdt;assert(h.handoff_calls && !kshim_mmu_is_enabled());
    assert(!strncmp(probe,"r24:init=",9) && !strncmp(s0,"ki1:rc=",7));
    if(h.info_fixture.board==DEVICE_BOARD_ONEPLUS_PAD2PRO)
        assert(strstr(probe,":b=3:ram=16586620928"));
    assert(strlen(probe)<=80 && strlen(s0)<=80);++reports;return 0;
}
int kshim_settings_save(struct kshim_settings_session *s,const struct kshim_config_values *v)
{(void)s;(void)v;assert(0);return -1;}
static void reset(void)
{
    setup(false,2);h.info_mode=true;h.info_fixture=console_off_info(DEVICE_BOARD_UNKNOWN);
    reports=preparations=0;prepare_status=0;fault_at=0;
#if CONFIG_KSHIM_EXT4_BOOT
    UiPad2proInput=(struct pad2pro_key_input){0};
    h.resources.fdt=(const void *)(uintptr_t)boot_fdt();
#endif
}
static int select_menu(size_t *selected)
{
    int rc=kshim_platform_select_localized_info(boot_fdt(),h.names,h.descriptions,
        console_off_roles,&h.info_fixture,2,1,20,0,selected);
    assert(reports==1 && h.handoff_calls==1 && !h.console_read_calls);return rc;
}
int main(void)
{
    size_t selected=SIZE_MAX;reset();
    assert(!select_menu(&selected) && selected==1 && h.now>=20 && preparations==1);
    reset();ui_at(5,-1,true);ui_at(40,1,true);selected=SIZE_MAX;
    assert(!select_menu(&selected) && selected==1 && h.now>=40);
    reset();prepare_status=-3;selected=SIZE_MAX;
    assert(!select_menu(&selected) && selected==1 && h.now>=20 && !UiPad2proInput.enabled);
    reset();ui_at(5,-1,true);fault_at=10;selected=SIZE_MAX;
    assert(!select_menu(&selected) && selected==1 && h.now==10 && UiPad2proInput.status==-6);
    reset();h.ui_init_result=-1;selected=SIZE_MAX;
    assert(!select_menu(&selected) && selected==1 && !h.now);
    reset();h.map_result=-1;selected=SIZE_MAX;
    assert(!select_menu(&selected) && selected==1 && !preparations);
    reset();h.handoff_result=-1;selected=SIZE_MAX;
    assert(select_menu(&selected)==-2);
    reset();h.info_fixture.board=DEVICE_BOARD_ONEPLUS_PAD2PRO;
    h.info_fixture.soc=DEVICE_SOC_SM8750;h.info_fixture.ram_known=true;
    h.info_fixture.dt_reported_ram_bytes=UINT64_C(16586620928);
    snprintf(h.info_fixture.model,sizeof(h.info_fixture.model),"%s",
        "Qualcomm Technologies, Inc. Sun MTP,erhai-O DVT");
    h.info_fixture.model_known=true;
    ui_at(5,(int)info_home_row(),true);ui_at(10,(int)info_home_row(),true);ui_at(15,1,true);
    selected=SIZE_MAX;assert(!select_menu(&selected) && selected==1);
    assert(h.info_snap_count>=2);
    const char *summary=snap_desc(&h.info_snaps[1],info_home_row());
    assert(summary && strstr(summary,"OnePlus Pad 2 Pro (OPD2413)") && strstr(summary,"15818 MiB"));
#if CONFIG_KSHIM_EXT4_BOOT
    /* First-menu interaction has already initialized SPMI. Opening the file
     * menu and returning must keep its proven key backend and debounce state,
     * rather than retry the boot-entry "uninitialized controller" gate. */
    reset(); selected=SIZE_MAX;
    assert(!select_menu(&selected) && selected==1);
    h.resources.spmi[0].controller.Initialized=1;
    const kshim_menu_role_t file_roles[]={KSHIM_MENU_ROLE_UNKNOWN,KSHIM_MENU_ROLE_UNKNOWN};
    ui_at(30,1,true);
    assert(!kshim_platform_select_localized_info(boot_fdt(),h.names,h.descriptions,
        file_roles,&h.info_fixture,2,0,0,0,&selected) && selected==1);
    assert(UiPad2proInput.enabled && preparations==1 && reports==2 && h.handoff_calls==2);
    ui_at(45,0,true);
    assert(!kshim_platform_select_localized_info(boot_fdt(),h.names,h.descriptions,
        file_roles,&h.info_fixture,2,0,0,0,&selected) && selected==0);
    assert(UiPad2proInput.enabled && preparations==1 && reports==3 && h.handoff_calls==3);
    /* A latched transport error cannot be erased by changing menu sessions. */
    reset(); selected=SIZE_MAX;
    assert(!select_menu(&selected));
    UiPad2proInput.errors=1;UiPad2proInput.status=-6;
    assert(kshim_platform_select_localized_info(boot_fdt(),h.names,h.descriptions,
        file_roles,&h.info_fixture,2,0,0,0,&selected)==-1);
    assert(UiPad2proInput.errors==1 && preparations==1);
#endif
    puts("OPD2413 keys menu: gated backend, timeout, cancelled timeout, fault exit and cleanup failure passed");
    return 0;
}
