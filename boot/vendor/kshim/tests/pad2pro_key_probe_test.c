/* SPDX-License-Identifier: MIT */
#include <oneplus_pad2pro_key_probe.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned reads;
static uint32_t version;
static uint32_t read_version(void *context, uintptr_t address)
{ (void)context; assert(address == 0xc400000 && reads++ == 0); return version; }
static void no_write(void *context, uintptr_t address, uint32_t value)
{ (void)context; (void)address; (void)value; assert(0); }
static const struct CrIo io = {.read32 = read_version, .write32 = no_write};

static void reset_resources(struct kshim_resources *r, void *fdt)
{
    memset(r, 0, sizeof(*r));
    r->fdt = fdt;
    assert(!kshim_dt_spmi(fdt, r));
    r->mapping_count = 1;
    r->mappings[0] = (kshim_mmu_region_t){0xc400000, 0x3000,
        KSHIM_MMU_DEVICE, KSHIM_MMU_READ | KSHIM_MMU_WRITE};
    reads = 0;
}
static struct pad2pro_key_probe run(void *fdt, struct kshim_resources *r, int mmu)
{
    struct pad2pro_key_probe result;
    memset(&result, 0xff, sizeof(result));
    pad2pro_key_probe_run(fdt, r, mmu, &io, &result);
    return result;
}
struct input_mock { unsigned calls, fail_at; uint32_t pon, gpio; };
static int input_read(void *context, uint64_t address, uint32_t *value)
{
    struct input_mock *m = context;
    ++m->calls;
    if (m->calls == m->fail_at) return -1;
    if (address == QCOM_KEY_SPMI_RESOURCE(0, 0, 0, 0x1310)) *value = m->pon;
    else {
        assert(address == (QCOM_KEY_SPMI_RESOURCE(0, 0, 1, 0x8d10) | QCOM_KEY_PMIC_GPIO_FLAG));
        *value = m->gpio;
    }
    return 0;
}
static void input_resources(struct kshim_resources *r, void *fdt)
{
    reset_resources(r, fdt);
    r->mapping_count = 0;
    for (unsigned i = 0; i < SPMI_MEMORY_REGION_TYPE_MAX; ++i) {
        const SpmiMemoryRegion *s = &r->spmi[0].controller.Regions[i];
        if (s->Size) r->mappings[r->mapping_count++] = (kshim_mmu_region_t){
            s->BaseAddress, s->Size, KSHIM_MMU_DEVICE, KSHIM_MMU_READ | KSHIM_MMU_WRITE};
    }
}
static void input_tests(void *fdt, struct kshim_resources *r)
{
    QcomKeys keys;
    QcomKeyEvent event;
    struct pad2pro_key_input result;
    struct pad2pro_key_probe probe = {.status=0, .keys=3, .mmu=1, .reads=1,
        .version=0x70020000, .regions=0x1f};
    struct input_mock m = {.gpio=1};
    input_resources(r, fdt);
    pad2pro_key_input_prepare(fdt, r, 1, &probe, input_read, &m, &keys, &result);
    assert(!result.status && result.enabled && m.calls==2 && !result.errors);
    assert(result.pon_reads==1 && result.gpio_reads==1);
    assert(QcomKeysPoll(&keys, &event)==QCOM_KEYS_NO_EVENT);
    for (unsigned i=0;i<3;++i) {
        m.pon=i==0?0x40:(i==2?0x80:0); m.gpio=i==1?0:1;
        assert(QcomKeysPoll(&keys,&event)==QCOM_KEYS_NO_EVENT);
        assert(QcomKeysPoll(&keys,&event)==QCOM_KEYS_EVENT);
        assert(event.Pressed && event.Action==(i==0?QCOM_KEY_ACTION_UP:(i==1?QCOM_KEY_ACTION_DOWN:QCOM_KEY_ACTION_SELECT)));
        m.pon=0; m.gpio=1;
        assert(QcomKeysPoll(&keys,&event)==QCOM_KEYS_NO_EVENT);
        assert(QcomKeysPoll(&keys,&event)==QCOM_KEYS_NO_EVENT);
    }
    m.fail_at=m.calls+1;
    (void)QcomKeysPoll(&keys,&event);
    assert(result.status==-6 && result.errors==1);
    unsigned stopped=m.calls;
    for(unsigned i=0;i<3;++i)(void)QcomKeysPoll(&keys,&event);
    assert(m.calls==stopped);
    for(unsigned kind=0;kind<9;++kind){
        input_resources(r,fdt);m=(struct input_mock){.gpio=1};
        struct pad2pro_key_probe candidate=probe;
        if(kind==0)candidate.version=0x70000000;
        if(kind==1)candidate.status=-1;
        if(kind==2)r->mapping_count=1;
        if(kind==3)m.fail_at=1;
        if(kind==4)m.fail_at=2;
        if(kind==5)m.pon=0x40;
        if(kind==6)m.gpio=0;
        if(kind==7)m.pon=0x100;
        if(kind==8)m.gpio=2;
        pad2pro_key_input_prepare(fdt,r,1,&candidate,input_read,&m,&keys,&result);
        assert(result.status && !result.enabled);
        if(kind<3)assert(!m.calls);
        if(kind==3)assert(m.calls==1 && result.status==-3);
        if(kind==4)assert(m.calls==2 && result.status==-4);
        if(kind==5 || kind==6)assert(result.status==-5);
        unsigned before=m.calls;
        if(result.errors)assert(pad2pro_key_input_read(&result,QCOM_KEY_SPMI_RESOURCE(0,0,0,0x1310),&version));
        assert(m.calls==before);
        char report[81];assert(pad2pro_key_input_report(&result,report,sizeof(report))>0);
    }
    input_resources(r,fdt);m=(struct input_mock){.gpio=1};
    pad2pro_key_input_prepare(fdt,r,1,&probe,input_read,&m,&keys,&result);
    uint32_t value=0xdeadbeef;
    assert(pad2pro_key_input_read(&result,0,&value) && value==0xdeadbeef && m.calls==2);
    assert(result.errors==1 && result.status==-6);
    result.pon_reads=result.gpio_reads=result.errors=UINT32_MAX;
    char report[81];assert(pad2pro_key_input_report(&result,report,sizeof(report))>0);
    puts("OPD2413 input: two probes, three debounced actions, exact version/maps, fault latch and bounded reports");
}
int main(void)
{
    FILE *file = fopen(FIXTURE_PATH, "rb");
    assert(file && !fseek(file, 0, SEEK_END));
    long bytes = ftell(file);
    assert(bytes > 0 && !fseek(file, 0, SEEK_SET));
    size_t capacity = (size_t)bytes + 4096;
    void *original = malloc((size_t)bytes), *fdt = malloc(capacity);
    struct kshim_resources *r = calloc(1, sizeof(*r));
    assert(original && fdt && r && fread(original, 1, (size_t)bytes, file) == (size_t)bytes);
    fclose(file);
    assert(!fdt_open_into(original, fdt, (int)capacity));
    input_tests(fdt,r);
    for (unsigned i = 0; i < 4; ++i) {
        static const uint32_t raw[] = {0x70000000, 0x80000000, 0x80050000, 0xffffffff};
        reset_resources(r, fdt); version = raw[i];
        struct pad2pro_key_probe p = run(fdt, r, 1);
        assert(!p.status && p.keys == 3 && p.reads == 1 && reads == 1 && p.mmu == 1);
        assert(p.version == raw[i] && p.regions == 0x1f && !r->spmi[0].controller.Initialized);
        char report[81];
        assert(pad2pro_key_probe_report(&p, report, sizeof(report)) > 0 && strlen(report) <= 80);
        const char prefix[] = "kp1:rc=0:k=3:mmu=1:rd=1:v=";
        assert(!strncmp(report, prefix, sizeof(prefix) - 1));
        assert(pad2pro_key_probe_report(&p, report, 80) == -1);
    }
    for (unsigned kind = 0; kind < 12; ++kind) {
        reset_resources(r, fdt);
        switch (kind) {
        case 0: r->spmi_count = 2; break;
        case 1: r->spmi_status = -1; break;
        case 2: r->spmi[0].controller.ActiveEE = 1; break;
        case 3: r->spmi[0].controller.BusId = 1; break;
        case 4: r->spmi[0].controller.HasInterrupt = 1; break;
        case 5: r->spmi[0].controller.Initialized = 1; break;
        case 6: r->spmi[0].controller.Regions[0].Size -= 4; break;
        case 7: r->mapping_count = KSHIM_RESOURCE_MAX + 1; break;
        case 8: r->mapping_count = 0; break;
        case 9: r->mappings[0].type = KSHIM_MMU_NORMAL_WB; break;
        case 10: r->mappings[0].permissions = KSHIM_MMU_WRITE; break;
        case 11: r->mappings[0].base += 4; break;
        }
        struct pad2pro_key_probe p = run(fdt, r, 1);
        assert(p.status && !reads && !p.reads && !p.version);
    }
    reset_resources(r, fdt);
    assert(run(fdt, r, 0).status == -4 && !reads);
    struct pad2pro_key_probe p;
    pad2pro_key_probe_run(fdt, r, 1, NULL, &p);
    assert(p.status == -4 && !reads);
    pad2pro_key_probe_run(NULL, r, 1, &io, &p);
    assert(p.status == -1 && !reads);
    for (unsigned kind = 0; kind < 4; ++kind) {
        assert(!fdt_open_into(original, fdt, (int)capacity));
        int node;
        if (kind == 0) assert(!fdt_setprop_string(fdt, 0, "model", "other sun tablet"));
        else if (kind == 1) assert(!fdt_setprop_string(fdt, 0, "compatible", "qcom,sun"));
        else if (kind == 2) {
            node = fdt_path_offset(fdt, "/soc/gpio_keys/vol_down"); assert(node >= 0);
            assert(!fdt_setprop_u32(fdt, node, "linux,code", 115));
        } else {
            node = fdt_path_offset(fdt, "/soc/qcom,spmi@c42d000/qcom,pmk8550@0/pon_hlos@1300/resin");
            assert(node >= 0 && !fdt_setprop_string(fdt, node, "status", "disabled"));
        }
        reset_resources(r, fdt); p = run(fdt, r, 1);
        assert(p.status && !reads && !p.reads);
    }
    free(original); free(fdt); free(r);
    puts("OPD2413 key checkpoint: exact DT/resources, one version read, no PMIC requests or polling");
    return 0;
}
