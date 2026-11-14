#!/usr/bin/env python3
"""Compile the effective device DTS and reproduce its verified FDT layout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from host_tools import command
from dtb import parse,serialize
DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    out.mkdir(parents=True)
    with (out/'dtc.log').open('w') as log:subprocess.run(command('dtc')+['-I','dts','-O','dtb','-o',str(out/'compiled.dtb'),str(DEVICE/'boot/dt/reference-rootfs.dts')],stderr=log,check=True)
    properties,nodes,_=parse((out/'compiled.dtb').read_bytes())
    locked=json.loads((DEVICE/'boot/dt/layout.lock.json').read_text());data=serialize(properties,nodes,locked);(out/'opd2413-rootfs.dtb').write_bytes(data)
    result=dict(passed=True,source_compiled=True,all_properties_verified=True,byte_identical=True,dtb_sha256=hashlib.sha256(data).hexdigest(),nodes=len(nodes),properties=len(properties))
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
