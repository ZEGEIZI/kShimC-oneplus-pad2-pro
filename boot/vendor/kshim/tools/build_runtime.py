#!/usr/bin/env python3
"""Build a 4 MiB Manifest runtime from any capability profile, without UEFI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=8)
    diagnostic = parser.add_mutually_exclusive_group()
    diagnostic.add_argument("--diagnostic-base-only", action="store_true",
                        help="Hand off immediately to Android without DT/peripheral/UI work")
    diagnostic.add_argument("--diagnostic-dt-only", action="store_true",
                            help="Parse the DT then return to Android without MMU or peripherals")
    diagnostic.add_argument("--diagnostic-early-mmu-only", action="store_true",
                            help="Configure and clean/disable early MMU then return without peripherals")
    diagnostic.add_argument("--diagnostic-resources-only", action="store_true",
                            help="Probe resources, clean/disable MMU, then return without drawing a menu")
    diagnostic.add_argument("--diagnostic-display-snapshot", action="store_true",
                            help="OPD2413 read-only display snapshot, then return without rendering")
    diagnostic.add_argument("--diagnostic-menu-preview", action="store_true",
                            help="Show the OPD2413 menu without physical key polling, then boot Android")
    diagnostic.add_argument("--diagnostic-key-controller", action="store_true",
                            help="OPD2413 preview plus one controller-version read, without key polling")
    diagnostic.add_argument("--diagnostic-menu-keys", action="store_true",
                            help="OPD2413 menu with gated PMIC key input and Android fallback")
    args = parser.parse_args()
    root, out = Path(__file__).resolve().parents[1], args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    config = args.config.read_text()
    config = re.sub(r"^CONFIG_KSHIM_UEFI_TEST_MENU=.*$", "# CONFIG_KSHIM_UEFI_TEST_MENU is not set",
                    config, flags=re.M)
    config = re.sub(r"^(?:CONFIG_KSHIM_PAD2PRO_(?:MENU_PREVIEW|KEY_PROBE|MENU_KEYS)=.*|# CONFIG_KSHIM_PAD2PRO_(?:MENU_PREVIEW|KEY_PROBE|MENU_KEYS) is not set)$",
                    "", config, flags=re.M)
    config += "\n" + ("CONFIG_KSHIM_PAD2PRO_MENU_PREVIEW=y\n" if args.diagnostic_menu_preview or args.diagnostic_key_controller or args.diagnostic_menu_keys else
                       "# CONFIG_KSHIM_PAD2PRO_MENU_PREVIEW is not set\n")
    config += ("CONFIG_KSHIM_PAD2PRO_KEY_PROBE=y\n" if args.diagnostic_key_controller or args.diagnostic_menu_keys else
               "# CONFIG_KSHIM_PAD2PRO_KEY_PROBE is not set\n")
    config += ("CONFIG_KSHIM_PAD2PRO_MENU_KEYS=y\n" if args.diagnostic_menu_keys else
               "# CONFIG_KSHIM_PAD2PRO_MENU_KEYS is not set\n")
    (out / ".config").write_text(config)
    for label, command in (
        ("configure", ["cmake", "-S", root, "-B", out, "-G", "Ninja",
                       "-DKSHIM_STANDALONE=OFF", "-DKSHIM_RUNTIME_SLOT_SIZE=0x400000",
                       "-DKSHIM_DIAGNOSTIC_BASE_ONLY=" + ("ON" if args.diagnostic_base_only else "OFF"),
                       "-DKSHIM_DIAGNOSTIC_DT_ONLY=" + ("ON" if args.diagnostic_dt_only else "OFF"),
                       "-DKSHIM_DIAGNOSTIC_EARLY_MMU_ONLY=" + ("ON" if args.diagnostic_early_mmu_only else "OFF"),
                       "-DKSHIM_DIAGNOSTIC_RESOURCES_ONLY=" + ("ON" if args.diagnostic_resources_only or args.diagnostic_display_snapshot else "OFF"),
                       "-DKSHIM_DIAGNOSTIC_PAD2PRO_SPLASH_SNAPSHOT=" + ("ON" if args.diagnostic_display_snapshot else "OFF"),
                       "-DKSHIM_RAMOOPS_RECOVERY_ONLY=OFF",
                       "-DKSHIM_UEFI_PAYLOAD=", "-DCMAKE_BUILD_TYPE=Release"]),
        ("build", ["cmake", "--build", out, "-j", str(args.jobs)]),
    ):
        with (out / (label + ".log")).open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = out / "kShimC.bin"
    if binary.stat().st_size != 0x400000:
        raise ValueError("Manifest runtime must occupy exactly 4 MiB")
    undefined = subprocess.check_output(["aarch64-linux-gnu-nm", "-u", out / "kShimC.elf"], text=True)
    if undefined.strip():
        raise ValueError("Unresolved symbols: " + undefined)
    report = {"profile": args.config.name, "mode": "manifest", "bytes": binary.stat().st_size,
              "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "undefined_symbols": [],
              "hardware_tested": False}
    report["diagnostic_base_only"] = args.diagnostic_base_only
    report["diagnostic_stage"] = ("base" if args.diagnostic_base_only else
                                  "dt" if args.diagnostic_dt_only else
                                  "early-mmu" if args.diagnostic_early_mmu_only else
                                  "display-snapshot" if args.diagnostic_display_snapshot else
                                  "menu-keys" if args.diagnostic_menu_keys else
                                  "key-controller" if args.diagnostic_key_controller else
                                  "menu-preview" if args.diagnostic_menu_preview else
                                  "resources" if args.diagnostic_resources_only else "none")
    (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{args.config.name}: PASS (4 MiB; no undefined symbols)")


if __name__ == "__main__":
    main()
