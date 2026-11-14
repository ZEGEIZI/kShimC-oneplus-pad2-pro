"""Bounded newc parsing and exact metadata-preserving archive assembly."""
from pathlib import PurePosixPath
import hashlib
import lzma

MAX_DECODED=256*1024**2


def decode(data):
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=128*1024**2)
    raw=decoder.decompress(data,max_length=MAX_DECODED+1)
    if len(raw)>MAX_DECODED or not decoder.eof or decoder.unused_data:
        raise ValueError('invalid or oversized initramfs XZ stream')
    return raw


def parse(raw):
    entries=[];seen=set();cursor=0
    while cursor<len(raw):
        if raw[cursor:cursor+6]!=b'070701' or cursor+110>len(raw):raise ValueError('invalid newc header')
        header=raw[cursor:cursor+110]
        fields=[int(header[6+i*8:14+i*8],16) for i in range(13)]
        size,nlen=fields[6],fields[11]
        if not nlen or cursor+110+nlen>len(raw):raise ValueError('invalid newc name length')
        name_bytes=raw[cursor+110:cursor+110+nlen]
        if name_bytes[-1:]!=b'\0' or b'\0' in name_bytes[:-1]:raise ValueError('invalid newc filename')
        name=name_bytes[:-1].decode();start=(cursor+110+nlen+3)&~3;end=(start+size+3)&~3
        if end>len(raw):raise ValueError('truncated newc file')
        if name=='TRAILER!!!':
            if size or any(raw[end:]):raise ValueError('invalid newc trailer')
            return entries,raw[cursor:]
        if name in seen or name.startswith('/') or '..' in PurePosixPath(name).parts:raise ValueError('unsafe/duplicate newc path')
        seen.add(name);data=raw[start:start+size]
        entries.append(dict(path=name,mode=fields[1],header=header.decode(),data=data,sha256=hashlib.sha256(data).hexdigest()))
        cursor=end
    raise ValueError('missing newc trailer')


def assemble(records,trailer,provider):
    chunks=[]
    for record in records:
        data=provider(record)
        if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('initramfs content differs: '+record['path'])
        header=record['header'].encode();name=record['path'].encode()+b'\0'
        if int(header[54:62],16)!=len(data):raise ValueError('initramfs size differs: '+record['path'])
        item=header+name;item+=bytes(-len(item)%4);item+=data;item+=bytes(-len(data)%4);chunks.append(item)
    return b''.join(chunks)+trailer
