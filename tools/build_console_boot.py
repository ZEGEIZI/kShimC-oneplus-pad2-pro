#!/usr/bin/env python3
"""Build a reversible text-console candidate from the hash-locked boot29 image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

from boot_contract import align, check_linux_packed
from build_boot import BOOT_SHA, STOCK_SHA
from cpio import assemble, decode, parse as parse_cpio
from dtb import parse as parse_dtb
from host_tools import command

DEVICE = Path(__file__).resolve().parents[1]
MASKS = (
    'armada-splash-initrd.service', 'armada-splash-early.service',
    'armada-splash-stall.service', 'armada-splash-poweroff-screen.service',
    'armada-splash-reboot-screen.service',
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def console_cmdline(original):
    # Keep storage, firmware, clocks, and the split GPU/KMS workaround intact.
    remove = {'console', 'quiet', 'splash', 'loglevel', 'ignore_loglevel',
              'initcall_debug', 'drm.debug', 'gpi.opd2413_boot_trace',
              'qcom_rpmh_regulator.opd2413_boot_observe'}
    words = [w for w in original.split() if w.split('=', 1)[0] not in remove]
    words += ['console=tty1', 'loglevel=7', 'printk.time=1', 'consoleblank=0',
              'systemd.show_status=yes', 'rd.systemd.show_status=yes',
              'systemd.log_level=info', 'rd.systemd.log_level=info',
              'vconsole.font=latarcyrheb-sun32', 'rd.vconsole.font=latarcyrheb-sun32',
              'opd2413.console=1']
    for unit in MASKS:
        words += ['systemd.mask=' + unit, 'rd.systemd.mask=' + unit]
    return ' '.join(words)


def console_dtb(raw):
    properties, nodes, layout = parse_dtb(raw)
    key = '/chosen:bootargs'
    updated = console_cmdline(properties[key].rstrip(b'\0').decode()).encode() + b'\0'
    if len(updated) > 2048:
        raise ValueError('console command line exceeds ARM64 COMMAND_LINE_SIZE')
    pieces = []
    for row in layout['tokens']:
        pieces.append(struct.pack('>I', row['type']))
        if row['type'] == 1:
            pieces += [row['name'].encode() + b'\0', bytes.fromhex(row['padding_hex'])]
        elif row['type'] == 3:
            data = updated if row['key'] == key else properties[row['key']]
            padding = bytes(-len(data) % 4) if row['key'] == key else bytes.fromhex(row['padding_hex'])
            pieces += [struct.pack('>II', len(data), row['index']), data, padding]
    structure = b''.join(pieces) + bytes.fromhex(layout['structure_gap_hex'])
    prefix = bytearray.fromhex(layout['prefix_hex'])
    strings = bytes.fromhex(layout['strings_hex'])
    struct.pack_into('>I', prefix, 4, len(prefix) + len(structure) + len(strings))
    struct.pack_into('>I', prefix, 12, len(prefix) + len(structure))
    struct.pack_into('>I', prefix, 36, len(b''.join(pieces)))
    result = bytes(prefix) + structure + strings
    actual, actual_nodes, _ = parse_dtb(result)
    expected = dict(properties); expected[key] = updated
    if actual != expected or actual_nodes != nodes:
        raise ValueError('candidate changed DT properties beyond bootargs')
    return result


def replace_entry(entries, path, data, mode=None):
    row = next((e for e in entries if e['path'] == path), None)
    if row is None:
        # All candidate additions are ordinary files/directories; no hardlinks.
        inode = max(int(e['header'][6:14], 16) for e in entries) + 1
        fields = [inode, mode or 0o100644, 0, 0, 1, 0, len(data), 0, 0, 0, 0,
                  len(path.encode()) + 1, 0]
        row = dict(path=path, header='070701' + ''.join(f'{x:08x}' for x in fields))
        entries.append(row)
    header = row['header']
    if mode is not None:
        header = header[:14] + f'{mode:08x}' + header[22:]
    row.update(data=data, sha256=sha(data), header=header[:54] + f'{len(data):08x}' + header[62:])


def repack_payloads(packed, stock, dtb, initrd, *, kernel_bytes=None):
    manifest_offset, manifest_bytes, shim_offset = struct.unpack_from('<3Q', packed, 32)
    manifest = bytearray(packed[manifest_offset:manifest_offset + manifest_bytes])
    cursor = 60; rows = []
    for i in range(5):
        off, size = struct.unpack_from('<QQ', manifest, cursor)
        nlen = struct.unpack_from('<I', manifest, cursor + 52)[0]
        rows.append((cursor, off, packed[off:off + size]))
        cursor += align(56 + nlen, 4)
    runtime = rows[4][2]; kernel = rows[1][2]
    check_linux_packed(packed, stock, runtime, 8000, [kernel, rows[2][2], rows[3][2]],
                       payload_names=('Linux 系统（实验）', 'OPD2413 rootfs DTB', 'standard dracut initramfs'))
    if kernel_bytes is not None:
        kernel = kernel_bytes
    payloads = [rows[0][2], kernel, dtb, initrd, runtime]
    image = bytearray()
    for i in sorted(range(5), key=lambda i: rows[i][1]):
        # Preserve the stock/shim/Linux placement (including ARM64 BSS alignment).
        off = rows[i][1] if i in (0, 1, 4) else align(len(image), 1 << (3 if i == 2 else 16))
        if off < len(image):
            raise ValueError('candidate payload overlap')
        image.extend(bytes(off - len(image))); image.extend(payloads[i])
        struct.pack_into('<QQ', manifest, rows[i][0], off, len(payloads[i]))
    new_manifest = align(len(image), 8)
    image.extend(bytes(new_manifest - len(image))); image.extend(manifest)
    struct.pack_into('<Q', image, 16, len(image))
    struct.pack_into('<3Q', image, 32, new_manifest, len(manifest), shim_offset)
    checked = check_linux_packed(bytes(image), stock, runtime, 8000, [kernel, dtb, initrd],
                                payload_names=('Linux 系统（实验）', 'OPD2413 rootfs DTB', 'standard dracut initramfs'))
    return bytes(image), checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True, help='Fresh baseline boot image from build_boot.py')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve()
    if out.exists(): parser.error('output directory must be new')
    reference = args.reference.read_bytes()
    if sha(reference) != BOOT_SHA: raise ValueError('reference is not the verified boot29 image')
    original = (DEVICE / 'inputs/local/stock-android-boot.img').read_bytes()
    if sha(original) != STOCK_SHA: raise ValueError('stock boot hash mismatch')
    stock = original[4096:4096 + struct.unpack_from('<I', original, 8)[0]]
    packed = reference[4096:4096 + struct.unpack_from('<I', reference, 8)[0]]
    offset = struct.unpack_from('<Q', packed, 32)[0]; cursor = offset + 60; payloads = []
    for i in range(5):
        start, size = struct.unpack_from('<QQ', packed, cursor)
        payloads.append(packed[start:start + size])
        cursor += align(56 + struct.unpack_from('<I', packed, cursor + 52)[0], 4)
    # Validate before using any extracted baseline component.
    check_linux_packed(packed, stock, payloads[4], 8000, payloads[1:4],
                       payload_names=('Linux 系统（实验）', 'OPD2413 rootfs DTB', 'standard dracut initramfs'))
    out.mkdir(parents=True)
    source = DEVICE / 'console'
    logger = (DEVICE / 'rootfs/helpers/logger/rootfs_probe.c').read_text()
    logger = logger.replace('#include "probe_board.c"', '#include "probe_board.c"\n#include "/device/console/probe_console.c"')
    logger = logger.replace('else if(!strcmp(command,"board"))', 'else if(!strcmp(command,"console"))console_reply();\n    else if(!strcmp(command,"board"))')
    (out / 'rootfs_probe.c').write_text(logger)
    toolchain = json.loads((DEVICE / 'inputs/toolchain.json').read_text())['image_id']
    base = ['docker', 'run', '--rm', '--network=none', '--user', f'{os.getuid()}:{os.getgid()}',
            '--mount', f'type=bind,src={DEVICE},dst=/device,readonly',
            '--mount', f'type=bind,src={out},dst=/work', toolchain,
            'aarch64-linux-gnu-gcc', '-static', '-Os', '-Wall', '-Wextra', '-Werror']
    subprocess.run(base + ['-o', '/work/text-console', '/device/console/text-console.c'], check=True)
    subprocess.run(base + ['-DDIAG_CPU=1', '-I/device/rootfs/helpers/logger', '-o', '/work/logger',
                           '/work/rootfs_probe.c', '/device/rootfs/helpers/logger/diag_cpu.c'], check=True)
    entries, trailer = parse_cpio(decode(payloads[3]))
    before = {e['path']: e['sha256'] for e in entries}
    replace_entry(entries, 'usr/libexec/armada/opd2413-rootfs-log', (out / 'logger').read_bytes())
    hook = 'var/lib/dracut/hooks/pre-pivot/90-opd2413-input-probe.sh'
    old = next(e['data'] for e in entries if e['path'] == hook)
    if old.count(b'= 781576 ]') != 1: raise ValueError('unknown logger staging hook')
    replace_entry(entries, hook, old.replace(b'= 781576 ]', f'= {(out / "logger").stat().st_size} ]'.encode()))
    replace_entry(entries, 'usr/lib/armada/opd2413-console', b'', 0o40755)
    for name, data, mode in [
        ('text-console', (out / 'text-console').read_bytes(), 0o100755),
        ('opd2413-shutdown-console.service', (source / 'opd2413-shutdown-console.service').read_bytes(), 0o100644),
    ]:
        replace_entry(entries, 'usr/lib/armada/opd2413-console/' + name, data, mode)
    replace_entry(entries, 'var/lib/dracut/hooks/pre-pivot/95-opd2413-console.sh',
                  (source / 'stage-console.sh').read_bytes(), 0o100755)
    raw = assemble(entries, trailer, lambda e: e['data'])
    (out / 'initramfs.cpio').write_bytes(raw)
    print('Compressing candidate initramfs', flush=True)
    with (out / 'initramfs.img').open('wb') as f:
        subprocess.run(command('xz') + ['-9', '--check=crc32', '--threads=1', '--stdout', str(out / 'initramfs.cpio')], stdout=f, check=True)
    initrd = (out / 'initramfs.img').read_bytes()
    after, _ = parse_cpio(decode(initrd))
    if {e['path']: e['sha256'] for e in after} != {e['path']: e['sha256'] for e in entries}:
        raise ValueError('candidate initramfs round trip differs')
    dtb = console_dtb(payloads[2]); (out / 'opd2413-rootfs.dtb').write_bytes(dtb)
    candidate, checked = repack_payloads(packed, stock, dtb, initrd)
    (out / 'PackedKernel').write_bytes(candidate)
    subprocess.run([sys.executable, str(DEVICE / 'tools/repack_boot_v4.py'),
                    '--original', str(args.reference.resolve()), '--kernel', str(out / 'PackedKernel'),
                    '--output', str(out / 'boot.img'), '--report', str(out / 'repack.json'),
                    '--avbtool', str(DEVICE / 'tools/avbtool.py')], check=True)
    subprocess.run(command('img2simg') + [str(out / 'boot.img'), str(out / 'boot.sparse'), '4096'], check=True)
    subprocess.run(command('simg2img') + [str(out / 'boot.sparse'), str(out / 'expanded.img')], check=True)
    boot = (out / 'boot.img').read_bytes()
    if (out / 'expanded.img').read_bytes() != boot: raise ValueError('sparse round trip differs')
    if boot[44:1580] != reference[44:1580]: raise ValueError('Android header command line changed')
    (out / 'expanded.img').unlink()
    report = dict(passed=True, profile='opd2413-text-console-v1', hardware_verified=False,
                  reference_boot_sha256=BOOT_SHA, boot_sha256=sha(boot),
                  sparse_sha256=sha((out / 'boot.sparse').read_bytes()),
                  kernel_and_modules_unchanged=True, stock_Android_restoration_identical=True,
                  Android_default=True, timeout_ms=8000, sparse_round_trip_verified=True,
                  rootfs_changes='RAM only; reference boot restores previous behavior',
                  changed_initrd_entries=[e['path'] for e in entries if before.get(e['path']) != e['sha256']],
                  layout=checked)
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(sha((out / n).read_bytes()) + '  ' + n + '\n' for n in ['boot.img', 'boot.sparse']))
    print(json.dumps({k: v for k, v in report.items() if k != 'layout'}, indent=2))


if __name__ == '__main__':
    main()
