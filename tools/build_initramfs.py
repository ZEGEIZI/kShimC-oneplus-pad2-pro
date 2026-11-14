#!/usr/bin/env python3
"""Assemble the verified dracut runtime from source-built device components."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from cpio import assemble, decode, parse
from host_tools import command

DEVICE=Path(__file__).resolve().parents[1]
RELEASE='7.2.6-opd2413-full-system03'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['modules','bundle','helpers','plasma','out']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    for name in ['modules','bundle','helpers','plasma']:
        if not json.loads((getattr(args,name)/'result.json').read_text())['passed']:
            raise ValueError('component has not passed: '+name)
    out.mkdir(parents=True);locked=json.loads((DEVICE/'boot/initramfs.lock.json').read_text())
    roots={'overlay':DEVICE/'rootfs/overlay','runtime':DEVICE/'inputs/local/initrd-runtime', 'source':DEVICE/'boot/initrd-overlay',
           'firmware':DEVICE/'inputs/local/firmware','module':args.modules/'stage/lib/modules'/RELEASE,
           'bundle':args.bundle/'bundle','helper':args.helpers,'plasma-plugin':args.plasma}
    def content(row):
        return bytes.fromhex(row['value']) if row['provider']=='inline' else (roots[row['provider']]/row['value']).read_bytes()
    raw=assemble(locked['entries'],bytes.fromhex(locked['trailer_hex']),content)
    if hashlib.sha256(raw).hexdigest()!=locked['uncompressed_sha256']:raise ValueError('newc archive differs')
    path=out/'initramfs.cpio';path.write_bytes(raw)
    subprocess.run(command('xz')+['-9e','--check=crc32','--threads=1','--keep',str(path)],check=True)
    image=out/'initramfs.img';(out/'initramfs.cpio.xz').rename(image)
    if hashlib.sha256(image.read_bytes()).hexdigest()!=locked['compressed_sha256']:raise ValueError('compressed initrd differs')
    entries,_=parse(decode(image.read_bytes()))
    result=dict(passed=True,entries=len(entries),initramfs_sha256=locked['compressed_sha256'],uncompressed_sha256=locked['uncompressed_sha256'],source_built_device_components=True,byte_identical=True)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
