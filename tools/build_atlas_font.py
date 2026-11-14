#!/usr/bin/env python3
"""Rebuild the Atlas font from the pinned LXGW WenKai source; requires fonttools/lz4."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = 'https://raw.githubusercontent.com/lxgw/LxgwWenKai/e8b5b48b79f19f29aa68b0a178eab3472ea9f7e8/fonts/TTF/LXGWWenKai-Regular.ttf'
SOURCE_SHA256 = '39ad71264b588165b469e35e6afb162a378dacd1f95348160240ba9038ac3009'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, default=ROOT/'boot/vendor/kshim/src/ui/fonts')
    args = p.parse_args()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA256:
        p.error('source font differs from the pinned LXGW WenKai revision')
    shim = ROOT/'boot/vendor/kshim'
    sources = ['src/core/menu_locale.c', 'src/include/menu_text.h', 'src/ui/menu_atlas.h']
    with tempfile.TemporaryDirectory() as tmp:
        required = Path(tmp)/'atlas-required-text.txt'
        required.write_text(''.join((shim/name).read_text() for name in sources))
        subprocess.run([sys.executable, str(shim/'tools/gen_ui_font.py'),
            '--source', str(args.source.resolve()), '--source-url', SOURCE_URL,
            '--output-stem', 'lxgw_wenkai_atlas', '--license-file',
            str(shim/'src/ui/fonts/lxgw_wenkai_menu-OFL.txt'), '--required-text', str(required),
            '--coverage', 'menu', '--out', str(args.out)], check=True)
    # Do not retain a temporary path as the coverage description.
    import json
    path = args.out/'lxgw_wenkai_atlas.provenance.json'
    info = json.loads(path.read_text())
    info['coverage'] = 'Menu preset plus all characters in ' + ', '.join(sources)
    info['generator'] = 'tools/build_atlas_font.py + boot/vendor/kshim/tools/gen_ui_font.py'
    path.write_text(json.dumps(info, indent=2)+'\n')


if __name__ == '__main__':
    main()
