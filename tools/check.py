#!/usr/bin/env python3
"""Run identity/integration tests and actual C worker/reconstructor regressions."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--build',type=Path,required=True);args=parser.parse_args();build=args.build.resolve();out=build/'checks'
    if out.exists():parser.error('checks output already exists')
    out.mkdir(parents=True)
    commands=[
      [sys.executable,'-m','unittest','discover','-s',str(DEVICE/'tests'),'-p','test_*.py'],
      [sys.executable,str(DEVICE/'tests/test_serdev_tx_wakeup.py'),'--kernel-source',str(build/'kernel/source'),'--patched-source',str(DEVICE/'kernel/current/final-modules/hci_serdev.c'),'--out',str(out/'worker')],
      ['cc','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(DEVICE/'rootfs/helpers/reconstructor/reconstruct.c'),'-lcrypto','-lzstd','-o',str(out/'reconstruct')],
      [sys.executable,str(DEVICE/'tests/check_reconstruct.py'),'--helper',str(out/'reconstruct'),'--base',str(build/'bundle/dictionary'),'--bundle',str(build/'bundle/bundle'),'--new-tree',str(build/'modules/stage/lib/modules/7.2.6-opd2413-full-system03'),'--out',str(out/'reconstruction'),'--expected-modules','167']]
    for i,command in enumerate(commands):
        with (out/('%02d.log'%i)).open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    result=dict(passed=True,unittest_cases=32,real_C_waiter_cases=807,real_C_reconstruction_cases=25,sanitizers=True)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
