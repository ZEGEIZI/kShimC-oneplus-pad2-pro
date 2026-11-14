#!/usr/bin/env python3
"""Pack Android+kShimC production or Linux-only fastboot debug boot.img."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from boot_contract import check_external_packed

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--boot-tools', type=Path, required=True)
    p.add_argument('--stock-boot', type=Path, required=True, help='Original Android v4 boot container')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--debug-image', type=Path)
    p.add_argument('--debug-dtb', type=Path)
    p.add_argument('--debug-initrd', type=Path)
    a = p.parse_args()
    debug = bool(a.debug_image)
    if any((a.debug_image, a.debug_dtb, a.debug_initrd)) and not all((a.debug_image, a.debug_dtb, a.debug_initrd)):
        p.error('Debug mode requires matching Image, DTB and initrd')
    tools = a.boot_tools.resolve()
    result = json.loads((tools/'result.json').read_text())
    runtime = tools/'kshim/kShimC.bin'
    if not result['passed'] or result.get('mode') != 'ext4' or hashlib.sha256(runtime.read_bytes()).hexdigest() != result['runtime_sha256']:
        raise ValueError('Expected verified ext4-mode boot-tools')
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    original = a.stock_boot.read_bytes()
    if original[:8] != b'ANDROID!' or struct.unpack_from('<I',original,40)[0] != 4 or struct.unpack_from('<I',original,12)[0]:
        raise ValueError('Expected original v4 boot with empty ramdisk')
    stock_kernel = original[4096:4096+struct.unpack_from('<I',original,8)[0]]
    if any(struct.unpack_from('<3Q',stock_kernel,32)):
        raise ValueError('Stock input already has manifest metadata')
    base = a.debug_image.read_bytes() if debug else stock_kernel
    if len(base) < 64 or base[56:60] != b'ARM\x64':
        raise ValueError('Expected uncompressed ARM64 Image')
    (out/'BaseImage').write_bytes(base)
    # Keep the measured diagnostic slots used by the existing OnePlus menu.
    header = bytearray(original[:4096])
    value = 'pending'+'_'*73
    slots = ' '.join(k+'='+value for k in ('kshimreport.kshim_probe','kshimreport.kshim_s0','androidboot.kshim_s1')).encode()
    if any(header[44:1580]):
        raise ValueError('Unexpected stock command line; preserve/review it explicitly')
    header[44:1580] = slots.ljust(1536,b'\0')
    container = out/'header-source.img'
    container.write_bytes(header+original[4096:])
    timeout = 0 if debug else 8000
    cfg = f'[Pack]\nShim={runtime}\nOutput={out / "PackedKernel"}\nDefault=Image-00\nTimeout={timeout}\n\n'
    cfg += f'[Image-00]\nName={"Linux RAM fallback" if debug else "原厂 Android"}\nType=Linux\nPath={out / "BaseImage"}\nAlign=21\nBaseImage=true\n'
    extra = None
    if debug:
        dtb = out/'debug.dtb'
        shutil.copyfile(a.debug_dtb,dtb)
        subprocess.run(['fdtput','-t','x',str(dtb),'/chosen','kshim,initrd-entry','2'],check=True)
        cfg += 'DeviceTreeBlob=Image-01\n\n'
        for i,kind,path,alignment in [(1,'DTB',dtb,3),(2,'Blob',a.debug_initrd.resolve(),16)]:
            cfg += f'[Image-{i:02d}]\nName=Linux debug {kind}\nType={kind}\nPath={path}\nAlign={alignment}\nBaseImage=false\n\n'
        extra = [dtb.read_bytes(),a.debug_initrd.read_bytes()]
    cfg += '\n[Manifest]\nType=Manifest\n'
    (out/'build.cfg').write_text(cfg)
    subprocess.run([str(tools/'packer/MultiBootKernelPatcher'),str(out/'build.cfg')],stdout=(out/'packer.log').open('w'),stderr=subprocess.STDOUT,check=True)
    packed = (out/'PackedKernel').read_bytes()
    contract = check_external_packed(packed,base,runtime.read_bytes(),timeout,debug_payloads=extra,
                                     runtime_slot_bytes=result['runtime_slot_bytes'])
    subprocess.run([sys.executable,str(ROOT/'tools/repack_boot_v4.py'),'--original',str(container),'--kernel',str(out/'PackedKernel'),
                    '--output',str(out/'boot.img'),'--report',str(out/'repack.json'),'--avbtool',str(ROOT/'tools/avbtool.py')],
                   stdout=(out/'repack.log').open('w'),stderr=subprocess.STDOUT,check=True)
    container.unlink()
    report = dict(passed=True,mode='debug-linux-only' if debug else 'external-production',hardware_verified=False,
                  boot_sha256=hashlib.sha256((out/'boot.img').read_bytes()).hexdigest(),
                  stock_boot_sha256=hashlib.sha256(original).hexdigest(),runtime_sha256=result['runtime_sha256'],
                  packed_kernel_bytes=len(packed),layout=contract,device_written=False)
    (out/'result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()
