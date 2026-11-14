/* SPDX-License-Identifier: MIT */
#pragma once
#include <qcom_dt.h>
#include <qcom_keys.h>
struct pad2pro_key_probe {
    int status;
    unsigned keys, mmu, reads;
    uint32_t version, regions;
};
/* OPD2413 checkpoint: validate the captured DT/key/resource layout, then read
 * only the controller's version word once. No SPMI transaction or key poll. */
void pad2pro_key_probe_run(const void *fdt, const struct kshim_resources *r,
    int mmu_enabled, const struct CrIo *io, struct pad2pro_key_probe *result);
int pad2pro_key_probe_report(const struct pad2pro_key_probe *result,
    char *out, size_t capacity);

struct pad2pro_key_input {
    int status, pon_status, gpio_status;
    uint32_t pon_value, gpio_value, pon_reads, gpio_reads, errors;
    bool enabled;
    QcomKeyRead32Status read;
    void *context;
};
/* Opt-in interaction checkpoint. After the exact 08 version/layout gate,
 * submit two bounded status reads through the existing polled adapter. Only
 * released, valid samples enable the three-key backend. A polling fault
 * latches and blocks all subsequent transactions until Android handoff. */
void pad2pro_key_input_prepare(const void *fdt, const struct kshim_resources *r,
    int mmu_enabled, const struct pad2pro_key_probe *probe,
    QcomKeyRead32Status read, void *context, QcomKeys *keys,
    struct pad2pro_key_input *result);
int pad2pro_key_input_read(void *context, uint64_t address, uint32_t *value);
int pad2pro_key_input_report(const struct pad2pro_key_input *result,
    char *out, size_t capacity);
