#!/usr/bin/env python3
"""Regenerate the complete167-module delta bundle against its fixed dictionary."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from host_tools import command

DEVICE=Path(__file__).resolve().parents[1]
RELEASE='7.2.6-opd2413-full-system03'


def digest(data):return hashlib.sha256(data).hexdigest()


def extract_dictionary(destination):
    report=json.loads((DEVICE/'inputs/local/package03-report.json').read_text())
    archive=DEVICE/'inputs/local/package03-kernel.tar.zst'
    if digest(archive.read_bytes())!=report['artifact_sha256']:raise ValueError('package03 archive hash mismatch')
    expected=report['stripped_module_load_identity_verified'];found=set();prefix='lib/modules/'+RELEASE+'/'
    child=subprocess.Popen(command('zstd')+['-q','-d','-c',str(archive)],stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=child.stdout,mode='r|') as source:
            for entry in source:
                if not entry.name.startswith(prefix) or not entry.name.endswith('.ko'):continue
                name=entry.name.removeprefix(prefix)
                if name not in expected or name in found or not entry.isfile():raise ValueError('invalid dictionary module')
                data=source.extractfile(entry).read()
                if digest(data)!=expected[name]['stripped_sha256']:raise ValueError('dictionary module hash mismatch: '+name)
                path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);found.add(name)
        child.stdout.close()
        if child.wait():raise RuntimeError('dictionary decompression failed')
    finally:
        if child.poll() is None:child.terminate();child.wait()
    if found!=set(expected) or len(found)!=164:raise ValueError('dictionary inventory incomplete')
    return expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    out.mkdir(parents=True);dictionary=out/'dictionary';dictionary.mkdir();expected=extract_dictionary(dictionary)
    target=args.modules.resolve()/'stage/lib/modules'/RELEASE
    module_report=json.loads((args.modules/'result.json').read_text())
    if not module_report['passed'] or not module_report['all_modules_byte_identical']:raise ValueError('unverified modules')
    bundle=out/'bundle';bundle.mkdir();rows=[]
    for index,path in enumerate(sorted(p for p in target.rglob('*') if p.is_file())):
        rel=path.relative_to(target).as_posix();data=path.read_bytes();base=dictionary/rel if rel in expected else None
        payload=bundle/('%03d.zst'%index);argv=command('zstd')+['-q','-19','-T1','--stdout']
        if base:argv+=['--patch-from='+str(base)]
        with payload.open('wb') as stream:result=subprocess.run(argv+[str(path)],stdout=stream,stderr=subprocess.PIPE)
        if result.returncode:raise RuntimeError(result.stderr.decode())
        check=command('zstd')+['-q','-d','--stdout']
        if base:check+=['--patch-from='+str(base)]
        rebuilt=subprocess.check_output(check+[str(payload)])
        if rebuilt!=data:raise ValueError('dictionary round trip differs: '+rel)
        rows.append([payload.name,str(base.stat().st_size if base else 0),expected[rel]['stripped_sha256'] if base else '-',str(len(data)),digest(data),str(payload.stat().st_size),digest(payload.read_bytes()),rel])
    manifest='OPD2413_MODULE_DELTA_V1\ncount\t'+str(len(rows))+'\n'+''.join('\t'.join(row)+'\n' for row in rows)
    (bundle/'manifest.tsv').write_text(manifest)
    initrd=json.loads((DEVICE/'boot/initramfs.lock.json').read_text())
    expected_manifest=next(x['sha256'] for x in initrd['entries'] if x['path']=='usr/lib/armada/opd2413-full-modules/bundle/manifest.tsv')
    actual=digest(manifest.encode())
    if actual!=expected_manifest:raise ValueError('regenerated bundle differs from the physically verified29 manifest')
    result=dict(passed=True,files=len(rows),dictionary_modules=len(expected),manifest_sha256=actual,all_payloads_and_manifest_byte_identical=True,all_dictionary_round_trips_verified=True)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
