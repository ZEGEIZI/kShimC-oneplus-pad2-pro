#!/usr/bin/env python3
"""Register the pinned ARM64 build emulator transiently; invoke through run0."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
DEVICE=Path(__file__).resolve().parents[1]


def main():
    if os.geteuid()!=0:raise SystemExit('Use run0 python3 '+str(Path(__file__).resolve()))
    lock=json.loads((DEVICE/'inputs/qemu-user.json').read_text());source=DEVICE/'inputs/local/qemu-aarch64-static'
    expected=lock.get('sha256') or lock.get('binary_sha256')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('QEMU input hash differs')
    runtime=Path('/run/armada-opd2413-repro');runtime.mkdir(mode=0o755,exist_ok=True)
    if runtime.is_symlink() or runtime.stat().st_uid!=0:raise ValueError('invalid runtime directory')
    target=runtime/'qemu-aarch64-static'
    if target.is_symlink():raise ValueError('invalid interpreter destination')
    shutil.copyfile(source,target);target.chmod(0o755)
    fs=Path('/proc/sys/fs/binfmt_misc')
    if not (fs/'register').exists():subprocess.run(['mount','-t','binfmt_misc','binfmt_misc',str(fs)],check=True)
    entry=fs/'qemu-opd2413-repro'
    if entry.exists():entry.write_text('-1')
    magic='7f454c460201010000000000000000000200b700';mask='ffffffffffffff000000000000000000feffffff'
    if len(bytes.fromhex(magic))!=len(bytes.fromhex(mask)):raise ValueError('binfmt magic/mask length mismatch')
    escaped=lambda value:''.join('\\x'+value[i:i+2] for i in range(0,len(value),2))
    (fs/'register').write_text(':qemu-opd2413-repro:M::'+escaped(magic)+':'+escaped(mask)+':'+str(target)+':F')
    print(entry.read_text())

if __name__=='__main__':main()
