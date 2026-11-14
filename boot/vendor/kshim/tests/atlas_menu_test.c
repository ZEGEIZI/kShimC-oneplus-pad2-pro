/* Real LVGL, physical key events, firmware heap and repeated ext4 UI sessions. */
#define main inherited_star_suite
#include "tb323fu_menu_test.c"
#undef main

static size_t peak_heap_used;

/* Check the rendered object tree, including UNKNOWN external boot entries.
 * Every selectable row needs visible artwork and a separate text column. */
static void assert_row_icons(kshim_lvgl_t *ui)
{
    for (uint32_t i=0;i<lv_group_get_obj_count(ui->Group);++i) {
        lv_obj_t *row=lv_group_get_obj_by_index(ui->Group,i), *icon=NULL;
        unsigned images=0;
        for (uint32_t j=0;j<lv_obj_get_child_count(row);++j) {
            lv_obj_t *child=lv_obj_get_child(row,(int32_t)j);
            if (lv_obj_check_type(child,&lv_image_class)) {icon=child;images++;}
        }
        assert(images==1 && icon && !lv_obj_has_flag(icon,LV_OBJ_FLAG_HIDDEN));
        const lv_image_dsc_t *asset=lv_image_get_src(icon);
        assert(asset && asset->header.cf==LV_COLOR_FORMAT_A8);
        assert(asset->header.w==56 && asset->header.h==56 && asset->data_size==56*56);
        unsigned ink=0;
        for(uint32_t k=0;k<asset->data_size;++k) ink+=asset->data[k]!=0;
        assert(ink>0);
        lv_area_t bounds;lv_obj_get_coords(icon,&bounds);
        for (uint32_t j=0;j<lv_obj_get_child_count(row);++j) {
            lv_obj_t *child=lv_obj_get_child(row,(int32_t)j);
            if (!lv_obj_check_type(child,&lv_label_class)) continue;
            lv_area_t text;lv_obj_get_coords(child,&text);
            assert(bounds.x2<text.x1 || text.x2<bounds.x1 ||
                   bounds.y2<text.y1 || text.y2<bounds.y1);
        }
    }
}

