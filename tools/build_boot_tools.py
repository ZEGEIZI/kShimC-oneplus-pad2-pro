#!/usr/bin/env python3
"""Build the retained kShim runtime and packer from device-local sources."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from boot_contract import EXTERNAL_RUNTIME_SIZE, RUNTIME_SIZE

DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--jobs',type=int,default=8)
    parser.add_argument('--mode',choices=['historical','ext4'],default='historical')
    parser.add_argument('--resume',action='store_true',help='Reconfigure/rebuild an existing output after source changes')
    args=parser.parse_args();out=args.out.resolve()
    slot_size=EXTERNAL_RUNTIME_SIZE if args.mode=='ext4' else RUNTIME_SIZE
    heap_size=0x40000 if args.mode=='ext4' else 0x10000
    if out.exists() and not args.resume:parser.error('output directory must be new (or use --resume)')
    out.mkdir(parents=True,exist_ok=args.resume);(out/'kshim').mkdir(exist_ok=args.resume);shutil.copyfile(DEVICE/('boot/kshim-ext4.config' if args.mode=='ext4' else 'boot/kshim.config'),out/'kshim/.config')
    locked=json.loads((DEVICE/'boot/kshim-source.json').read_text());image=json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    epoch=int(datetime.datetime.strptime(locked['source_date_utc'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp())
    base=['docker','run','--rm','--network=none','--hostname','501b28fdf1b7','--user',f'{os.getuid()}:{os.getgid()}',
          '--mount',f'type=bind,src={DEVICE},dst=/device,readonly','--mount',f'type=bind,src={out},dst=/work',
          '-e','PYTHONPATH=/device/boot/vendor/kconfiglib','-e','SOURCE_DATE_EPOCH='+str(epoch),'-e','TERM=xterm-256color',image]
    commands=[('configure-packer',['cmake','-S','/device/boot/vendor/packer','-B','/work/packer','-DBUILD_SHIMS=OFF','-DCMAKE_BUILD_TYPE=Release']),
              ('compile-packer',['cmake','--build','/work/packer','--parallel',str(args.jobs)]),
              ('configure-kshim',['cmake','-S','/device/boot/vendor/kshim','-B','/work/kshim','-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DGENCONFIG_EXECUTABLE=/device/tools/genconfig','-DKSHIM_STANDALONE=OFF',f'-DKSHIM_RUNTIME_SLOT_SIZE={slot_size:#x}',f'-DKSHIM_HEAP_SIZE={heap_size:#x}','-DLV_BUILD_EXAMPLES=OFF','-DLV_BUILD_DEMOS=OFF']),
              ('compile-kshim',['cmake','--build','/work/kshim','--parallel',str(args.jobs)])]
    for label,cmd in commands:
        print(label,flush=True)
        with (out/(label+'.log')).open('w') as log:q=subprocess.run(base+cmd,stdout=log,stderr=subprocess.STDOUT)
        if q.returncode:raise RuntimeError(label+' failed; see '+str(out/(label+'.log')))
    runtime=out/'kshim/kShimC.bin';actual=hashlib.sha256(runtime.read_bytes()).hexdigest()
    result=dict(passed=actual==locked['reference_runtime_sha256'],source_built=True,old_build_not_mounted=True,runtime_sha256=actual,reference_runtime_sha256=locked['reference_runtime_sha256'],reference_runtime_identical=actual==locked['reference_runtime_sha256'])
    if args.mode=='ext4':
        header=runtime.read_bytes()[:64]
        result.update(passed=runtime.stat().st_size==slot_size and header[56:60]==b'ARM\x64' and
                      struct.unpack_from('<Q',header,16)[0]==slot_size,mode='ext4',hardware_verified=False,
                      runtime_slot_bytes=slot_size,runtime_bytes=runtime.stat().st_size,general_heap_bytes=heap_size,
                      config_sha256=hashlib.sha256((out/'kshim/.config').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    if not result['passed']:raise ValueError('Runtime exceeds slot or historical snapshot differs; inspect result.json')


if __name__=='__main__':main()
