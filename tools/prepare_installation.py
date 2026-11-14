#!/usr/bin/env python3
"""Materialize the verified initial install bundle plus the rebuilt29 update."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--boot',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    if not json.loads((args.boot/'result.json').read_text())['passed']:raise ValueError('unverified boot29')
    locked=json.loads((DEVICE/'inputs/installation.json').read_text());out.mkdir(parents=True)
    for row in locked['files']:
        source=DEVICE/row['source'] if row.get('provider')=='source' else DEVICE/'inputs/local/installation'/row['path']
        with source.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=row['sha256']:raise ValueError('installation input differs: '+row['path'])
        target=out/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['cp','--reflink=auto','--sparse=always',str(source),str(target)],check=True)
    sys.path.insert(0,str(DEVICE/'rootfs/install-tools'));tool=importlib.import_module('manual_gpt')
    bundle=tool.load_bundle(out/'gpt/factory',out/'gpt/candidate',out/'gpt/layout-128gib.json');review=tool.final_admission(out/'final-review.json',bundle)
    # Keep the historical GPT review bound to its exact initial boot. The29
    # update is a separate package and does not change filesystem/GPT content.
    update=out/'update29';update.mkdir()
    for name in ['boot.img','boot.sparse','result.json']:shutil.copyfile(args.boot/name,update/name)
    shutil.copyfile(DEVICE/'INSTALLATION.md',out/'CURRENT-INSTALLATION.md')
    result=dict(passed=True,original_reviewed_installation_bundle_verified=True,current29_update_verified=True,files=len(locked['files']),device_access=False,GPT_changed=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
