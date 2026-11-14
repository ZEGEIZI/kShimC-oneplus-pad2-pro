#!/usr/bin/env python3
"""Rebuild the two actually deployed Plasma Mobile compatibility plugins."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from host_tools import command
from gzip_payload import build as build_gzip, compress as gzip_compress

DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    out.mkdir(parents=True);(out/'source').mkdir();(out/'logs').mkdir();(out/'outputs').mkdir()
    locked=json.loads((DEVICE/'rootfs/plasma/inputs.json').read_text());source=DEVICE/locked['source_archive']
    if hashlib.sha256(source.read_bytes()).hexdigest()!=locked['source_archive_sha256']:raise ValueError('Plasma upstream archive hash mismatch')
    with tarfile.open(source,'r:xz') as archive:archive.extractall(out/'source',filter='data')
    tree=out/'source/plasma-mobile-6.7.5'
    for name,digest in sorted(locked['patch_sha256'].items()):
        patch=DEVICE/'rootfs/plasma/patches'/name
        if hashlib.sha256(patch.read_bytes()).hexdigest()!=digest:raise ValueError('Plasma patch hash mismatch')
        q=subprocess.run(['patch','--fuzz=0','-p1','-i',str(patch)],cwd=tree,capture_output=True,text=True)
        (out/'logs'/('patch-'+name+'.log')).write_text(q.stdout+q.stderr);q.check_returncode()
    for name,digest in locked['modified_qml_sha256'].items():
        if hashlib.sha256((tree/name).read_bytes()).hexdigest()!=digest:raise ValueError('patched Plasma QML differs')
    # Qt embeds source modification times in its QML cache.
    for name,mtime in locked['source_mtime_ns'].items():
        os.utime(tree/name, ns=(mtime,mtime))
    builder=json.loads((DEVICE/'inputs/plasma-builder.json').read_text());image=builder['image_id']
    if subprocess.run(['podman','image','exists',image]).returncode:
        path=DEVICE/'inputs'/builder['archive']
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=builder['archive_sha256']:raise ValueError('Plasma builder archive hash mismatch')
        child=subprocess.Popen(command('zstd')+['-q','-d','-c',str(path)],stdout=subprocess.PIPE)
        subprocess.run(['podman','load'],stdin=child.stdout,check=True);child.stdout.close()
        if child.wait():raise RuntimeError('Plasma builder archive decompression failed')
    argv=['podman','run','--rm','--network=none','--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}',
          '--volume',str(DEVICE)+':/device:ro','--volume',str(out)+':/diag',image,'python3','/device/tools/build_plasma_inner.py']
    with (out/'container.log').open('w') as stream:q=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT)
    if q.returncode:raise RuntimeError('Plasma container build failed; see '+str(out/'container.log'))
    helper=build_gzip(out)
    initrd=json.loads((DEVICE/'boot/initramfs.lock.json').read_text());records=[]
    for name in ['panel','taskpanel']:
        source=out/'outputs'/('org.kde.plasma.mobile.'+name+'.so')
        raw=source.read_bytes();compressed=gzip_compress(helper,source)
        expected=next(x['sha256'] for x in initrd['entries'] if x['provider']=='plasma-plugin' and x['value']==name+'.so.gz')
        actual=hashlib.sha256(compressed).hexdigest()
        if actual!=expected:raise ValueError(name+' rebuilt plugin differs: '+actual)
        (out/(name+'.so.gz')).write_bytes(compressed);records.append(dict(name=name,plugin_sha256=hashlib.sha256(raw).hexdigest(),compressed_sha256=actual,byte_identical=True))
    result=dict(passed=True,source_rebuilt=True,old_build_not_mounted=True,network_disabled=True,plugins=records)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
