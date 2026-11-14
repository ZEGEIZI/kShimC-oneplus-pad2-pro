/* SPDX-License-Identifier: MIT */
/* Offline DT parsing only; the register reader below never accesses hardware. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <device_info.h>
#include <qcom_dt.h>
#include <qcom_keys_fdt.h>

struct mock_display { unsigned reads; struct dt_range regs; };
static uint32_t empty_display(void *context, uintptr_t address)
{
    struct mock_display *m = context;
    assert(address >= m->regs.base && address - m->regs.base <= m->regs.size - 4);
    assert(!(address & 3));
    ++m->reads;
    return 0; /* No active scanout: discovery must fail instead of guessing. */
}

int main(int argc, char **argv)
{
    const char *path = argc == 3 && !strcmp(argv[1], "--hardware-dtb") ? argv[2] : FIXTURE_PATH;
    assert(argc == 1 || (argc == 3 && !strcmp(argv[1], "--hardware-dtb")));
    FILE *file = fopen(path, "rb");
    assert(file && !fseek(file, 0, SEEK_END));
    long size = ftell(file);
    assert(size > 0 && size < 16 * 1024 * 1024 && !fseek(file, 0, SEEK_SET));
    size_t capacity = (size_t)size + 4096;
    void *f = calloc(1, capacity), *snapshot = malloc((size_t)size);
    assert(f && snapshot && fread(f, 1, (size_t)size, file) == (size_t)size);
    fclose(file);
    memcpy(snapshot, f, (size_t)size);
    assert(!dt_validate(f, (size_t)size));
    struct device_info info;
    device_info_read(f, &info);
    assert(info.soc == DEVICE_SOC_SM8750);
    /* This exact stock model + unique panel override identifies OPD2413;
     * it must never enable Lenovo-specific storage/touch work. */
    assert(info.board == DEVICE_BOARD_ONEPLUS_PAD2PRO);
    if (argc == 3) {
        assert(info.ram_known && info.dt_reported_ram_bytes == UINT64_C(16586620928));
        printf("OPD2413 real FDT: board=%u RAM=%llu bytes (%llu MiB)\n",
            (unsigned)info.board, (unsigned long long)info.dt_reported_ram_bytes,
            (unsigned long long)(info.dt_reported_ram_bytes / 1048576));
    }
    struct kshim_resources *r = calloc(1, sizeof(*r));
    assert(r && !kshim_dt_spmi(f, r) && r->spmi_count == 1);
    assert(r->spmi[0].controller.Regions[SPMI_MEMORY_REGION_TYPE_CORE].BaseAddress == 0xc400000);
    assert(r->spmi[0].controller.Regions[SPMI_MEMORY_REGION_TYPE_OBSERVER].BaseAddress == 0xc440000);
    QcomKeyDescriptor keys[QCOM_KEYS_MAX];
    size_t count = 0;
    assert(!QcomKeysBuildFromDeviceTree(f, keys, QCOM_KEYS_MAX, &count) && count == 3);
    unsigned actions = 0;
    for (size_t i = 0; i < count; ++i) {
        QcomKeyDescriptor *k = &keys[i];
        assert(QCOM_KEY_IS_SPMI_TOKEN(k->Base));
        assert(QCOM_KEY_SPMI_TOKEN_CONTROLLER(k->Base) == 0);
        assert(QCOM_KEY_SPMI_TOKEN_BUS(k->Base) == 0);
        if (k->Code == 116 || k->Code == 115) {
            assert(QCOM_KEY_SPMI_TOKEN_SID(k->Base) == 0);
            assert(QCOM_KEY_SPMI_TOKEN_ADDRESS(k->Base) == 0x1300);
            assert(k->RegisterOffset == 0x10);
            assert(k->Mask == (k->Code == 116 ? 128 : 64));
            assert(k->Action == (k->Code == 116 ? QCOM_KEY_ACTION_SELECT : QCOM_KEY_ACTION_UP));
            actions |= k->Code == 116 ? 1 : 2;
        } else {
            assert(k->Code == 114 && k->Action == QCOM_KEY_ACTION_DOWN);
            assert(QCOM_KEY_SPMI_TOKEN_SID(k->Base) == 1);
            assert(QCOM_KEY_SPMI_TOKEN_ADDRESS(k->Base) == 0x8d10);
            assert((k->Base & QCOM_KEY_PMIC_GPIO_FLAG) && k->RegisterOffset == 0);
            assert(k->Mask == 1 && k->ActiveLow == 1);
            actions |= 4;
        }
    }
    assert(actions == 7);
    struct dt_range reservation;
    assert(!kshim_dt_splash_reservation(f, &reservation, NULL));
    assert(reservation.base == 0xfc800000 && reservation.size == 0x2b00000);
    int sde = fdt_node_offset_by_compatible(f, -1, "qcom,sde-kms");
    struct mock_display mock = {0};
    assert(sde >= 0 && !dt_reg_named(f, sde, "mdp_phys", &mock.regs));
    const struct CrIo io = {.context = &mock, .read32 = empty_display};
    kshim_framebuffer_config_t fb;
    kshim_mmu_region_t mmio;
    assert(kshim_dt_splash(f, &io, &fb, &mmio) != 0);
    assert(mock.reads > 0 && !fb.render_address && !fb.width && !mmio.size);
    assert(!memcmp(snapshot, f, (size_t)size));
    /* Conflicting hardware version must fail before issuing a single read. */
    assert(!fdt_open_into(f, f, (int)capacity));
    sde = fdt_node_offset_by_compatible(f, -1, "qcom,sde-kms");
    assert(!fdt_setprop_u32(f, sde, "qcom,sde-hw-version", 0xdeadbeef));
    mock.reads = 0;
    assert(kshim_dt_splash(f, &io, &fb, &mmio) != 0 && !mock.reads);
    free(r); free(snapshot); free(f);
    puts("OPD2413 DT: three keys and SPMI decoded; display tables accepted; no scanout guessed; input unchanged");
    return 0;
}
