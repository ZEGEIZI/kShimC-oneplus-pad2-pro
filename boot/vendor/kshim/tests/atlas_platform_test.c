/* Real platform page builder/actions, with existing scripted hardware adapters. */
#define main inherited_platform_suite
#include "platform_menu_test.c"
#undef main
void kshim_lvgl_cancel_countdown(kshim_lvgl_t *context)
{ kshim_lvgl_set_countdown(context,0); }
void kshim_lvgl_set_page(kshim_lvgl_t *c,uint8_t p){c->UiPage=p;}
void kshim_lvgl_set_environment(kshim_lvgl_t *c,const char *s,const char *d,const char *l)
{c->UiEnvSlot=s;c->UiEnvDefault=d;c->UiEnvLast=l;}
void kshim_lvgl_set_info_values(kshim_lvgl_t *c,const char *const *v,size_t n)
{c->UiInfoValues=v;c->UiInfoCount=n;}
int fdt_path_offset(const void *fdt,const char *path){(void)fdt;(void)path;return -1;}
const void *fdt_getprop(const void *fdt,int node,const char *name,int *len)
{(void)fdt;(void)node;(void)name;*len=-1;return NULL;}
int main(void)
{
    setup(false,2);
    struct device_info info=settings_info(DEVICE_BOARD_ONEPLUS_PAD2PRO);
    const char *names[]={"Android","Linux (ext4 /boot)"};
    kshim_menu_role_t roles[]={KSHIM_MENU_ROLE_ANDROID,KSHIM_MENU_ROLE_UNKNOWN};
    enum device_board boards[]={DEVICE_BOARD_UNKNOWN,DEVICE_BOARD_ONEPLUS_PAD2PRO};
    struct menu_selection menu={.fdt=(void *)(uintptr_t)boot_fdt(),.timeout=8000};
    assert(!menu_build(&menu,names,NULL,roles,&info,boards,2,0,0,1,1,1));
    assert(menu.pages[0].count==7 && menu.default_ok && menu.boot_delay_ms==8000);
    assert(menu.pages[0].actions[0]==MENU_PAYLOAD && menu.pages[0].payloads[0]==0);
    assert(menu.pages[0].actions[1]==MENU_PAYLOAD && menu.pages[0].payloads[1]==1);
    const char *failure=NULL;size_t selected=SIZE_MAX;
    assert(menu_activate(&menu,menu.settings_row,&selected,&failure)==2);
    assert(menu.page==MENU_PAGE_SETTINGS && menu.pages[menu.page].count==3);
    assert(menu_activate(&menu,menu.delay_entry_row,&selected,&failure)==2);
    assert(menu.page==MENU_PAGE_DELAY && menu.pages[menu.page].initial==3);
    assert(menu_activate(&menu,6,&selected,&failure)==2);
    assert(menu.page==MENU_PAGE_SETTINGS && menu.boot_delay_ms==30000 && !menu.timeout);
    assert(menu_activate(&menu,menu.language_entry_row,&selected,&failure)==2);
    assert(menu.page==MENU_PAGE_LANGUAGE);
    assert(menu_activate(&menu,1,&selected,&failure)==2);
    assert(kshim_menu_get_language()==KSHIM_MENU_LANG_EN && menu.boot_delay_ms==30000);
    assert(menu_activate(&menu,2,&selected,&failure)==2);
    assert(menu.page==MENU_PAGE_MAIN && !menu.timeout);
    assert(menu_activate(&menu,1,&selected,&failure)==1 && selected==1);
    /* Generic menus map each row verbatim, even with advanced/power compiled in. */
    const char *versions[]={"Return","kernel-a","kernel-b"};
    struct menu_selection sub={.fdt=menu.fdt,.timeout=0};
    assert(!menu_build(&sub,versions,NULL,NULL,&info,NULL,3,2,0,1,1,0));
    assert(sub.pages[0].count==3 && sub.pages[0].initial==2);
    assert(menu_activate(&sub,2,&selected,&failure)==1 && selected==2);
    puts("Atlas platform: real targets, no synthetic device rows, delay/language/back and ext4 row mapping passed");
}
