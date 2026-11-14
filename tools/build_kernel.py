#!/usr/bin/env python3
"""Build the verified OPD2413 core from locked inputs in an isolated compiler."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from reproducibility import canonicalize_image
from host_tools import command as host_command

DEVICE = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_source(destination):
    manifest = json.loads((DEVICE/'kernel/current/base-overlay.json').read_text())
    archive = DEVICE/'inputs/local/linux-7.2.6.tar.xz'
    if sha(archive) != manifest['upstream_archive_sha256']:
        raise ValueError('upstream Linux archive hash mismatch')
    with tarfile.open(archive, 'r:xz') as source:
        source.extractall(destination, filter='data')
    tree = destination/'linux-7.2.6'
    tree.rename(destination/'source')
    tree = destination/'source'
    patch=DEVICE/'kernel/current'/manifest['patch']
    if sha(patch)!=manifest['patch_sha256']:
        raise ValueError('effective kernel patch hash mismatch')
    result=subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(patch)],cwd=tree,capture_output=True,text=True)
    (destination/'patch.log').write_text(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError('effective kernel patch failed')
    for record in manifest['files']:
        relative=Path(record['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe kernel patch path')
        if sha(tree/relative)!=record['target_sha256']:
            raise ValueError('effective source differs: '+str(relative))
    for snapshot in manifest.get('dtc_directory_snapshots',[]):
        target=tree/snapshot['path']
        if not target.is_symlink():
            raise ValueError('expected DT include-directory symlink')
        target.unlink()
        shutil.copytree(tree/snapshot['canonical_target'],target)
        for name in snapshot['remove']:
            (target/name).unlink()
        for record in snapshot['overrides']:
            source=DEVICE/'kernel/current'/record['source']
            if sha(source)!=record['sha256']:
                raise ValueError('DT include snapshot hash mismatch')
            destination_file=target/record['path']
            destination_file.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination_file)
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error('output directory must be new')
    out.mkdir(parents=True)
    locked = json.loads((DEVICE/'inputs/toolchain.json').read_text())
    image = locked['image_id']
    inspect = subprocess.run(['docker','image','inspect',image], capture_output=True)
    if inspect.returncode:
        archive = DEVICE/'inputs'/locked['archive']
        if sha(archive) != locked['archive_sha256']:
            raise ValueError('compiler archive hash mismatch')
        unpack = subprocess.Popen(host_command('zstd')+['-q','-d','-c',str(archive)], stdout=subprocess.PIPE)
        loaded = subprocess.run(['docker','load'], stdin=unpack.stdout, check=True)
        unpack.stdout.close()
        if unpack.wait():
            raise RuntimeError('compiler archive decompression failed')
    started = time.time()
    print('Preparing clean Linux source from locked upstream archive and device overlay', flush=True)
    prepare_source(out)
    (out/'build').mkdir()
    shutil.copyfile(DEVICE/'kernel/current/config', out/'build/.config')
    command = ['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
               '--mount',f'type=bind,src={DEVICE},dst=/device,readonly',
               '--mount',f'type=bind,src={out},dst=/work',
               '-e','KBUILD_BUILD_USER=armada','-e','KBUILD_BUILD_HOST=opd2413-full-system',
               '-e','KBUILD_BUILD_TIMESTAMP=2026-11-08 00:00:00 UTC',
               '-e','KBUILD_BUILD_VERSION=3','-e','LC_ALL=C',image,
               'make','-C','/work/source','O=/work/build','ARCH=arm64',
               'CROSS_COMPILE=aarch64-linux-gnu-',
               'PAHOLE=/device/inputs/local/pahole132/run-pahole']
    commands=[]
    for name, targets in [('configure',['olddefconfig']),('compile',[f'-j{args.jobs}','Image','modules'])]:
        argv=command+targets
        print('Kernel stage: '+name, flush=True)
        with (out/(name+'.log')).open('w') as log:
            result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT)
        commands.append(dict(stage=name,returncode=result.returncode))
        if result.returncode:
            raise RuntimeError('kernel '+name+' failed; see '+str(out/(name+'.log')))
        if name=='configure' and (out/'build/.config').read_bytes()!=(DEVICE/'kernel/current/config').read_bytes():
            raise ValueError('locked kernel configuration changed after olddefconfig')
    canonical=canonicalize_image(out/'build/arch/arm64/boot/Image',out/'Image')
    (out/'image-reproducibility.json').write_text(json.dumps(canonical,indent=2)+'\n')
    result=dict(passed=True,canonical_image_sha256=sha(out/'Image'),source_built_from_clean_upstream=True,old_workspace_not_mounted=True,network_disabled=True,
                compiler_image=image,commands=commands,seconds=time.time()-started,
                kernel_image_sha256=sha(out/'build/arch/arm64/boot/Image'),
                config_sha256=sha(out/'build/.config'),module_count=len(list((out/'build').rglob('*.ko'))),
                exports_sha256=sha(out/'build/Module.symvers'))
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    main()
