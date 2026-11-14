/* SPDX-License-Identifier: GPL-3.0-only */
#include <boot_files_menu.h>
#include <stdio.h>
#include <string.h>

static int default_matches(const struct kshim_boot_catalog *catalog, unsigned i)
{
    const struct kshim_boot_summary *e = &catalog->entries[i];
    char key[144];
    snprintf(key,sizeof(key),"%s/%s",catalog->systems[e->system],e->version);
    /* current/previous are selector aliases, even when a version ID uses one
     * of these words. Explicit version IDs otherwise select a pinned kernel. */
    const char *selector = strchr(catalog->default_entry,'/');
    if (!selector) return 0;
    if (!strcmp(selector+1,"current") || !strcmp(selector+1,"previous")) {
        int match = !strcmp(selector+1,"current") ? e->current : e->previous;
        snprintf(key,sizeof(key),"%s/%s",catalog->systems[e->system],selector+1);
        return match && !strcmp(key,catalog->default_entry);
    }
    return !strcmp(key,catalog->default_entry);
}

int kshim_boot_choose(const struct kshim_boot_catalog *catalog,
    kshim_boot_menu_select_fn select, void *context, size_t *entry)
{
    if (!catalog || !select || !entry || !catalog->system_count ||
        catalog->system_count > KSHIM_BOOT_SYSTEMS_MAX)
        return KSHIM_STORAGE_ARG;
    *entry = SIZE_MAX;
    const char *names[KSHIM_BOOT_MENU_ROWS], *descriptions[KSHIM_BOOT_MENU_ROWS];
    char labels[KSHIM_BOOT_MENU_ROWS][176];
    char details[KSHIM_BOOT_MENU_ROWS][192];
    unsigned counts[KSHIM_BOOT_SYSTEMS_MAX] = {0};
    unsigned starts[KSHIM_BOOT_SYSTEMS_MAX] = {0};
    for (unsigned i = 0; i < catalog->count; ++i) {
        unsigned system = catalog->entries[i].system;
        if (system >= catalog->system_count) return KSHIM_STORAGE_ARG;
        if (!counts[system]) starts[system] = i;
        ++counts[system];
    }
    size_t system_initial = 0;
    uint32_t system_timeout = catalog->timeout_ms;
    for (unsigned i = 0; i < catalog->count; ++i) {
        if (!default_matches(catalog,i)) continue;
        system_initial = catalog->entries[i].system+1;
    }
    for (;;) {
        names[0] = "Return to main menu";
        descriptions[0] = "Choose a built-in boot entry there";
        for (unsigned s = 0; s < catalog->system_count; ++s) {
            names[s+1] = catalog->systems[s];
            snprintf(details[s+1],sizeof(details[0]),"Choose a kernel (%u entries)",counts[s]);
            descriptions[s+1] = details[s+1];
        }
        size_t selected = 0;
        int rc = select(context,names,descriptions,catalog->system_count+1,
                        system_initial,system_timeout,&selected);
        if (rc) return rc;
        if (selected > catalog->system_count) return KSHIM_STORAGE_RANGE;
        if (!selected) return 0;
        unsigned system = (unsigned)selected-1;
        system_initial = selected;
        system_timeout = 0; /* Back never starts a loop of countdowns. */

        unsigned total = counts[system], first = starts[system];
        unsigned per_page = total < KSHIM_BOOT_MENU_ROWS ?
                            KSHIM_BOOT_MENU_ROWS-1 : KSHIM_BOOT_MENU_ROWS-3;
        unsigned preferred = total;
        int has_system_default = 0;
        for (unsigned j = 0; j < total; ++j) {
            unsigned i = first+j;
            if (catalog->entries[i].current && !has_system_default) preferred = j;
            if (default_matches(catalog,i)) { preferred = j; has_system_default = 1; }
        }
        /* An explicit default that disappeared must not auto-boot a peer. */
        const char *slash = strchr(catalog->default_entry,'/');
        if (slash && (size_t)(slash-catalog->default_entry) == strlen(catalog->systems[system]) &&
            !memcmp(catalog->default_entry,catalog->systems[system],(size_t)(slash-catalog->default_entry)) &&
            !has_system_default) preferred = total;

        unsigned offset = preferred < total ? preferred/per_page*per_page : 0;
        uint32_t timeout = preferred < total ? catalog->timeout_ms : 0;
        for (;;) {
            names[0] = "Return to systems";
            descriptions[0] = "Choose another Linux system";
            size_t count = 1, initial = 0;
            while (count <= per_page && offset+count-1 < total) {
                unsigned j = offset+count-1;
                const struct kshim_boot_summary *e = &catalog->entries[first+j];
                /* Keep selectors visible when LVGL ellipsizes long labels. */
                const char *mark = e->current ? "(current) " :
                                   e->previous ? "(previous) " : "";
                if (e->error)
                    snprintf(labels[count],sizeof(labels[0]),"%s%.90s [%.63s]",mark,e->title,e->version);
                else
                    snprintf(labels[count],sizeof(labels[0]),"%s%.63s [%.63s]",mark,e->release,e->version);
                snprintf(details[count],sizeof(details[0]),"%s%.95s | %.63s",mark,e->title,e->version);
                names[count] = labels[count];
                descriptions[count] = details[count];
                if (j == preferred) initial = count;
                ++count;
            }
            size_t end = count, previous = SIZE_MAX, next = SIZE_MAX;
            if (offset) {
                previous = count;
                names[count] = "Previous page";
                descriptions[count++] = "Show earlier kernels in menu order";
            }
            if (offset+end-1 < total) {
                next = count;
                names[count] = "Next page";
                descriptions[count++] = "Show later kernels in menu order";
            }
            selected = 0;
            rc = select(context,names,descriptions,count,initial,timeout,&selected);
            if (rc) return rc;
            if (selected >= count) return KSHIM_STORAGE_RANGE;
            if (!selected) break;
            if (selected < end) {
                *entry = first+offset+selected-1;
                return 0;
            }
            if (selected == previous) offset -= per_page;
            if (selected == next) offset += per_page;
            timeout = 0;
        }
    }
}
