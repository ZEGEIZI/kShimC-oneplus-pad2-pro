#!/usr/bin/env python3
"""Build the runtime ext4/configuration reader for host image verification."""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(out, sanitize=False):
    out.mkdir(parents=True, exist_ok=True)
    shim = ROOT/'boot/vendor/kshim'
    nh = ROOT/'boot/vendor/nh-ext4'
    sources = [ROOT/'tools/check_boot_files.c',
               *(shim/'src/core'/n for n in ('storage_block.c', 'ext4_boot.c', 'boot_files_config.c', 'boot_files_menu.c')),
               *(nh/n for n in ('NhBase.c', 'NhExt4.c', 'NhFs.c'))]
    command = ['cc', '-std=gnu11', '-DKSHIM_FILE_BOOT_ENABLED=1', '-g', '-O1', '-Wall', '-Wextra',
               '-Werror', '-Wno-misleading-indentation', '-ffunction-sections', '-fdata-sections',
               '-Wl,--gc-sections', '-I'+str(shim/'src/include'), '-I'+str(nh/'include')]
    if sanitize:
        command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    subprocess.run(command+[str(s) for s in sources]+['-o', str(out/'check-boot-files')], check=True)
    menu_sources = [ROOT/'tests/boot_files_menu_test.c', shim/'src/core/boot_files_menu.c']
    subprocess.run(command+[str(s) for s in menu_sources]+['-o',str(out/'boot-files-menu-test')],check=True)
    subprocess.run([str(out/'boot-files-menu-test')],check=True)
    memory_sources = [ROOT/'tests/boot_files_memory_test.c', shim/'src/core/boot_files_memory.c', nh/'NhBase.c']
    subprocess.run(command+['-I'+str(shim/'lib/libfdt/include')]+[str(s) for s in memory_sources]+
                   ['-o',str(out/'boot-files-memory-test')],check=True)
    subprocess.run([str(out/'boot-files-memory-test')],check=True)
    session_sources = [ROOT/'tests/boot_files_storage_test.c',
                       shim/'src/arch/arm64/boot_files_storage.c',
                       shim/'src/core/storage_block.c', shim/'src/core/boot_files_config.c']
    session_flags = ['-I'+str(shim/'lib/libfdt/include'), '-I'+str(shim/'tests/include'),
                     '-DCONFIG_KSHIM_BOOT_PARTUUID="00112233-4455-6677-8899-aabbccddeeff"',
                     '-DCONFIG_KSHIM_BOOT_PARTLABEL="linux_boot"']
    subprocess.run(command+session_flags+[str(s) for s in session_sources]+
                   ['-o',str(out/'boot-files-storage-test')],check=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        cases = [pool.submit(subprocess.run,[str(out/'boot-files-storage-test'),str(i)],
                             capture_output=True,text=True) for i in range(15)]
        for i,future in enumerate(cases):
            result = future.result()
            if result.returncode:
                raise RuntimeError(f'Native storage case {i} failed:\n{result.stdout}{result.stderr}')
    print('native UFS session: all 15 admission, multi-LUN, failure and restore cases passed')
    return out/'check-boot-files'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--sanitize', action='store_true')
    a = p.parse_args()
    print(build(a.out.resolve(), a.sanitize))
