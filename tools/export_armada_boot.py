#!/usr/bin/env python3
"""Export the exact Linux payloads from the retained ArmadaOS five-entry boot."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from boot_contract import check_linux_packed
from dtb import parse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--boot', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    raw = a.boot.read_bytes()
    if raw[:8] != b'ANDROID!' or struct.unpack_from('<I',raw,40)[0] != 4:
        raise ValueError('Expected an ArmadaOS Android v4 boot image')
    size = struct.unpack_from('<I',raw,8)[0]
    if 4096+size > len(raw):
        raise ValueError('Truncated boot image')
    packed = raw[4096:4096+size]
    offset, length, shim = struct.unpack_from('<3Q',packed,32)
    if offset > len(packed) or length != len(packed)-offset or length < 60:
        raise ValueError('Invalid manifest bounds')
    magic, major, minor, count, default, timeout = struct.unpack_from('<IHHIII',packed,offset)
    if (magic,major,minor,count) != (0x464D504B,0,1,5):
        raise ValueError('Only the retained five-entry memory-payload layout is supported')
    contents, names = [], []
    cursor = offset+60
    for i in range(count):
        if cursor+56 > len(packed):
            raise ValueError('Truncated manifest')
        off,n,typ,flags,load,entry,dtref,alignment,copy,nlen = struct.unpack_from('<QQIIQIIIQI',packed,cursor)
        if off > offset or n > offset-off or not 0 < nlen < 256 or cursor+56+nlen > len(packed):
            raise ValueError('Invalid entry bounds')
        contents.append(packed[off:off+n])
        names.append(packed[cursor+56:cursor+56+nlen].decode())
        cursor += (56+nlen+3)&~3
    base = bytearray(contents[0])
    backup = struct.unpack_from('<5Q',packed,offset+20)
    for at,value in zip((0,16,32,40,48),backup):
        struct.pack_into('<Q',base,at,value)
    contract = check_linux_packed(packed,base,contents[4],timeout,contents[1:4],payload_names=names[1:4],default_index=default)
    properties, _, _ = parse(contents[2])
    cmdline = properties['/chosen:bootargs']
    if not cmdline.endswith(b'\0') or b'\0' in cmdline[:-1]:
        raise ValueError('Invalid command line')
    out = a.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    files = {}
    for name,content in zip(('Image','board.dtb','initramfs.img','cmdline.txt'),(*contents[1:4],cmdline[:-1]+b'\n')):
        (out/name).write_bytes(content)
        files[name] = dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    result = dict(passed=True,boot_sha256=hashlib.sha256(raw).hexdigest(),files=files,source_contract=contract,
                  note='Exports actual packed payloads, including final initramfs overlays. Does not regenerate initramfs/modules/OSTree deployments.')
    (out/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(files,indent=2))


if __name__ == '__main__':
    main()
