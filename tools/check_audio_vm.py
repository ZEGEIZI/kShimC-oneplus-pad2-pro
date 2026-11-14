#!/usr/bin/env python3
"""Exercise the maintained PCM override with actual cold ARM64 kmod loads."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from build_console_boot import replace_entry
from cpio import assemble, decode, parse

DEVICE = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel', type=Path, required=True)
    p.add_argument('--initramfs', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); out = a.out.resolve(); kernel = a.kernel.resolve()
    if out.exists(): p.error('output must be new')
    out.mkdir(parents=True)
    hook = (DEVICE/'audio/early-audio.sh').read_text()
    match = re.search(r"cat > (/run/modprobe.d/\S+) <<'CONF'\n(.*?)\nCONF", hook, re.S)
    if not match: raise ValueError('unknown PCM override hook')
    config_path, config = match.groups()
    image = json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    base = ['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
        '--mount',f'type=bind,src={DEVICE},dst=/device,readonly',
        '--mount',f'type=bind,src={kernel},dst=/kernel,readonly',
        '--mount',f'type=bind,src={out},dst=/vm',image]
    subprocess.run(base+['aarch64-linux-gnu-gcc','-static','-Os','-Wall','-Wextra','-Werror',
        '-DGOOD_CONFIG_PATH="'+config_path+'"','/device/tests/audio_cold_pcm.c','-o','/vm/init'],check=True)
    entries,trailer = parse(decode(a.initramfs.read_bytes()))
    def put(path,data,mode=0o100644):
        for directory in reversed([Path(path).parent,*Path(path).parent.parents]):
            if str(directory)!='.': replace_entry(entries,str(directory),b'',0o40755)
        replace_entry(entries,path,data,mode)
    put('init',(out/'init').read_bytes(),0o100755)
    put('vm-pcm.conf',(config+'\n').encode())
    tree=kernel/'stage/lib/modules/7.2.6-opd2413-full-system03'
    for f in tree.rglob('*'):
        if f.is_file(): put('usr/lib/modules/7.2.6-opd2413-full-system03/'+f.relative_to(tree).as_posix(),f.read_bytes())
    (out/'initramfs.gz').write_bytes(gzip.compress(assemble(entries,trailer,lambda e:e['data']),compresslevel=1,mtime=0))
    with (out/'console.log').open('w') as log:
        run=subprocess.run(base+['timeout','70','qemu-system-aarch64','-M','virt,gic-version=3',
            '-cpu','cortex-a76','-smp','4','-m','1024','-nographic','-no-reboot','-nic','none',
            '-kernel','/kernel/Image','-initrd','/vm/initramfs.gz',
            '-append','console=ttyAMA0 rdinit=/init selinux=0 panic=0 loglevel=5'],stdout=log,stderr=subprocess.STDOUT,timeout=80)
    text=(out/'console.log').read_text()
    if run.returncode or 'AUDIO_COLD_PCM_APM_PRM_PASS' not in text or 'AUDIO_COLD_PCM_FAIL' in text:
        raise ValueError('cold PCM VM regression failed; see console.log')
    result=dict(passed=True,actual_arm64_kmod=True,pcm_unloaded_before_fix=True,
        physical_hardware=False,kernel_sha256=hashlib.sha256((kernel/'Image').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'initramfs.gz').unlink(); (out/'init').unlink()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
