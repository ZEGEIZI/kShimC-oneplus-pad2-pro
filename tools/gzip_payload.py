"""Compile the small native packager and use the locked zlib-ng/loader closure."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
DEVICE=Path(__file__).resolve().parents[1]


def build(output):
    image=json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    argv=['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
          '--mount',f'type=bind,src={DEVICE},dst=/device,readonly',
          '--mount',f'type=bind,src={output.resolve()},dst=/work',image,
          'gcc','-O2','-Wall','-Wextra','-Werror','/device/tools/gzip_payload.c',
          '-I/device/inputs/local/host-tools/include',
          '-L/device/inputs/local/host-tools/lib','-Wl,-rpath-link,/device/inputs/local/host-tools/lib',
          '-l:libz.so.1','-o','/work/gzip-payload']
    q=subprocess.run(argv,capture_output=True,text=True)
    (output/'gzip-build.log').write_text(q.stdout+q.stderr);q.check_returncode()
    return output/'gzip-payload'


def compress(helper,source):
    locked=json.loads((DEVICE/'inputs/host-tools.json').read_text());root=DEVICE/'inputs/local/host-tools'
    for name in ['libz.so.1','libc.so.6',Path(locked['loader']).name]:
        if hashlib.sha256((root/'lib'/name).read_bytes()).hexdigest()!=locked['libraries'][name]:raise ValueError('compression runtime differs: '+name)
    return subprocess.check_output([str(root/locked['loader']),'--library-path',str(root/'lib'),str(helper.resolve()),str(source.resolve())])
