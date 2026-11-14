"""Read flattened DTs and retain their nonsemantic serialization layout."""
import hashlib
import struct


def parse(raw):
    if len(raw)<40:raise ValueError('truncated FDT')
    magic,total,structure,strings,reserve,version,last,cpu,nstrings,nstructure=struct.unpack_from('>10I',raw)
    if magic!=0xd00dfeed or total!=len(raw) or structure+nstructure>strings or strings+nstrings>total:raise ValueError('unsupported FDT layout')
    table=raw[strings:strings+nstrings];position=structure;stack=[];tokens=[];properties={};nodes=set()
    while position<structure+nstructure:
        token=struct.unpack_from('>I',raw,position)[0];position+=4
        if token==1:
            end=raw.index(0,position);name=raw[position:end].decode();padding=raw[end+1:(end+4)&~3];position=(end+4)&~3;stack.append(name);node='/'.join(stack) or '/';nodes.add(node);tokens.append(dict(type=token,name=name,padding_hex=padding.hex()))
        elif token==2:
            stack.pop();tokens.append(dict(type=token))
        elif token==3:
            size,index=struct.unpack_from('>II',raw,position);position+=8
            end=table.index(0,index);name=table[index:end].decode();path='/'.join(stack) or '/';key=path+':'+name
            if key in properties:raise ValueError('duplicate FDT property')
            data=raw[position:position+size];padding=raw[position+size:(position+size+3)&~3];properties[key]=data;position=(position+size+3)&~3
            tokens.append(dict(type=token,key=key,size=size,index=index,padding_hex=padding.hex(),sha256=hashlib.sha256(data).hexdigest()))
        elif token==4:tokens.append(dict(type=token))
        elif token==9:
            tokens.append(dict(type=token));break
        else:raise ValueError('invalid FDT token')
    return properties,nodes,dict(prefix_hex=raw[:structure].hex(),strings_hex=raw[strings:].hex(),structure_gap_hex=raw[position:strings].hex(),tokens=tokens,dtb_sha256=hashlib.sha256(raw).hexdigest())


def serialize(properties,nodes,layout):
    expected={x['key'] for x in layout['tokens'] if x['type']==3}
    if set(properties)!=expected:raise ValueError('DTS property inventory differs')
    chunks=[];stack=[];seen=set()
    for row in layout['tokens']:
        kind=row['type'];chunks.append(struct.pack('>I',kind))
        if kind==1:
            stack.append(row['name']);seen.add('/'.join(stack) or '/');data=row['name'].encode()+b'\0';chunks.append(data+bytes.fromhex(row['padding_hex']))
        elif kind==2:stack.pop()
        elif kind==3:
            data=properties[row['key']]
            if len(data)!=row['size'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('DTS property differs: '+row['key'])
            chunks.extend([struct.pack('>II',len(data),row['index']),data,bytes.fromhex(row['padding_hex'])])
    if seen!=nodes:raise ValueError('DTS node inventory differs')
    data=bytes.fromhex(layout['prefix_hex'])+b''.join(chunks)+bytes.fromhex(layout['structure_gap_hex'])+bytes.fromhex(layout['strings_hex'])
    if hashlib.sha256(data).hexdigest()!=layout['dtb_sha256']:raise ValueError('DT serialization differs')
    return data
