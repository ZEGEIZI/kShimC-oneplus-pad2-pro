#!/usr/bin/env python3
"""Apply maintained device integration to the locked ArmadaOS distro input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from host_tools import command
DEVICE=Path(__file__).resolve().parents[1]
RELEASE='7.2.6-opd2413-full-system03'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['kernel','initramfs','helpers','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    for name in ['kernel','initramfs','helpers']:
        if not json.loads((getattr(args,name)/'result.json').read_text())['passed']:raise ValueError('unverified component '+name)
    out.mkdir(parents=True);locked=json.loads((DEVICE/'inputs/os-base.json').read_text());image=locked['image_id']
    if subprocess.run(['podman','image','exists',image]).returncode:
        path=DEVICE/'inputs'/locked['archive']
        with path.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=locked['archive_sha256']:raise ValueError('OS base archive mismatch')
        child=subprocess.Popen(command('zstd')+['-q','-d','-c',str(path)],stdout=subprocess.PIPE)
        subprocess.run(['podman','load'],stdin=child.stdout,check=True);child.stdout.close()
        if child.wait():raise RuntimeError('OS base decompression failed')
    stage=out/'overlay';shutil.copytree(DEVICE/'rootfs/overlay',stage,symlinks=True)
    shutil.copytree(DEVICE/'inputs/local/firmware',stage/'usr/lib/firmware',dirs_exist_ok=True)
    module_dir=stage/'usr/lib/modules'/RELEASE;module_dir.mkdir(parents=True)
    shutil.copyfile(args.kernel/'Image',module_dir/'vmlinuz');shutil.copyfile(args.initramfs/'initramfs.img',module_dir/'initramfs.img')
    shutil.copyfile(DEVICE/'kernel/current/config',module_dir/'config')
    helper=stage/'usr/libexec/armada/opd2413-rootfs-log';helper.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.helpers/'opd2413-rootfs-log',helper);helper.chmod(0o755)
    link=stage/'usr/lib/systemd/system/bluetooth.service.wants/opd2413-btaddr.service';link.parent.mkdir(parents=True);link.symlink_to('../opd2413-btaddr.service')
    recipe=out/'Containerfile';recipe.write_text('FROM '+image+'\nCOPY overlay/ /\n')
    with (out/'build.log').open('w') as log:subprocess.run(['podman','build','--network=none','--pull=never','--timestamp','1794182400','--iidfile',str(out/'image-id'),'-f',str(recipe),str(out)],stdout=log,stderr=subprocess.STDOUT,check=True)
    final=(out/'image-id').read_text().strip();cid=subprocess.check_output(['podman','create',final],text=True).strip()
    try:
        # Read actual resulting content, including all unchanged dictionary modules.
        subprocess.run(['podman','cp',cid+':/usr/lib/modules/'+RELEASE,str(out/'verified-modules')],check=True,stdout=subprocess.DEVNULL)
        report=json.loads((DEVICE/'inputs/local/package03-report.json').read_text())
        for name,row in report['stripped_module_load_identity_verified'].items():
            if hashlib.sha256((out/'verified-modules'/name).read_bytes()).hexdigest()!=row['stripped_sha256']:raise ValueError('base module dictionary changed: '+name)
        subprocess.run(['podman','cp',cid+':/usr/lib/systemd/system/opd2413-btaddr.service',str(out/'verified-btaddr.service')],check=True,stdout=subprocess.DEVNULL)
        if (out/'verified-btaddr.service').read_bytes()!=(stage/'usr/lib/systemd/system/opd2413-btaddr.service').read_bytes():raise ValueError('Bluetooth service missing')
    finally:subprocess.run(['podman','rm',cid],check=True,stdout=subprocess.DEVNULL)
    result=dict(passed=True,image_id=final,distro_base=image,device_sources_applied=True,original_164_module_dictionary_preserved=True,personal_Bluetooth_identity_embedded=False,full_distro_recompiled=False,physical_installation_performed=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
