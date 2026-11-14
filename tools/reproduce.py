#!/usr/bin/env python3
"""Rebuild current device code, initramfs and persistent29 boot offline."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--jobs',type=int,default=8)
    parser.add_argument('--with-rootfs',action='store_true');parser.add_argument('--with-installation',action='store_true')
    parser.add_argument('--with-console',action='store_true',help='also build the tested scrolling boot/shutdown console variant')
    parser.add_argument('--with-battery',action='store_true',help='also build the GLINK battery variant with the text console')
    args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('choose a new output directory')
    out.mkdir(parents=True);started=time.time();stages=[]
    def run(name,tool,options=()):
        print('Building '+name,flush=True);command=[sys.executable,str(DEVICE/'tools'/tool),'--out',str(out/name),*map(str,options)]
        with (out/(name+'.log')).open('w') as log:q=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if q.returncode:raise RuntimeError(name+' failed; see '+str(out/(name+'.log')))
        result=json.loads((out/name/'result.json').read_text())
        if not result['passed']:raise RuntimeError(name+' did not pass')
        stages.append(dict(stage=name,passed=True));return out/name
    subprocess.run([sys.executable,str(DEVICE/'tools/verify_inputs.py')],check=True)
    kernel=run('kernel','build_kernel.py',['--jobs',args.jobs])
    modules=run('modules','build_modules.py',['--kernel',kernel])
    bundle=run('bundle','build_bundle.py',['--modules',modules])
    helpers=run('helpers','build_helpers.py')
    boot_tools=run('boot-tools','build_boot_tools.py',['--jobs',args.jobs])
    dtb=run('dtb','build_dtb.py');plasma=run('plasma','build_plasma.py')
    initrd=run('initramfs','build_initramfs.py',['--modules',modules,'--bundle',bundle,'--helpers',helpers,'--plasma',plasma])
    boot=run('boot','build_boot.py',['--kernel',kernel,'--boot-tools',boot_tools,'--dtb',dtb,'--initramfs',initrd])
    if args.with_console or args.with_battery:
        console=run('console','build_console_boot.py',['--reference',boot/'boot.img'])
    if args.with_battery:
        run('battery','build_battery_boot.py',['--reference',console/'boot.img','--kernel',kernel])
    if args.with_rootfs:run('rootfs','build_rootfs.py',['--kernel',kernel,'--initramfs',initrd,'--helpers',helpers])
    if args.with_installation:run('installation','prepare_installation.py',['--boot',boot])
    subprocess.run([sys.executable,str(DEVICE/'tools/check.py'),'--build',str(out)],check=True)
    result=dict(passed=True,stages=stages,seconds=time.time()-started,source_rebuilt_device_code=True,boot29_byte_identical=True,old_build_dependency=False,device_access=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
