/* SPDX-License-Identifier: GPL-3.0-only */
#include <boot_files_menu.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct kshim_boot_summary rows[48];
static struct kshim_boot_catalog catalog = {.entries = rows};
struct step {
    size_t count, initial, selected;
    uint32_t timeout;
    const char *label, *detail;
};
struct script { const struct step *steps; size_t count, cursor; int error; };
static int select_menu(void *opaque, const char *const *names,
    const char *const *descriptions, size_t count, size_t initial,
    uint32_t timeout, size_t *selected)
{
    struct script *script=opaque;
    assert(script->cursor < script->count);
    const struct step *step=&script->steps[script->cursor++];
    assert(count == step->count && initial == step->initial && timeout == step->timeout);
    for (size_t i=0; i<count; ++i) {
        const char *marks[]={"(current) ","(previous) "};
        for (size_t m=0; m<2; ++m) {
            /* A right-ellipsized row must retain its selector marker. */
            const char *mark=strstr(names[i],marks[m]);
            if (mark) {
                assert(mark == names[i]);
                assert(!strncmp(descriptions[i],marks[m],strlen(marks[m])));
            }
        }
    }
    *selected=step->selected == SIZE_MAX ? initial : step->selected;
    if (step->label) assert(strstr(names[*selected],step->label));
    if (step->detail) assert(strstr(descriptions[*selected],step->detail));
    if (*selected && !strncmp(names[0],"Return to systems",17) &&
        strcmp(names[*selected],"Next page") && strcmp(names[*selected],"Previous page")) {
        /* Equal releases must remain distinguishable in the primary row,
         * including UIs where the description is not visible. */
        assert(strchr(names[*selected],'[') && strchr(names[*selected],']'));
    }
    return script->error;
}
static void run(const char *default_entry, const struct step *steps, size_t count, size_t expected)
{
    strcpy(catalog.default_entry,default_entry);
    struct script script={steps,count,0,0}; size_t selected=0;
    assert(kshim_boot_choose(&catalog,select_menu,&script,&selected) == 0);
    assert(selected == expected && script.cursor == count);
}
int main(void)
{
    catalog.timeout_ms=8000; catalog.system_count=4; catalog.count=32;
    for (unsigned s=0; s<4; ++s) {
        snprintf(catalog.systems[s],64,"system%u",s);
        for (unsigned v=0; v<8; ++v) {
            unsigned i=s*8+v; struct kshim_boot_summary *e=&catalog.entries[i];
            e->system=s;
            snprintf(e->version,64,"kernel%u",v);
            snprintf(e->release,sizeof(e->release),"6.12.%u",v);
            snprintf(e->title,96,"Linux system %u",s);
            e->current=v == 0; e->previous=v == 1;
        }
    }
    const struct step last[]={{5,0,3,8000,"system2",NULL},{9,1,8,8000,"6.12.7","kernel7"}};
    run("android",last,2,23);
    const struct step previous[]={{5,2,SIZE_MAX,8000,"system1",NULL},{9,2,SIZE_MAX,8000,"(previous)","kernel1"}};
    run("system1/previous",previous,2,9);
    const struct step pinned[]={{5,3,SIZE_MAX,8000,"system2",NULL},{9,8,SIZE_MAX,8000,"6.12.7","kernel7"}};
    run("system2/kernel7",pinned,2,23);
    const struct step current[]={{5,4,SIZE_MAX,8000,"system3",NULL},{9,1,SIZE_MAX,8000,"(current)","kernel0"}};
    run("system3/current",current,2,24);
    const struct step back[]={{5,0,1,8000,NULL,NULL},{9,1,0,8000,"Return to systems",NULL},
                             {5,1,4,0,"system3",NULL},{9,1,7,8000,"6.12.6","kernel6"}};
    run("android",back,4,30);
    const struct step exit[]={{5,0,0,8000,"Return to main menu",NULL}};
    run("android",exit,1,SIZE_MAX);
    const struct step missing[]={{5,0,1,8000,NULL,NULL},{9,0,3,0,"6.12.2","kernel2"}};
    run("system0/missing",missing,2,2);
    strcpy(catalog.entries[2].release,catalog.entries[3].release);
    const struct step same_release[]={{5,0,1,8000,NULL,NULL},{9,1,3,8000,"6.12.3","kernel2"}};
    run("android",same_release,2,2);
    catalog.entries[0].error=KSHIM_STORAGE_NOT_FOUND;
    strcpy(catalog.entries[0].title,"manifest error");
    const struct step healthy[]={{5,0,1,8000,NULL,NULL},{9,1,4,8000,"6.12.3","kernel3"}};
    run("android",healthy,2,3);
    const struct step bad_selection[]={{5,0,99,8000,NULL,NULL}};
    struct script script={bad_selection,1,0,0}; size_t selected=0;
    assert(kshim_boot_choose(&catalog,select_menu,&script,&selected) == KSHIM_STORAGE_RANGE);
    assert(selected == SIZE_MAX);
    script.cursor=0; script.error=KSHIM_STORAGE_IO;
    assert(kshim_boot_choose(&catalog,select_menu,&script,&selected) == KSHIM_STORAGE_IO);
    assert(selected == SIZE_MAX);

    /* NixOS IDs and releases can fill the protocol fields. Exercise both
     * aliases and a broken current manifest without shortening the ID. */
    for (unsigned i=0; i<2; ++i) {
        struct kshim_boot_summary *e=&catalog.entries[i];
        memset(e->release,'r',sizeof(e->release)-1);
        e->release[sizeof(e->release)-1]='\0';
        memset(e->version,'v',sizeof(e->version)-1);
        e->version[0]='0'+i; e->version[sizeof(e->version)-1]='\0';
        memset(e->title,'t',sizeof(e->title)-1);
        e->title[sizeof(e->title)-1]='\0';
        e->error=0;
    }
    const struct step long_current[]={{5,1,SIZE_MAX,8000,NULL,NULL},
        {9,1,SIZE_MAX,8000,"(current) rrrrr","(current) ttttt"}};
    run("system0/current",long_current,2,0);
    const struct step long_previous[]={{5,1,SIZE_MAX,8000,NULL,NULL},
        {9,2,SIZE_MAX,8000,"(previous) rrrrr","(previous) ttttt"}};
    run("system0/previous",long_previous,2,1);
    catalog.entries[0].error=KSHIM_STORAGE_NOT_FOUND;
    const struct step broken_current[]={{5,1,SIZE_MAX,8000,NULL,NULL},
        {9,1,SIZE_MAX,8000,"(current) ttttt",catalog.entries[0].version}};
    run("system0/current",broken_current,2,0);
    for (unsigned v=8; v<24; ++v) {
        struct kshim_boot_summary *e=&rows[24+v];
        *e=rows[31];
        snprintf(e->version,sizeof(e->version),"kernel%u",v);
        snprintf(e->release,sizeof(e->release),"6.12.%u",v);
    }
    catalog.count=48;
    const struct step paged[]={{5,0,4,8000,NULL,NULL},
        {8,1,7,8000,"Next page",NULL},
        {9,0,8,0,"Next page",NULL},
        {9,0,7,0,"Previous page",NULL},
        {9,0,5,0,"6.12.10","kernel10"}};
    run("android",paged,5,34);
    const struct step pinned_page[]={{5,4,SIZE_MAX,8000,NULL,NULL},
        {8,6,SIZE_MAX,8000,"6.12.23","kernel23"}};
    run("system3/kernel23",pinned_page,2,47);
    puts("multi-kernel menu: paging, aliases, defaults, back and error isolation passed");
    return 0;
}
