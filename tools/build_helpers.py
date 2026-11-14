#!/usr/bin/env python3
"""Recompile the two actual initrd helpers with the locked compiler/runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    out.mkdir(parents=True);libs=out/'libs';libs.mkdir();locked=json.loads((DEVICE/'boot/initramfs.lock.json').read_text());libnames=['libcrypto.so.3.5.9','libzstd.so.1.5.7','libc.so.6']
    for name in libnames:
        row=next(x for x in locked['entries'] if x['path']=='usr/lib64/'+name)
        source=DEVICE/'inputs/local/initrd-runtime'/row['value']
        if hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('native ARM64 library hash mismatch')
        shutil.copyfile(source,libs/name)
    image=json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    base=['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
          '--mount',f'type=bind,src={DEVICE},dst=/device,readonly','--mount',f'type=bind,src={out},dst=/work',image,'aarch64-linux-gnu-gcc']
    commands={
        'opd2413-rootfs-log':['-static','-Os','-Wall','-Wextra','-Werror','-DDIAG_CPU=1','-I/device/rootfs/helpers/logger','-o','/work/opd2413-rootfs-log','/device/rootfs/helpers/logger/rootfs_probe.c','/device/rootfs/helpers/logger/diag_cpu.c'],
        'opd2413-reconstruct-modules':['-std=gnu11','-O2','-Wall','-Wextra','-Werror','/device/rootfs/helpers/reconstructor/reconstruct.c','-L/work/libs','-Wl,-rpath-link,/work/libs','-l:libcrypto.so.3.5.9','-l:libzstd.so.1.5.7','-l:libc.so.6','-o','/work/opd2413-reconstruct-modules']}
    records=[]
    for name,argv in commands.items():
        q=subprocess.run(base+argv,capture_output=True,text=True);(out/(name+'.log')).write_text(q.stdout+q.stderr)
        if q.returncode:raise RuntimeError(name+' compilation failed')
        expected=next(x['sha256'] for x in locked['entries'] if x['provider']=='helper' and x['value']==name)
        actual=hashlib.sha256((out/name).read_bytes()).hexdigest()
        if actual!=expected:raise ValueError(name+' binary differs: '+actual)
        records.append(dict(name=name,sha256=actual,byte_identical=True))
    result=dict(passed=True,source_rebuilt=True,binaries=records,old_build_not_mounted=True)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
