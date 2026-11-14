"""Independent ABI/layout and original Android restoration checks."""
import hashlib
import struct
RUNTIME_SIZE=4*1024*1024  # Retained historical memory-payload layout.
EXTERNAL_RUNTIME_SIZE=8*1024*1024
BASE_NAME="原厂 Android"
SHIM_NAME="Attached Shim"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def align(n, boundary):
    return (n + boundary - 1) // boundary * boundary

def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]

def u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]

def check_linux_packed(data, stock, runtime, timeout, payloads, *, payload_names=None, default_index=0):
    require(data[56:60] == b"ARM\x64" and u64(data, 16) == len(data), "invalid packed Linux header")
    require(data[8:16] == stock[8:16] and data[24:32] == stock[24:32], "ARM64 offset/flags changed")
    offset, size, shim = struct.unpack_from("<3Q", data, 32)
    require(offset + size == len(data) and shim == align(max(len(stock), u64(stock, 16)), 4)
            and offset > shim + RUNTIME_SIZE, "invalid Linux manifest bounds")
    require(default_index in (0, 1), "invalid Linux manifest default index")
    require(struct.unpack_from("<IHHIII", data, offset) == (0x464D504B, 0, 1, 5, default_index, timeout), "unexpected Linux manifest header/default")
    backup = struct.unpack_from("<5Q", data, offset + 20)
    require(backup == tuple(u64(stock, p) for p in (0, 16, 32, 40, 48)), "wrong base header backup")
    names = payload_names or ("Linux 诊断模式", "OPD2413 Diagnostic DTB", "RAM diagnostic initramfs")
    require(len(names) == 3 and all(isinstance(name, str) and name for name in names),
            "invalid Linux payload names")
    specs = [(BASE_NAME, 1, 5, 21, 0, stock), (names[0], 1, 12, 21, 2, payloads[0]),
             (names[1], 5, 0, 3, 0, payloads[1]),
             (names[2], 4, 0, 16, 0, payloads[2]), (SHIM_NAME, 3, 4, 2, 0, runtime)]
    cursor, entries = offset + 60, []
    for index, (name, typ, flags, alignment, dtref, content) in enumerate(specs):
        require(cursor + 56 <= len(data), "truncated Linux manifest entry")
        off, length, actual_type, actual_flags, load, entry, dtb, actual_align, copy, nlen = struct.unpack_from("<QQIIQIIIQI", data, cursor)
        end = cursor + align(56 + nlen, 4)
        require(end <= len(data) and data[cursor + 56:cursor + 56 + nlen] == name.encode() and
                not any(data[cursor + 56 + nlen:end]), "Linux entry name mismatch")
        require((length, actual_type, actual_flags, load, entry, dtb, actual_align, copy) ==
                (len(content), typ, flags, 0, 0, dtref, alignment, 0), "Linux entry ABI mismatch")
        require(off + length <= offset, "out-of-bounds Linux payload")
        if index == 0:
            require(off == 0, "base not at zero")
        else:
            require(data[off:off + length] == content, "Linux payload bytes differ")
        if index == 1:
            require(off >= align(max(len(stock), u64(stock, 16)), 4) and
                    (off + u64(stock, 8) - u64(content, 8)) % (1 << 21) == 0, "Linux BSS/alignment conflict")
        elif index > 1:
            require(off % (1 << alignment) == 0, "non-Linux entry alignment mismatch")
        if index == 4:
            require(off == shim, "shim offset mismatch")
        entries.append({"name": name, "offset": off, "bytes": length, "type": typ, "flags": flags, "dtb_index": dtb})
        cursor = end
    previous = 0
    for entry in sorted(entries, key=lambda e: e["offset"]):
        require(entry["offset"] >= previous, "overlapping Linux payloads")
        require(not any(data[previous:entry["offset"]]), "nonzero Linux layout padding")
        previous = entry["offset"] + entry["bytes"]
    require(cursor == len(data) and offset == align(previous, 8) and not any(data[previous:offset]), "Linux trailing layout mismatch")
    require(entries[1]["offset"] >= shim + RUNTIME_SIZE, "Linux overlaps shim slot")
    restored = bytearray(data[:len(stock)])
    for value, pos in zip(backup, (0, 16, 32, 40, 48)):
        struct.pack_into("<Q", restored, pos, value)
    require(bytes(restored) == stock, "Linux layout base restoration differs")
    require(shim < 0x8000000 and u32(data, 0) == 0x94000000 | (shim // 4), "wrong shim branch")
    word = u32(stock, 0)
    expected = ((word & 0xfc000000) | (((word & 0x03ffffff) - 1) & 0x03ffffff)) if word & 0xfc000000 == 0x14000000 else u32(stock, 4)
    require(u32(data, 4) == expected, "base branch differs")
    return {"base_slot_bytes": align(max(len(stock), u64(stock, 16)), 4), "manifest_offset": offset,
            "manifest_bytes": size, "entries": entries, "restored_base_identical": True, "runtime_identical": True}


def check_external_packed(data, base, runtime, timeout, *, debug_payloads=None,
                          runtime_slot_bytes=EXTERNAL_RUNTIME_SIZE):
    """Independent file-source contract; the historical five-entry contract is unchanged."""
    require(data[56:60] == b'ARM\x64' and u64(data,16) == len(data), 'bad packed Image')
    offset, size, shim = struct.unpack_from('<3Q',data,32)
    require(offset+size == len(data) and shim == align(max(len(base),u64(base,16)),4), 'bad manifest/slot')
    require(runtime_slot_bytes in (RUNTIME_SIZE, EXTERNAL_RUNTIME_SIZE), 'unsupported runtime slot')
    require(len(runtime) == runtime_slot_bytes and runtime[56:60] == b'ARM\x64' and
            u64(runtime,16) == runtime_slot_bytes, 'runtime/header/slot size mismatch')
    require(data[shim:shim+len(runtime)] == runtime, 'wrong runtime')
    require(shim < 0x8000000 and u32(data,0) == 0x94000000 | (shim//4), 'wrong shim branch')
    require(data[8:16] == base[8:16] and data[24:32] == base[24:32], 'base load protocol changed')
    expected = 4 if debug_payloads else 2
    require(struct.unpack_from('<IHHIII',data,offset) == (0x464D504B,0,1,expected,0,timeout), 'bad header/default')
    require(struct.unpack_from('<5Q',data,offset+20) == tuple(u64(base,p) for p in (0,16,32,40,48)), 'base restoration mismatch')
    rows = []
    cursor = offset+60
    for i in range(expected):
        require(cursor+56 <= len(data), 'truncated entry')
        off,length,typ,flags,load,entry,dtb,alignment,copy,nlen = struct.unpack_from('<QQIIQIIIQI',data,cursor)
        end = cursor+align(56+nlen,4)
        require(end <= len(data) and 0 < nlen < 256 and off <= offset and length <= offset-off, 'bad entry bounds')
        require(not load and not entry and not copy, 'unexpected relocation')
        name = data[cursor+56:cursor+56+nlen].decode('utf-8')
        rows.append(dict(offset=off,bytes=length,type=typ,flags=flags,dtb_index=dtb,name=name))
        require(2 <= alignment <= 21 and (not i or off % (1<<alignment) == 0), 'bad alignment')
        if i == 0:
            require((off,length,typ,flags,dtb) == (0,len(base),1,13 if debug_payloads else 5,1 if debug_payloads else 0), 'bad base')
        elif i == expected-1:
            require((off,length,typ,flags,dtb) == (shim,len(runtime),3,4,0), 'bad shim')
        else:
            content = debug_payloads[i-1]
            require(off >= shim+runtime_slot_bytes, 'debug payload overlaps reserved shim slot')
            require((length,typ,flags,dtb) == (len(content),5 if i==1 else 4,0,0), 'unexpected debug payload')
            require(data[off:off+length] == content, 'debug payload differs')
        cursor = end
    require(cursor == len(data), 'trailing manifest data')
    restored = bytearray(data[:len(base)])
    for p in (0,16,32,40,48):
        restored[p:p+8] = base[p:p+8]
    require(restored == base, 'base bytes changed')
    previous = 0
    for row in sorted(rows,key=lambda x:x['offset']):
        require(row['offset'] >= previous, 'overlapping payload')
        previous = row['offset']+row['bytes']
    require(offset >= shim+runtime_slot_bytes, 'manifest overlaps reserved shim slot')
    if not debug_payloads:
        # No hidden Linux payload can be appended between the reserved slot
        # and manifest: production consists solely of base, shim and padding.
        require(offset == align(shim+runtime_slot_bytes,4), 'unexpected production payload')
    return dict(entries=rows,linux_embedded=bool(debug_payloads),android_retained=not bool(debug_payloads),
                original_base_restored=True,runtime_slot_bytes=runtime_slot_bytes)
