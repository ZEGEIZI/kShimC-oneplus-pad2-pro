/* SPDX-License-Identifier: MIT */
#include <oneplus_pad2pro_key_probe.h>
#include <qcom_keys_fdt.h>
#include <stdio.h>
#include <string.h>

static bool captured_controller(const struct kshim_resources *r)
{
    static const SpmiMemoryRegion expected[SPMI_MEMORY_REGION_TYPE_MAX] = {
        [SPMI_MEMORY_REGION_TYPE_CORE] = {0xc400000, 0x3000},
        [SPMI_MEMORY_REGION_TYPE_CH_SLAVES] = {0xc500000, 0x400000},
        [SPMI_MEMORY_REGION_TYPE_OBSERVER] = {0xc440000, 0x80000},
        [SPMI_MEMORY_REGION_TYPE_INTERRUPT] = {0xc4c0000, 0x10000},
        [SPMI_MEMORY_REGION_TYPE_CONFIG] = {0xc42d000, 0x4000},
    };
    if (!r || r->spmi_status || r->spmi_count != 1 ||
        r->mapping_count > KSHIM_RESOURCE_MAX) return false;
    const SpmiDeviceContext *c = &r->spmi[0].controller;
    if (c->BusId || c->ActiveEE || c->Channel || c->HasInterrupt || c->Initialized)
        return false;
    for (unsigned i = 0; i < SPMI_MEMORY_REGION_TYPE_MAX; ++i)
        if (c->Regions[i].BaseAddress != expected[i].BaseAddress ||
            c->Regions[i].Size != expected[i].Size) return false;
    return true;
}

static bool captured_keys(const QcomKeyDescriptor *keys, size_t count)
{
    unsigned seen = 0;
    if (count != 3) return false;
    for (size_t i = 0; i < count; ++i) {
        const QcomKeyDescriptor *k = &keys[i];
        unsigned bit;
        if (k->Code == QCOM_KEYCODE_POWER || k->Code == QCOM_KEYCODE_VOLUMEUP) {
            bit = k->Code == QCOM_KEYCODE_POWER ? 1u : 2u;
            if (k->Base != QCOM_KEY_SPMI_RESOURCE(0, 0, 0, 0x1300) ||
                k->RegisterOffset != 0x10 || k->Mask != (bit == 1 ? 128u : 64u) ||
                k->Source != QCOM_KEY_SOURCE_PON || k->ActiveLow ||
                k->Action != (bit == 1 ? QCOM_KEY_ACTION_SELECT : QCOM_KEY_ACTION_UP)) return false;
        } else if (k->Code == QCOM_KEYCODE_VOLUMEDOWN) {
            bit = 4;
            if (k->Base != (QCOM_KEY_SPMI_RESOURCE(0, 0, 1, 0x8d10) | QCOM_KEY_PMIC_GPIO_FLAG) ||
                k->RegisterOffset || k->Mask != 1 || k->Source != QCOM_KEY_SOURCE_PMIC_GPIO ||
                k->ActiveLow != 1 || k->Action != QCOM_KEY_ACTION_DOWN) return false;
        } else return false;
        if (seen & bit) return false;
        seen |= bit;
    }
    return seen == 7;
}

void pad2pro_key_probe_run(const void *fdt, const struct kshim_resources *r,
    int mmu_enabled, const struct CrIo *io, struct pad2pro_key_probe *result)
{
    if (!result) return;
    *result = (struct pad2pro_key_probe){.status = -1, .mmu = mmu_enabled == 1};
    if (!fdt || fdt_check_header(fdt) || fdt_node_check_compatible(fdt, 0, "qcom,sunp")) return;
    const char *model = dt_string(fdt, 0, "model");
    if (!model || strcmp(model, "Qualcomm Technologies, Inc. Sun MTP,erhai-O DVT")) return;
    result->status = -2;
    if (!captured_controller(r) || r->fdt != fdt) return;
    for (unsigned i = 0; i < SPMI_MEMORY_REGION_TYPE_MAX; ++i)
        if (r->spmi[0].controller.Regions[i].Size) result->regions |= 1u << i;
    result->status = -3;
    QcomKeyDescriptor keys[QCOM_KEYS_MAX];
    size_t count = 0;
    dt_parent_index_begin(fdt);
    int parse = QcomKeysBuildFromDeviceTree(fdt, keys, QCOM_KEYS_MAX, &count);
    dt_parent_index_end();
    result->keys = (unsigned)count;
    if (parse || !captured_keys(keys, count)) return;
    result->status = -4;
    if (mmu_enabled != 1 || !io || !io->read32) return;
    result->status = -5;
    bool mapped = false;
    const uint64_t address = 0xc400000;
    for (size_t i = 0; i < r->mapping_count; ++i) {
        const kshim_mmu_region_t *m = &r->mappings[i];
        if (m->type == KSHIM_MMU_DEVICE && (m->permissions & KSHIM_MMU_READ) &&
            m->base <= address && m->size >= 4 && m->base <= UINT64_MAX - m->size &&
            address - m->base <= m->size - 4) mapped = true;
    }
    if (!mapped) return;
    result->version = io->read32(io->context, (uintptr_t)address);
    result->reads = 1;
    /* This is successful capture, not proof that this ABI is supported or
     * that any PMIC key can be read. The next stage must inspect the value. */
    result->status = 0;
}

