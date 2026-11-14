#!/usr/bin/env python3
"""Build the current GLINK battery boot image with the verified core/console."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

from boot_contract import align, check_linux_packed
from build_boot import STOCK_SHA
from build_console_boot import replace_entry, repack_payloads, sha
from cpio import assemble, decode, parse as parse_cpio
from dtb import parse as parse_dtb
from host_tools import command

DEVICE = Path(__file__).resolve().parents[1]
CONSOLE_SHA = '4ba90cca3e715a92ffe8ef9b115e860756ac057a259a8c47d93d2d2be1f984ef'
DRIVERS = ('drivers/soc/qcom/pmic_glink.c', 'drivers/power/supply/qcom_battmgr.c')
SOURCE_HASHES = ('3e087dd303cf07a980836c4fd1e2ea26f0a7d9ad8a1f1d92f4129da4c9ad3a20',
                 '832ffd8e386533f51a8325ef8736dbf9d5bf29abf2d97c17b764f1b427636d40')


def verify_battery_dtb(before, after):
    old, nodes, _ = parse_dtb(before)
    new, new_nodes, _ = parse_dtb(after)
    expected = dict(old)
    expected['/pmic-glink:compatible'] = (b'qcom,sm8750-pmic-glink\0'
        b'qcom,sm8550-pmic-glink\0qcom,pmic-glink\0')
    if new != expected or new_nodes != nodes | {'/pmic-glink'}:
        raise ValueError('battery DT changed properties beyond the GLINK node')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True, help='Verified core build with source and build directories')
    parser.add_argument('--reference', type=Path, required=True, help='Fresh text-console boot image from build_console_boot.py')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); kernel = args.kernel.resolve()
    if out.exists(): parser.error('output directory must be new')
    reference = args.reference.read_bytes()
    if sha(reference) != CONSOLE_SHA: raise ValueError('reference is not the verified console image')
    if not json.loads((kernel/'result.json').read_text())['passed']:
        raise ValueError('kernel build not verified')
    lock = json.loads((DEVICE/'kernel/current/reproducibility.json').read_text())
    if sha((kernel/'build/.config').read_bytes()) != lock['config_sha256']:
        raise ValueError('kernel configuration mismatch')
    if sha((kernel/'build/Module.symvers').read_bytes()) != lock['export_sha256']:
        raise ValueError('kernel exported ABI mismatch')
    original = (DEVICE/'inputs/local/stock-android-boot.img').read_bytes()
    if sha(original) != STOCK_SHA: raise ValueError('stock boot hash mismatch')
    stock = original[4096:4096+struct.unpack_from('<I', original, 8)[0]]
    packed = reference[4096:4096+struct.unpack_from('<I', reference, 8)[0]]
    offset = struct.unpack_from('<Q', packed, 32)[0]; cursor = offset+60; payloads=[]
    for _ in range(5):
        start, size = struct.unpack_from('<QQ', packed, cursor)
        payloads.append(packed[start:start+size])
        cursor += align(56+struct.unpack_from('<I', packed, cursor+52)[0], 4)
    check_linux_packed(packed, stock, payloads[4], 8000, payloads[1:4],
        payload_names=('Linux 系统（实验）','OPD2413 rootfs DTB','standard dracut initramfs'))
    image_bytes=lock['image_bytes']
    if sha(payloads[1][:image_bytes]) != lock['image_sha256'] or any(payloads[1][image_bytes:]):
        raise ValueError('reference core mismatch')
    out.mkdir(parents=True); modules=out/'modules'; modules.mkdir()
    sources={}
    # These two files are unchanged upstream files, outside the effective overlay.
    for path, expected in zip(DRIVERS, SOURCE_HASHES):
        data=(kernel/'source'/path).read_bytes()
        if sha(data)!=expected: raise ValueError('driver source mismatch: '+path)
        sources[path]=sha(data)
        (modules/Path(path).name).write_bytes(data)
    for patch in sorted((DEVICE/'research/battery').glob('*.patch')):
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(patch)],cwd=modules,check=True)
    (modules/'Makefile').write_text('obj-m += pmic_glink.o qcom_battmgr.o\n')
    image=json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    base=['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
        '--mount',f'type=bind,src={DEVICE},dst=/device,readonly',
        '--mount',f'type=bind,src={kernel},dst=/work',
        '--mount',f'type=bind,src={out},dst=/candidate',image]
    # External modules use the same prepared headers, compiler, BTF and modversions.
    result=subprocess.run(base+['make','-C','/work/source','O=/work/build','ARCH=arm64',
        'CROSS_COMPILE=aarch64-linux-gnu-',
        'PAHOLE=/device/inputs/local/pahole132/run-pahole',
        'M=/candidate/modules','-j4','modules'],capture_output=True,text=True)
    (out/'modules.log').write_text(result.stdout+result.stderr)
    if result.returncode: raise RuntimeError('module compilation failed; see modules.log')
    source=DEVICE/'research/battery'
    logger=(DEVICE/'rootfs/helpers/logger/rootfs_probe.c').read_text()
    logger=logger.replace('#include "probe_board.c"', '#include "probe_board.c"\n'
        '#include "/device/console/probe_console.c"\n#include "/device/research/battery/probe_battery.c"')
    logger=logger.replace('else if(!strcmp(command,"board"))',
        'else if(!strcmp(command,"battery"))battery_reply();\n'
        '    else if(!strcmp(command,"console"))console_reply();\n'
        '    else if(!strcmp(command,"board"))')
    (out/'rootfs_probe.c').write_text(logger)
    subprocess.run(base+['aarch64-linux-gnu-gcc','-static','-Os','-Wall','-Wextra','-Werror',
        '-DDIAG_CPU=1','-I/device/rootfs/helpers/logger','-o','/candidate/logger',
        '/candidate/rootfs_probe.c','/device/rootfs/helpers/logger/diag_cpu.c'],check=True)
    entries,trailer=parse_cpio(decode(payloads[3])); before={e['path']:e['sha256'] for e in entries}
    replace_entry(entries,'usr/libexec/armada/opd2413-rootfs-log',(out/'logger').read_bytes())
    hook='var/lib/dracut/hooks/pre-pivot/90-opd2413-input-probe.sh'
    old=next(e['data'] for e in entries if e['path']==hook)
    import re
    updated,n=re.subn(rb'= \d+ \]',f'= {(out/"logger").stat().st_size} ]'.encode(),old)
    if n!=1: raise ValueError('unknown logger staging hook')
    replace_entry(entries,hook,updated)
    prefix='usr/lib/armada/opd2413-battery/'
    replace_entry(entries,prefix.rstrip('/'),b'',0o40755)
    module_hashes={}
    for name in ('pmic_glink','qcom_battmgr'):
        subprocess.run(base+['aarch64-linux-gnu-strip','--strip-debug',f'/candidate/modules/{name}.ko'],check=True)
        data=(modules/(name+'.ko')).read_bytes(); module_hashes[name+'.ko']=sha(data)
        replace_entry(entries,prefix+name+'.ko',data,0o100644)
    sums=''.join(h+'  '+name+'\n' for name,h in module_hashes.items()).encode()
    replace_entry(entries,prefix+'SHA256SUMS',sums,0o100644)
    for name in ('load-battery.sh','opd2413-battery.service'):
        replace_entry(entries,prefix+name,(source/name).read_bytes(),0o100644)
    replace_entry(entries,'var/lib/dracut/hooks/pre-pivot/96-opd2413-battery.sh',
        (source/'stage-battery.sh').read_bytes(),0o100755)
    raw=assemble(entries,trailer,lambda e:e['data']); (out/'initramfs.cpio').write_bytes(raw)
    with (out/'initramfs.img').open('wb') as stream:
        subprocess.run(command('xz')+['-9','--check=crc32','--threads=1','--stdout',str(out/'initramfs.cpio')],stdout=stream,check=True)
    initrd=(out/'initramfs.img').read_bytes(); roundtrip,_=parse_cpio(decode(initrd))
    if {e['path']:e['sha256'] for e in roundtrip}!={e['path']:e['sha256'] for e in entries}:
        raise ValueError('initramfs round trip mismatch')
    # dtc may change serialization; compare every property and node semantically.
    subprocess.run(command('dtc')+['-q','-I','dtb','-O','dts','-o',str(out/'reference.dts')],input=payloads[2],check=True)
    text=(out/'reference.dts').read_text()
    text+='\n/ { pmic-glink { compatible = "qcom,sm8750-pmic-glink", "qcom,sm8550-pmic-glink", "qcom,pmic-glink"; }; };\n'
    (out/'battery.dts').write_text(text)
    subprocess.run(command('dtc')+['-q','-I','dts','-O','dtb','-o',str(out/'opd2413-rootfs.dtb'),str(out/'battery.dts')],check=True)
    dtb=(out/'opd2413-rootfs.dtb').read_bytes(); verify_battery_dtb(payloads[2],dtb)
    candidate,checked=repack_payloads(packed,stock,dtb,initrd); (out/'PackedKernel').write_bytes(candidate)
    subprocess.run([sys.executable,str(DEVICE/'tools/repack_boot_v4.py'),'--original',str(args.reference.resolve()),
        '--kernel',str(out/'PackedKernel'),'--output',str(out/'boot.img'),'--report',str(out/'repack.json'),
        '--avbtool',str(DEVICE/'tools/avbtool.py')],check=True)
    subprocess.run(command('img2simg')+[str(out/'boot.img'),str(out/'boot.sparse'),'4096'],check=True)
    subprocess.run(command('simg2img')+[str(out/'boot.sparse'),str(out/'expanded.img')],check=True)
    boot=(out/'boot.img').read_bytes()
    if (out/'expanded.img').read_bytes()!=boot: raise ValueError('sparse round trip mismatch')
    (out/'expanded.img').unlink()
    if boot[44:1580]!=reference[44:1580]: raise ValueError('Android header changed')
    report=dict(passed=True,profile='opd2413-battery-v1',hardware_verified=False,
        reference_boot_sha256=CONSOLE_SHA,boot_sha256=sha(boot),
        sparse_sha256=sha((out/'boot.sparse').read_bytes()),
        kernel_image_unchanged=True,existing_modules_unchanged=True,dt_only_adds_glink=True,
        Android_default=True,timeout_ms=8000,stock_Android_restoration_identical=True,
        sparse_round_trip_verified=True,modules=module_hashes,driver_sources=sources,
        changed_initrd_entries=[e['path'] for e in entries if before.get(e['path'])!=e['sha256']],layout=checked)
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(sha((out/n).read_bytes())+'  '+n+'\n' for n in ['boot.img','boot.sparse']))
    print(json.dumps({k:v for k,v in report.items() if k!='layout'},indent=2))


if __name__=='__main__': main()
