/* SPDX-License-Identifier: GPL-3.0-only */
#include <boot_files_memory.h>
#include <ext4_boot.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
static void le64(uint8_t *p,uint64_t v){for(unsigned i=0;i<8;i++)p[i]=v>>(8*i);}
int main(void)
{
    struct kshim_boot_memory m={.ram={{0x80000000,0x40000000}},.ram_count=1};
    uint64_t address;
    assert(!kshim_boot_memory_reserve(&m,0x80000000,0x800000));
    assert(!kshim_boot_memory_reserve(&m,0x81000000,0x100000));
    assert(!kshim_boot_memory_alloc(&m,0x2000000,0x200000,0x80000,&address));
    assert(address==0x81280000);
    uint64_t kernel=address;
    assert(!kshim_boot_memory_alloc(&m,0x300000,65536,0,&address));
    assert(address>=0x80800000 && address+0x300000<=0x81000000);
    assert(address+0x300000<=kernel || address>=kernel+0x2000000);
    assert(kshim_boot_memory_reserve(&m,UINT64_MAX-1,3));
    assert(kshim_boot_memory_alloc(&m,1,3,0,&address));
    assert(kshim_boot_memory_alloc(&m,1,65536,65536,&address));
    assert(kshim_boot_memory_alloc(&m,0x40000000,0x200000,0,&address));
    uint8_t h[64]={0};memcpy(h+56,"ARM\x64",4);le64(h+8,0x80000);le64(h+16,0x2000000);le64(h+24,10);
    uint64_t size,offset;
    assert(!kshim_boot_image_header(h,0x1000000,&size,&offset));
    assert(size==0x2000000 && offset==0x80000);
    le64(h+16,0);assert(kshim_boot_image_header(h,4096,&size,&offset));
    le64(h+16,0x2000000);le64(h+8,0x200000);assert(kshim_boot_image_header(h,4096,&size,&offset));
    le64(h+8,0x80000);le64(h+24,11);assert(kshim_boot_image_header(h,4096,&size,&offset));
    puts("memory placement and ARM64 header checks passed");
}
