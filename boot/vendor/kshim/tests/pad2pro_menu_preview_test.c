/* SPDX-License-Identifier: MIT */
/* Reuse the real platform loop and its scripted UI/peripheral harness. */
#define main unused_shared_suite_main
#include "platform_menu_test.c"
#undef main
static unsigned preview_reports;
#if CONFIG_KSHIM_PAD2PRO_KEY_PROBE
static unsigned probe_calls;
static int probe_status;
void pad2pro_key_probe_run(const void *fdt, const struct kshim_resources *r,
    int mmu, const struct CrIo *io, struct pad2pro_key_probe *result)
{
    (void)fdt; (void)r; (void)io;
    assert(mmu == 1 && !h.handoff_calls && probe_calls++ == 0);
    *result = (struct pad2pro_key_probe){.status = probe_status};
}
int pad2pro_key_probe_report(const struct pad2pro_key_probe *result, char *out, size_t capacity)
{ return snprintf(out, capacity, "kp1:rc=%d", result->status); }
#endif
int dt_probe_report(void *fdt, const char *value) { (void)fdt; (void)value; return 0; }
int dt_probe_report_slot(void *fdt, unsigned slot, const char *value)
{ (void)fdt; (void)slot; (void)value; return 0; }
int dt_diagnostic_report_slots(void *fdt,const char *probe,const char *s0)
{
    (void)fdt;assert(h.handoff_calls && !kshim_mmu_is_enabled());
    assert(!strncmp(probe,"r24:init=",9));
#if CONFIG_KSHIM_PAD2PRO_KEY_PROBE
    assert(!strncmp(s0,"kp1:rc=",7));
#else
    assert(!strncmp(s0,"r24:fb=",7));
#endif
    assert(strlen(probe)<=80 && strlen(s0)<=80);++preview_reports;return 0;
}
int kshim_settings_save(struct kshim_settings_session *s,const struct kshim_config_values *v)
{ (void)s;(void)v;assert(0);return -1; }

static int run_preview(size_t *selected)
{
    preview_reports=0;
#if CONFIG_KSHIM_PAD2PRO_KEY_PROBE
    probe_calls=0;
#endif
    int rc=kshim_platform_select_localized_info(boot_fdt(),h.names,h.descriptions,
        console_off_roles,&h.info_fixture,2,1,20,0,selected);
    assert(preview_reports==1);return rc;
}
int main(void)
{
    setup(false,2);h.info_mode=true;h.info_fixture=console_off_info(DEVICE_BOARD_UNKNOWN);
    size_t selected=SIZE_MAX;
    assert(!run_preview(&selected) && selected==1 && h.frames>0 && h.now>=20);
    assert(!h.key_poll_calls && !h.console_read_calls && h.handoff_calls==1);
#if CONFIG_KSHIM_PAD2PRO_KEY_PROBE
    assert(probe_calls==1);
    setup(false,2);h.info_mode=true;h.info_fixture=console_off_info(DEVICE_BOARD_UNKNOWN);
    probe_status=-4;selected=SIZE_MAX;
    assert(!run_preview(&selected) && selected==1 && h.frames>0 && probe_calls==1);
    assert(!h.key_poll_calls && !h.console_read_calls);
    probe_status=0;
#endif
    for(unsigned kind=0;kind<3;++kind){
        arm_initial_failure(kind);h.info_fixture=console_off_info(DEVICE_BOARD_UNKNOWN);
        selected=SIZE_MAX;
        assert(!run_preview(&selected) && selected==1 && !h.frames && !h.now);
        assert(!h.key_poll_calls && !h.console_read_calls && h.handoff_calls==1);
    }
    setup(false,2);h.info_mode=true;h.info_fixture=console_off_info(DEVICE_BOARD_UNKNOWN);
    h.map_result=-1;selected=SIZE_MAX;
    assert(!run_preview(&selected) && selected==1 && !h.frames && !h.fb_calls);
    assert(!h.key_poll_calls && !h.console_read_calls);
    setup(true,2);h.info_mode=true;h.info_fixture=console_off_info(DEVICE_BOARD_UNKNOWN);
    h.handoff_result=-1;selected=SIZE_MAX;
    assert(run_preview(&selected)==-2 && selected==SIZE_MAX);
    assert(!h.key_poll_calls && !h.console_read_calls);
    puts("OPD2413 preview: no key polling, timeout, UI/map failure fallback and cleanup failure passed");
    return 0;
}
