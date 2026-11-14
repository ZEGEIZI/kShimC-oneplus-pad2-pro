#!/usr/bin/env python3
"""Verify immutable local inputs without reading private per-device identity."""
import hashlib
import json
import os
from pathlib import Path
DEVICE=Path(__file__).resolve().parents[1]


def main():
    locked=json.loads((DEVICE/'inputs/files.lock.json').read_text());root=DEVICE/'inputs/local'
    for row in locked['files']:
        path=root/row['path']
        if 'symlink' in row:
            if not path.is_symlink() or os.readlink(path)!=row['symlink']:raise ValueError('input link differs: '+row['path'])
        else:
            if path.is_symlink() or path.stat().st_size!=row['bytes']:raise ValueError('input size/type differs: '+row['path'])
            with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
            if actual!=row['sha256']:raise ValueError('input hash differs: '+row['path'])
    source=json.loads((DEVICE/'source.lock.json').read_text())
    for row in source['files']:
        path=DEVICE/row['path']
        if 'symlink' in row:
            if not path.is_symlink() or os.readlink(path)!=row['symlink']:raise ValueError('source link differs: '+row['path'])
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('source hash differs: '+row['path'])
    print('Verified %d immutable local inputs; private identity excluded.'%len(locked['files']),flush=True)

if __name__=='__main__':main()
