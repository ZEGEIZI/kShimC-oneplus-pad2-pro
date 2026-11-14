"""ARM64 executable/module identity checks retained from the verified device validators."""
import hashlib
import json
import re
import struct

def module_load_identity(data):
    """Canonical loadable sections and symbol-resolved AArch64 relocations.

    Allows removing DWARF while checking that code/data, exported symbols and
    every relocation applied to an allocated section retain the same meaning.
    """
    assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<HH',data,16)==(1,183)
    offset=struct.unpack_from('<Q',data,40)[0];size,count,index=struct.unpack_from('<HHH',data,58)
    assert size==64 and count and index<count and offset+size*count<=len(data)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)]
    def content(section):
        assert section[4]+section[5]<=len(data)
        return data[section[4]:section[4]+section[5]]
    def string(table,start):
        assert start<len(table);end=table.find(b'\0',start);assert end>=start
        return table[start:end].decode()
    names_table=content(sections[index]);names=[string(names_table,s[0]) for s in sections]
    def sym(table,number):
        assert table[9]==24 and (number+1)*24<=table[5]
        name,info,other,section,value,length=struct.unpack_from('<IBBHQQ',data,table[4]+number*24)
        symbol_name=string(content(sections[table[6]]),name)
        target=names[section] if 0<section<count else '@'+str(section)
        return [symbol_name,info,other,target,value,length]
    allocated={};relocations=[];exports=[]
    for i,s in enumerate(sections):
        if s[2]&2:
            allocated[names[i]]=[s[1],s[2],s[5],s[8],hashlib.sha256(content(s)).hexdigest() if s[1]!=8 else 'NOBITS']
        if s[1] in (4,9) and sections[s[7]][2]&2:
            assert s[1]==4 and s[9]==24 and not s[5]%24
            table=sections[s[6]]
            for pos in range(s[4],s[4]+s[5],24):
                where,info,addend=struct.unpack_from('<QQq',data,pos)
                relocations.append([names[s[7]],where,info&0xffffffff,sym(table,info>>32),addend])
        if s[1]==2:
            assert s[9]==24 and not s[5]%24
            for n in range(s[5]//24):
                item=sym(s,n)
                if item[1]>>4 in (1,2):exports.append(item)
    result={'allocated':allocated,'relocations':sorted(relocations),'exports':sorted(exports)}
    return hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def elf_module_info(data):
    assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<HH',data,16)==(1,183),'Native module must be ARM64 ET_REL'
    assert struct.unpack_from('<H',data,56)[0]==0,'Module has unexpected program headers'
    offset=struct.unpack_from('<Q',data,40)[0];size,count,names=struct.unpack_from('<HHH',data,58)
    assert size==64 and 0<count<512 and names<count and offset+size*count<=len(data),'Invalid module section table'
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)]
    def content(section):
        assert section[4]+section[5]<=len(data),'Module section outside file'
        return data[section[4]:section[4]+section[5]]
    strings=content(sections[names])
    def section_name(section):
        index=section[0];assert index<len(strings)
        end=strings.find(b'\0',index);assert end>=index
        return strings[index:end].decode()
    named={section_name(s):s for s in sections}
    assert '.modinfo' in named and '.gnu.linkonce.this_module' in named,'Missing Linux module metadata'
    info={}
    for item in content(named['.modinfo']).split(b'\0'):
        if not item:continue
        key,sep,value=item.partition(b'=');assert sep
        info.setdefault(key.decode(),[]).append(value.decode())
    for key in ['name','vermagic','depends']:assert len(info[key])==1,'Ambiguous module '+key
    return {key:info[key][0] for key in ['name','vermagic','depends']}

def static_arm64(data):
    assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<HH',data,16)==(2,183),'Worker must be static ARM64 ELF'
    off=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
    assert size==56 and 0<count<128 and off+size*count<=len(data)
    types=[struct.unpack_from('<I',data,off+i*size)[0] for i in range(count)]
    assert 1 in types and not set(types)&{2,3},'Worker has dynamic dependencies'


def canonical_module_build_id(data):
    """Clear only a validated allocated GNU build-ID descriptor for comparison."""
    raw=bytearray(data)
    offset=struct.unpack_from('<Q',raw,40)[0]
    size,count,index=struct.unpack_from('<HHH',raw,58)
    sections=[struct.unpack_from('<IIQQQQIIQQ',raw,offset+i*size) for i in range(count)]
    names=sections[index];strings=raw[names[4]:names[4]+names[5]]
    found=[]
    for section in sections:
        name=strings[section[0]:strings.find(b'\0',section[0])].decode()
        if name!='.note.gnu.build-id':continue
        if section[1]!=7 or section[5]!=36 or raw[section[4]:section[4]+16]!=bytes.fromhex('040000001400000003000000474e5500'):
            raise ValueError('unsupported GNU build-ID note')
        found.append((section[4]+16,bytes(raw[section[4]+16:section[4]+36])))
        raw[section[4]+16:section[4]+36]=bytes(20)
    if len(found)!=1:raise ValueError('expected exactly one module GNU build-ID')
    return bytes(raw),found[0]