static void snapshot(const char *directory, const char *name, kshim_framebuffer_t *fb)
{
    if (!directory) return;
    char path[1024];
    snprintf(path,sizeof(path),"%s/%s.ppm",directory,name);
    FILE *out=fopen(path,"wb"); assert(out);
    lv_refr_now(NULL);
    fprintf(out,"P6\n%u %u\n255\n",fb->width,fb->height);
    for (size_t i=0;i<(size_t)fb->width*fb->height;++i) {
        uint32_t p=((uint32_t *)(uintptr_t)fb->render_address)[i];
        unsigned char rgb[]={p>>16,p>>8,p}; assert(fwrite(rgb,3,1,out)==1);
    }
    assert(!fclose(out));
}
static void page(kshim_lvgl_t *ui, unsigned id, const char *const *names,
    const char *const *desc, const kshim_menu_role_t *roles, size_t n, size_t initial)
{
    kshim_lvgl_set_page(ui,id);
    assert(!kshim_lvgl_set_entries_described(ui,names,desc,NULL,n,initial));
    kshim_lvgl_set_entry_roles(ui,roles,n);
    Advance(ui,64);
    assert(lv_group_get_obj_count(ui->Group)>0);
    assert_row_icons(ui);
    lv_mem_monitor_t monitor;lv_mem_monitor(&monitor);
    size_t used=monitor.total_size-monitor.free_size;
    if(used>peak_heap_used) peak_heap_used=used;
    assert(monitor.free_size>32768);
}
int main(int argc,char **argv)
{
    const char *out=argc>1?argv[1]:NULL;
    const char *names[]={"Android","Linux (ext4 /boot)","Advanced","Settings","Device info","Restart","Power off"};
    kshim_menu_role_t roles[]={KSHIM_MENU_ROLE_ANDROID,KSHIM_MENU_ROLE_UNKNOWN,
        KSHIM_MENU_ROLE_ADVANCED,KSHIM_MENU_ROLE_SETTINGS,KSHIM_MENU_ROLE_DEVICE_INFO,
        KSHIM_MENU_ROLE_RESTART,KSHIM_MENU_ROLE_OFF};
    for (unsigned session=0;session<3;++session) {
        kshim_lvgl_t ui; kshim_framebuffer_t fb; uint32_t *pixels;
        QcomKeyDescriptor descriptors[3]; QcomKeys keys;
        FixtureInitSize(&ui,&fb,&pixels,descriptors,&keys,3392,2400);
        assert(LV_MEM_SIZE==1024U*1024U);
        assert(CONFIG_KSHIM_LVGL_BUFFER_BYTES==3392U*4U*32U);
        kshim_menu_set_language(KSHIM_MENU_LANG_EN);
        kshim_lvgl_set_environment(&ui,"B","Android",NULL);
        page(&ui,0,names,NULL,roles,7,1);
        assert(lv_group_get_obj_count(ui.Group)==7);
        kshim_lvgl_set_countdown(&ui,8000); Advance(&ui,32);
        if (!session) snapshot(out,"main-en",&fb);
        PressKey(&ui,2); assert(kshim_lvgl_take_index(&ui)==1);
        kshim_lvgl_cancel_countdown(&ui);
        assert(ui.CountdownCancelled && !ui.CountdownEnabled);
        const char *langs[]={"简体中文","English","Back"};
        const char *lang_desc[]={"Use Simplified Chinese","Use English","Return to settings"};
        const kshim_menu_role_t lr[]={KSHIM_MENU_ROLE_LANG_ZH,KSHIM_MENU_ROLE_LANG_EN,KSHIM_MENU_ROLE_BACK};
        page(&ui,2,langs,lang_desc,lr,3,1);
        PressKey(&ui,2); assert(kshim_lvgl_take_index(&ui)==1);
        if (!session) snapshot(out,"language-en",&fb);
        const char *delays[]={"Do not auto-boot","3 s","5 s","8 s","10 s","15 s","30 s","Back"};
        kshim_menu_role_t dr[8]; for(unsigned i=0;i<8;++i) dr[i]=i==7?KSHIM_MENU_ROLE_BACK:KSHIM_MENU_ROLE_SETTINGS;
        page(&ui,7,delays,NULL,dr,8,6); PressKey(&ui,2); assert(kshim_lvgl_take_index(&ui)==6);
        if (!session) snapshot(out,"delay-en",&fb);
        const char *settings[]={"Language","Boot delay: 30 s","Back"};
        const kshim_menu_role_t sr[]={KSHIM_MENU_ROLE_LANGUAGE,KSHIM_MENU_ROLE_SETTINGS,KSHIM_MENU_ROLE_BACK};
        page(&ui,4,settings,NULL,sr,3,0); if(!session)snapshot(out,"settings-en",&fb);
        const char *advanced[]={"Fastboot","Recovery","9008","Back"};
        const kshim_menu_role_t ar[]={KSHIM_MENU_ROLE_FASTBOOT,KSHIM_MENU_ROLE_RECOVERY,KSHIM_MENU_ROLE_EDL,KSHIM_MENU_ROLE_BACK};
        page(&ui,1,advanced,NULL,ar,4,0); if(!session)snapshot(out,"advanced-en",&fb);
        const char *values[]={"OnePlus Pad 2 Pro (OPD2413)","SM8750","OnePlus Pad 2 Pro","oneplus,opd2413\nqcom,sm8750","15818 MiB","3392x2400 stride 13568","pad2pro-atlas-v15"};
        kshim_lvgl_set_info_values(&ui,values,7);
        const char *info[]={"Back"}; const kshim_menu_role_t ir[]={KSHIM_MENU_ROLE_BACK};
        page(&ui,3,info,NULL,ir,1,0);
        if(!session)snapshot(out,"info-en",&fb);
        PressKey(&ui,2); assert(kshim_lvgl_take_index(&ui)==0);
        const char *systems[]={"Return to main menu","ArmadaOS","Mainline Linux"};
        const kshim_menu_role_t sys_roles[]={KSHIM_MENU_ROLE_BACK,KSHIM_MENU_ROLE_UNKNOWN,KSHIM_MENU_ROLE_UNKNOWN};
        page(&ui,8,systems,NULL,sys_roles,3,1);
        if(!session)snapshot(out,"systems-en",&fb);
        char labels[9][160]; const char *versions[9],*desc[9]; kshim_menu_role_t vr[9];
        for(unsigned i=0;i<9;++i) {
            snprintf(labels[i],sizeof(labels[i]),"7.2.6-opd2413-full-system03 [kernel-%u-20261110]",i);
            versions[i]=labels[i];desc[i]="Independent boot entry";vr[i]=KSHIM_MENU_ROLE_UNKNOWN;
        }
        versions[0]="Return to systems"; vr[0]=KSHIM_MENU_ROLE_BACK;
        page(&ui,8,versions,desc,vr,9,8);
        assert(lv_group_get_obj_count(ui.Group)==9);
        for(unsigned i=0;i<9;++i) {
            lv_group_focus_obj(lv_group_get_obj_by_index(ui.Group,i)); Advance(&ui,32);
            PressKey(&ui,2); assert(kshim_lvgl_take_index(&ui)==(int)i);
        }
        if(!session)snapshot(out,"kernels-en",&fb);
        kshim_menu_set_language(KSHIM_MENU_LANG_ZH_CN);
        page(&ui,0,names,NULL,roles,7,0);
        if(!session)snapshot(out,"main-zh",&fb);
        /* Exercise additional Chinese glyphs at all three Atlas font sizes,
         * while switching pages with the same live font caches. */
        const char *zh_settings[]={"语言","开机延迟","返回"};
        const char *zh_details[]={"选择菜单显示语言","设置自动启动前的等待时间","返回上级菜单"};
        page(&ui,4,zh_settings,zh_details,sr,3,0);
        if(!session)snapshot(out,"settings-zh",&fb);
        page(&ui,2,langs,lang_desc,lr,3,0);
        if(!session)snapshot(out,"language-zh",&fb);
        page(&ui,7,delays,NULL,dr,8,6);
        if(!session)snapshot(out,"delay-zh",&fb);
        page(&ui,1,advanced,NULL,ar,4,0);
        page(&ui,3,info,NULL,ir,1,0);
        lv_mem_monitor_t monitor;lv_mem_monitor(&monitor);assert(monitor.free_size>32768);
        FixtureDeinit(&ui,pixels);
    }
    printf("Atlas peak sampled heap usage: %zu / %u bytes\n",peak_heap_used,(unsigned)LV_MEM_SIZE);
    puts("Atlas: all selectable rows have icons without text overlap; pages, English/Chinese, nine kernel rows, key mapping, countdown and three UI lifecycles passed");
}
