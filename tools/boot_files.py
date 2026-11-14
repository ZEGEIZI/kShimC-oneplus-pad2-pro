#!/usr/bin/env python3
"""Publish versioned Linux boot files. Does not write Android boot partitions."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import uuid

FILE_MAX = 128 * 1024 * 1024
TOTAL_MAX = 256 * 1024 * 1024
DTB_MAX = 1024 * 1024
CONFIG_MAX = 8192
ID = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,62}\Z')


def identifier(value):
    if not ID.fullmatch(value) or value == 'none':
        raise ValueError('Invalid system/version identifier')
    return value


def plain(value, limit):
    if not value or len(value.encode()) >= limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid or oversized text field')
    return value


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def directory(path):
    if path.is_symlink():
        raise ValueError('Symlink directory refused: ' + str(path))
    path.mkdir(exist_ok=True)
    if not path.is_dir():
        raise ValueError('Not a directory: ' + str(path))
    sync_dir(path.parent)
    return path


def atomic_text(path, text):
    fd, name = tempfile.mkstemp(prefix='.config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_config(path, keys, optional=(), formats=('1',)):
    if path.is_symlink() or path.stat().st_size > CONFIG_MAX:
        raise ValueError('Invalid configuration file')
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        k, sep, v = line.partition('=')
        if not sep or not v or k in result or k not in (*keys, *optional):
            raise ValueError('Invalid configuration')
        result[k] = v
    if not set(keys) <= set(result) or result['format'] not in formats:
        raise ValueError('Unsupported/incomplete configuration')
    return result


def root(args):
    if args.staging_root:
        p = args.staging_root.absolute()
        if p.is_symlink() or p.is_mount() or p.resolve() == Path('/boot'):
            raise ValueError('Use a plain offline staging directory')
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()
    p = args.boot_dir.absolute()
    if p.is_symlink() or p.resolve() != p or not args.partuuid:
        raise ValueError('Use a real mountpoint and explicitly specify --partuuid')
    # An unmounted /boot, a bind of a subdirectory, the wrong partition, a
    # read-only mount or another filesystem must fail before creating files.
    data = json.loads(subprocess.check_output([
        'findmnt', '--json', '--mountpoint', str(p), '-o',
        'TARGET,SOURCE,FSTYPE,OPTIONS,PARTUUID,FSROOT'], text=True))['filesystems']
    if len(data) != 1:
        raise ValueError('Expected exactly one boot mount')
    m = data[0]
    if (m['target'] != str(p) or m['fstype'] != 'ext4' or m['fsroot'] != '/' or
            (m.get('partuuid') or '').lower() != str(uuid.UUID(args.partuuid)) or
            (getattr(args, 'action', None) != 'list' and 'rw' not in m['options'].split(','))):
        raise ValueError('Boot mount is not the requested writable ext4 partition')
    return p


@contextlib.contextmanager
def locked(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Invalid lock file')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def copy_file(source, dest, kind):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= FILE_MAX:
            raise ValueError('Invalid/oversized ' + kind)
        h = hashlib.sha256()
        with os.fdopen(os.dup(fd), 'rb') as src, dest.open('xb') as dst:
            header = src.read(64)
            if kind == 'image':
                if len(header) != 64 or header[56:60] != b'ARM\x64':
                    raise ValueError('Expected uncompressed ARM64 Image')
                offset, memory_size, flags = struct.unpack_from('<QQQ', header, 8)
                if not memory_size or memory_size > TOTAL_MAX or offset >= 0x200000 or offset % 65536 or flags & ~14:
                    raise ValueError('Unsupported ARM64 Image header')
            if kind == 'dtb':
                if len(header) < 40 or header[:4] != b'\xd0\x0d\xfe\xed' or struct.unpack_from('>I', header, 4)[0] != before.st_size or before.st_size > DTB_MAX:
                    raise ValueError('Expected a complete DTB (max 1 MiB)')
            dst.write(header)
            h.update(header)
            for chunk in iter(lambda: src.read(1024*1024), b''):
                dst.write(chunk)
                h.update(chunk)
            if dst.tell() != before.st_size:
                raise ValueError('Source size changed during copy')
            dst.flush()
            os.fsync(dst.fileno())
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Source changed during copy')
        if hashlib.sha256(dest.read_bytes()).hexdigest() != h.hexdigest():
            raise ValueError('Published copy failed verification')
        return before.st_size, h.hexdigest()
    finally:
        os.close(fd)


def versions(system):
    path = system/'entries.conf'
    if not path.exists():
        return None
    result = read_config(path, ('format', 'current', 'previous'),
                         optional=('versions',), formats=('1', '2'))
    identifier(result['current'])
    if result['previous'] != 'none':
        identifier(result['previous'])
        if result['previous'] == result['current']:
            raise ValueError('Current and previous must be different versions')
    if result['format'] == '1':
        if 'versions' in result:
            raise ValueError('Format 1 does not have a versions list')
        result['versions'] = [result['current']]
        if result['previous'] != 'none':
            result['versions'].append(result['previous'])
    else:
        result['versions'] = version_list(result.get('versions', ''))
        if result['current'] not in result['versions'] or (
                result['previous'] != 'none' and result['previous'] not in result['versions']):
            raise ValueError('Current and previous must be included in versions')
    return result


def version_list(value):
    values = value.split(',')
    if len(set(values)) != len(values):
        raise ValueError('Expected unique versions')
    for item in values:
        identifier(item)
    return values


def entries_config(current, previous, listed):
    version_list(','.join(listed))
    if current not in listed or current == previous or (previous != 'none' and previous not in listed):
        raise ValueError('Invalid current/previous/menu selection')
    text = f'format=2\ncurrent={current}\nprevious={previous}\nversions={",".join(listed)}\n'
    if len(text.encode()) > CONFIG_MAX:
        raise ValueError('entries.conf exceeds the loader configuration size limit')
    return text


def write_versions(system, current, previous, listed):
    # All callers hold the system lock. Switch the menu and both aliases
    # in one atomic replacement.
    atomic_text(system/'entries.conf', entries_config(current, previous, listed))


def existing_system(boot, system_id):
    system = boot/'kshim'/'systems'/identifier(system_id)
    for path in (boot/'kshim', system.parent, system, system/'versions'):
        if path.is_symlink() or not path.is_dir():
            raise ValueError('Invalid system path')
    return system


def version_manifest(system, version, verify_payloads=True):
    identifier(version)
    folder = system/'versions'/version
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Missing version directory')
    keys = ('format', 'system_id', 'title', 'boot_id', 'kernel_release', 'device',
            'image', 'image_size', 'image_sha256', 'dtb', 'dtb_size', 'dtb_sha256',
            'initrd', 'cmdline')
    result = read_config(folder/'manifest.conf', keys, optional=('initrd_size', 'initrd_sha256'))
    if result['system_id'] != system.name or result['boot_id'] != version or result['device'] != 'oneplus,opd2413':
        raise ValueError('Version manifest identity mismatch')
    external = result['initrd'] != 'none'
    if len(result) != (16 if external else 14):
        raise ValueError('Incomplete version manifest')
    if not verify_payloads:
        return result
    for kind in ('image', 'dtb', 'initrd') if external else ('image', 'dtb'):
        name = result[kind]
        if len(name.encode()) >= 512 or any(p in ('', '.', '..') for p in name.split('/')):
            raise ValueError('Invalid version payload path')
        path = folder
        for component in name.split('/'):
            path = path/component
            if path.is_symlink():
                raise ValueError('Symlink version payload refused')
        size, digest = result[kind+'_size'], result[kind+'_sha256']
        if (not re.fullmatch(r'[0-9]+', size) or not 0 < int(size) <= FILE_MAX or
                not re.fullmatch(r'[0-9a-f]{64}', digest) or not path.is_file() or
                path.stat().st_size != int(size)):
            raise ValueError('Invalid version payload metadata')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != digest:
            raise ValueError('Version payload hash mismatch')
    return result


def publish(args, boot):
    system_id, boot_id = identifier(args.system), identifier(args.version)
    title = plain(args.title, 96)
    release = plain(args.kernel_release, 128)
    cmdline = plain(args.cmdline_file.read_text().rstrip('\n'), 4096)
    kshim = directory(boot/'kshim')
    systems = directory(kshim/'systems')
    system = directory(systems/system_id)
    store = directory(system/'versions')
    with locked(system/'.update.lock'):
        old = versions(system)
        final = store/boot_id
        if final.exists() or final.is_symlink():
            raise ValueError('Version exists; publish a NEW boot version ID')
        listed = [boot_id] + (old['versions'] if old else [])
        previous = old['current'] if old else 'none'
        config = entries_config(boot_id, previous, listed)
        sources = [('image', args.image, 'Image'), ('dtb', args.dtb, 'board.dtb')]
        if args.initrd:
            sources.append(('initrd', args.initrd, 'initramfs.img'))
        required = sum(p.stat().st_size for _, p, _ in sources)
        if required > TOTAL_MAX or shutil.disk_usage(boot).free < required + 8*1024*1024:
            raise ValueError('Insufficient boot space / total payload limit exceeded')
        temporary = Path(tempfile.mkdtemp(prefix='.version-', dir=store))
        try:
            fields = dict(format='1', system_id=system_id, title=title, boot_id=boot_id,
                          kernel_release=release, device='oneplus,opd2413')
            for key, source, name in sources:
                size, sha = copy_file(source, temporary/name, key)
                fields.update({key: name, key+'_size': str(size), key+'_sha256': sha})
            # Image.image_size includes runtime BSS and can exceed the file
            # length. Match the loader's total memory admission before making
            # this version visible or changing the previous working selection.
            with (temporary/'Image').open('rb') as image:
                image_memory = struct.unpack_from('<Q', image.read(64), 16)[0]
            memory_bytes = (max(image_memory, int(fields['image_size'])) +
                            int(fields['dtb_size']) + int(fields.get('initrd_size', '0')))
            if memory_bytes > TOTAL_MAX:
                raise ValueError('Total loaded memory exceeds loader limit (including Image.image_size)')
            if not args.initrd:
                fields['initrd'] = 'none'
            fields['cmdline'] = cmdline
            manifest = ''.join(f'{k}={v}\n' for k, v in fields.items())
            if len(manifest.encode()) > CONFIG_MAX:
                raise ValueError('Manifest too large')
            atomic_text(temporary/'manifest.conf', manifest)
            sync_dir(temporary)
            os.rename(temporary, final)
            sync_dir(store)
            # A failure after this rename leaves an unreferenced complete
            # version; the old selection remains valid until the final replace.
            atomic_text(system/'entries.conf', config)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {'system': system_id, 'current': boot_id, 'previous': previous,
            'versions': listed,
            'android_boot_written': False}


def configure(args, boot):
    systems = args.systems.split(',')
    if not 1 <= len(systems) <= 4 or len(set(systems)) != len(systems):
        raise ValueError('Expected 1..4 unique systems')
    for s in systems:
        identifier(s)
    if args.default != 'android':
        system, sep, selector = args.default.partition('/')
        if not sep or system not in systems:
            raise ValueError('Default must name a configured system')
        identifier(selector)
        if selector not in ('current', 'previous'):
            selected = versions(existing_system(boot, system))
            if not selected or selector not in selected['versions']:
                raise ValueError('Default kernel must be included in its system menu')
            version_manifest(existing_system(boot, system), selector)
    if not 0 <= args.timeout_ms <= 600000:
        raise ValueError('Invalid timeout')
    kshim = directory(boot/'kshim')
    with locked(kshim/'.config.lock'):
        atomic_text(kshim/'boot.conf', f'format=1\nsystems={args.systems}\ndefault={args.default}\ntimeout_ms={args.timeout_ms}\n')
    return {'configured_systems': systems, 'default': args.default}


def rollback(args, boot):
    system = existing_system(boot, args.system)
    with locked(system/'.update.lock'):
        old = versions(system)
        if not old or old['previous'] == 'none':
            raise ValueError('No previous version')
        # A damaged current kernel is a reason to roll back. Verify the target,
        # while retaining the old current entry for diagnosis and manual use.
        version_manifest(system, old['previous'])
        write_versions(system, old['previous'], old['current'], old['versions'])
    return {'current': old['previous'], 'previous': old['current']}


def select_kernel(args, boot):
    system = existing_system(boot, args.system)
    version = identifier(args.version)
    with locked(system/'.update.lock'):
        old = versions(system)
        if not old:
            raise ValueError('Missing version selection')
        version_manifest(system, version)
        listed = old['versions'] if version in old['versions'] else old['versions']+[version]
        previous = old['previous'] if version == old['current'] else old['current']
        write_versions(system, version, previous, listed)
    return {'current': version, 'previous': previous, 'versions': listed}


def menu(args, boot):
    system = existing_system(boot, args.system)
    listed = version_list(args.versions)
    with locked(system/'.update.lock'):
        old = versions(system)
        if not old:
            raise ValueError('Missing version selection')
        if old['current'] not in listed or (old['previous'] != 'none' and old['previous'] not in listed):
            raise ValueError('Keep current and previous in the kernel menu')
        for version in listed:
            version_manifest(system, version)
        write_versions(system, old['current'], old['previous'], listed)
    return {'current': old['current'], 'previous': old['previous'], 'versions': listed,
            'payload_files_deleted': False}


def list_kernels(args, boot):
    system = existing_system(boot, args.system)
    selected = versions(system)
    if not selected:
        raise ValueError('Missing version selection')
    kernels = []
    for version in selected['versions']:
        row = dict(version=version, current=version == selected['current'],
                   previous=version == selected['previous'])
        try:
            manifest = version_manifest(system, version, verify_payloads=False)
            row.update(title=manifest['title'], kernel_release=manifest['kernel_release'])
        except (ValueError, OSError) as error:
            row['error'] = str(error)
        kernels.append(row)
    return {'system': args.system, 'kernels': kernels}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    target = p.add_mutually_exclusive_group()
    target.add_argument('--boot-dir', type=Path, default=Path('/boot'))
    target.add_argument('--staging-root', type=Path, help='Build an offline export tree; never use for live /boot')
    p.add_argument('--partuuid')
    sub = p.add_subparsers(dest='action', required=True)
    pub = sub.add_parser('publish')
    for key in ('system', 'version', 'title', 'kernel-release'):
        pub.add_argument('--'+key, required=True)
    for key in ('image', 'dtb', 'cmdline-file'):
        pub.add_argument('--'+key, type=Path, required=True)
    initrd = pub.add_mutually_exclusive_group(required=True)
    initrd.add_argument('--initrd', type=Path)
    initrd.add_argument('--builtin-initramfs', action='store_true')
    conf = sub.add_parser('configure', help='Explicit shared boot.conf administration')
    conf.add_argument('--systems', required=True)
    conf.add_argument('--default', default='android')
    conf.add_argument('--timeout-ms', type=int, default=8000)
    roll = sub.add_parser('rollback')
    roll.add_argument('--system', required=True)
    listing = sub.add_parser('list', help='List the kernels exposed for one system (read-only)')
    listing.add_argument('--system', required=True)
    selection = sub.add_parser('select', help='Choose current kernel; preserve other menu entries')
    selection.add_argument('--system', required=True)
    selection.add_argument('--version', required=True)
    ordering = sub.add_parser('menu', help='Expose/reorder/hide kernel entries without deleting files')
    ordering.add_argument('--system', required=True)
    ordering.add_argument('--versions', required=True, help='Comma-separated version IDs; keep current and previous')
    args = p.parse_args()
    try:
        actions = dict(publish=publish, configure=configure, rollback=rollback,
                       list=list_kernels, select=select_kernel, menu=menu)
        print(json.dumps(actions[args.action](args, root(args)), ensure_ascii=False))
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        p.exit(1, str(e)+'\n')


if __name__ == '__main__':
    main()