int pad2pro_key_probe_report(const struct pad2pro_key_probe *r, char *out, size_t capacity)
{
    if (!r || !out || capacity < 81) return -1;
    int n = snprintf(out, capacity, "kp1:rc=%d:k=%u:mmu=%u:rd=%u:v=%08x:r=%x",
        r->status, r->keys, r->mmu, r->reads, r->version, r->regions);
    return n > 0 && n <= 80 && (size_t)n < capacity ? n : -1;
}

static bool controller_mapped(const struct kshim_resources *r)
{
    for (unsigned region = 0; region < SPMI_MEMORY_REGION_TYPE_MAX; ++region) {
        const SpmiMemoryRegion *s = &r->spmi[0].controller.Regions[region];
        if (!s->Size) continue;
        bool found = false;
        for (size_t i = 0; i < r->mapping_count; ++i) {
            const kshim_mmu_region_t *m = &r->mappings[i];
            unsigned rw = KSHIM_MMU_READ | KSHIM_MMU_WRITE;
            if (m->type == KSHIM_MMU_DEVICE && (m->permissions & rw) == rw &&
                m->base <= s->BaseAddress && m->size >= s->Size &&
                m->base <= UINT64_MAX - m->size &&
                s->BaseAddress - m->base <= m->size - s->Size) found = true;
        }
        if (!found) return false;
    }
    return true;
}

int pad2pro_key_input_read(void *context, uint64_t address, uint32_t *value)
{
    struct pad2pro_key_input *r = context;
    if (!r || !r->read || r->errors) return -1;
    bool pon = address == QCOM_KEY_SPMI_RESOURCE(0, 0, 0, 0x1310);
    bool gpio = address == (QCOM_KEY_SPMI_RESOURCE(0, 0, 1, 0x8d10) | QCOM_KEY_PMIC_GPIO_FLAG);
    uint32_t sample = 0;
    int rc = -1;
    if (value && (pon || gpio)) {
        uint32_t *count = pon ? &r->pon_reads : &r->gpio_reads;
        if (*count != UINT32_MAX) ++*count;
        rc = r->read(r->context, address, &sample);
        if (!rc && (sample > (pon ? 255u : 1u))) rc = -1;
    }
    if (rc) {
        ++r->errors;
        if (r->enabled) r->status = -6;
        return rc;
    }
    *value = sample;
    return 0;
}

void pad2pro_key_input_prepare(const void *fdt, const struct kshim_resources *r,
    int mmu_enabled, const struct pad2pro_key_probe *probe,
    QcomKeyRead32Status read, void *context, QcomKeys *keys,
    struct pad2pro_key_input *result)
{
    if (!result) return;
    *result = (struct pad2pro_key_input){.status = -1, .pon_status = -9,
        .gpio_status = -9, .pon_value = 255, .gpio_value = 255};
    if (!keys || !read || mmu_enabled != 1 || !probe || probe->status ||
        probe->mmu != 1 || probe->reads != 1 || probe->keys != 3 ||
        probe->regions != 0x1f || probe->version != 0x70020000 ||
        !captured_controller(r) || r->fdt != fdt || !controller_mapped(r)) return;
    if (!fdt || fdt_check_header(fdt) || fdt_node_check_compatible(fdt, 0, "qcom,sunp")) return;
    const char *model = dt_string(fdt, 0, "model");
    if (!model || strcmp(model, "Qualcomm Technologies, Inc. Sun MTP,erhai-O DVT")) return;
    QcomKeyDescriptor descriptors[QCOM_KEYS_MAX];
    size_t count = 0;
    result->status = -2;
    dt_parent_index_begin(fdt);
    int parse = QcomKeysBuildFromDeviceTree(fdt, descriptors, QCOM_KEYS_MAX, &count);
    dt_parent_index_end();
    if (parse || !captured_keys(descriptors, count)) return;
    result->read = read;
    result->context = context;
    result->pon_status = pad2pro_key_input_read(result,
        QCOM_KEY_SPMI_RESOURCE(0, 0, 0, 0x1310), &result->pon_value);
    if (result->pon_status) { result->status = -3; return; }
    result->gpio_status = pad2pro_key_input_read(result,
        QCOM_KEY_SPMI_RESOURCE(0, 0, 1, 0x8d10) | QCOM_KEY_PMIC_GPIO_FLAG,
        &result->gpio_value);
    if (result->gpio_status) { result->status = -4; return; }
    /* Do not turn a button held during boot or an invalid sample into an
     * immediate selection or cancelled timeout. Retry on the next user boot. */
    if ((result->pon_value & 0xc0) || !result->gpio_value) {
        result->status = -5; return;
    }
    if (QcomKeysInitEx(keys, descriptors, count, NULL, pad2pro_key_input_read, result)) return;
    QcomKeysSetDebounce(keys, QCOM_KEYS_DEFAULT_DEBOUNCE);
    result->status = 0;
    result->enabled = true;
}

int pad2pro_key_input_report(const struct pad2pro_key_input *r, char *out, size_t capacity)
{
    if (!r || !out || capacity < 81) return -1;
    int n = snprintf(out, capacity, "ki1:rc=%d:en=%u:p=%d/%x:g=%d/%x:n=%u/%u:e=%u",
        r->status, r->enabled ? 1u : 0u, r->pon_status, r->pon_value,
        r->gpio_status, r->gpio_value, r->pon_reads, r->gpio_reads, r->errors);
    return n > 0 && n <= 80 && (size_t)n < capacity ? n : -1;
}
