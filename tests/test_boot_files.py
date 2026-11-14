"""Host integration: real ext4 images, the runtime C reader and atomic updates."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import boot_files
from build_host_checks import build


class BootFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        cls.base = Path(cls.work.name)
        cls.checker = build(cls.base/'host', sanitize=True)
        cls.image = cls.base/'Image'
        header = bytearray(64)
        struct.pack_into('<QQQ', header, 8, 0x80000, 24*1024*1024, 10)
        header[56:60] = b'ARM\x64'
        cls.image.write_bytes(header + b'\xa5'*(20*1024*1024-64))
        cls.dtb = cls.base/'board.dtb'
        subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb', '-o', str(cls.dtb)],
                       input=b'/dts-v1/; / { compatible = "oneplus,opd2413", "qcom,sm8750"; };', check=True)
        cls.initrd = cls.base/'initrd'
        cls.initrd.write_bytes(b'\x1f\x8b'+b'initrd payload'*1200)
        cls.cmdline = cls.base/'cmdline'
        cls.cmdline.write_text('root=UUID=example rootflags=subvol=/root ostree=/deployment rw\n')

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = self.root/'boot'
        self.tree.mkdir()
        self.publish('alpha', 'v1')
        self.configure('alpha')

    def args(self, system='alpha', version='v1', **kw):
        values = dict(system=system, version=version, title='Linux example',
                      kernel_release='7.2.6-test', image=self.image, dtb=self.dtb,
                      initrd=self.initrd, builtin_initramfs=False, cmdline_file=self.cmdline)
        values.update(kw)
        return argparse.Namespace(**values)

    def publish(self, system, version, **kw):
        return boot_files.publish(self.args(system, version, **kw), self.tree)

    def configure(self, systems):
        boot_files.configure(argparse.Namespace(systems=systems, default='android', timeout_ms=8000), self.tree)

    def ext4(self, name='disk', features=None, fragmented=False):
        image = self.root/(name+'.img')
        with image.open('wb') as f:
            f.truncate(128*1024*1024)
        cmd = ['mkfs.ext4', '-q', '-F', '-b', '4096']
        if features:
            cmd += ['-O', features]
        if fragmented:
            cmd += ['-g', '1024', '-O', '^flex_bg']
        subprocess.run(cmd+['-d', str(self.tree), str(image)], check=True)
        return image

    def check(self, image, expected=0, sector=512, partuuid=None, choose=None):
        cmd = [str(self.checker), str(image), str(sector)]
        if partuuid:
            cmd.append(str(partuuid))
        if choose is not None:
            cmd.extend(['--choose', choose])
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotIn('Sanitizer', p.stderr)
        self.assertEqual(p.returncode, 0 if expected == 0 else 1, p.stdout+p.stderr)
        result = json.loads(p.stdout)
        self.assertEqual(result['status'], expected, result)
        return result

    def test_real_large_file_two_systems_and_previous(self):
        self.publish('alpha', 'v2')
        self.publish('beta', 'v1', initrd=None)
        self.configure('alpha,beta')
        self.assertEqual(self.check(self.ext4())['entries'], 3)
        before = (self.tree/'kshim/boot.conf').read_bytes()
        other = (self.tree/'kshim/systems/beta/entries.conf').read_bytes()
        boot_files.rollback(argparse.Namespace(system='alpha'), self.tree)
        self.assertEqual((self.tree/'kshim/boot.conf').read_bytes(), before)
        self.assertEqual((self.tree/'kshim/systems/beta/entries.conf').read_bytes(), other)
        self.assertEqual(boot_files.versions(self.tree/'kshim/systems/alpha')['current'], 'v1')

    def sized_dtb(self, size):
        data = bytearray(self.dtb.read_bytes())
        data.extend(bytes(size-len(data)))
        struct.pack_into('>I', data, 4, size)
        path = self.root/f'board-{size}.dtb'
        path.write_bytes(data)
        return path

    def test_dtb_above_old_limit_and_at_one_mib(self):
        for i, size in enumerate((256*1024+8, 1024*1024)):
            with self.subTest(size=size):
                dtb = self.sized_dtb(size)
                self.publish('alpha', f'large{i}', image=self.small_image(f'large{i}'), dtb=dtb)
                result = self.check(self.ext4(f'large-dtb-{i}'), choose='1,1')
                self.assertEqual(result['selection']['version'], f'large{i}')
                self.assertEqual(result['selection']['payload_sha256']['dtb'],
                                 hashlib.sha256(dtb.read_bytes()).hexdigest())

    def test_dtb_over_one_mib_rejected_by_publisher_and_runtime(self):
        before = (self.tree/'kshim/systems/alpha/entries.conf').read_bytes()
        with self.assertRaisesRegex(ValueError, 'max 1 MiB'):
            self.publish('alpha', 'too-large', dtb=self.sized_dtb(1024*1024+1))
        self.assertEqual((self.tree/'kshim/systems/alpha/entries.conf').read_bytes(), before)
        self.publish('alpha', 'max-dtb', dtb=self.sized_dtb(1024*1024))
        manifest = self.tree/'kshim/systems/alpha/versions/max-dtb/manifest.conf'
        manifest.write_text(manifest.read_text().replace('dtb_size=1048576', 'dtb_size=1048577'))
        disk = self.ext4('oversized-dtb')
        self.check(disk, -9, choose='1,1')
        self.assertEqual(self.check(disk, choose='1,2')['selection']['version'], 'v1')

    def small_image(self, name):
        image = self.root/('Image-'+name)
        header = bytearray(self.image.read_bytes()[:64])
        struct.pack_into('<Q', header, 16, 1024*1024)
        image.write_bytes(header + name.encode()*256)
        return image

    def test_legacy_v1_read_and_upgrade_preserves_old_kernels(self):
        self.publish('alpha', 'v2', image=self.small_image('v2'))
        path = self.tree/'kshim/systems/alpha/entries.conf'
        path.write_text('format=1\ncurrent=v2\nprevious=v1\n')
        before = self.check(self.ext4('legacy'))
        self.assertEqual([r['version'] for r in before['catalog']], ['v2', 'v1'])
        self.assertEqual([r['current'] for r in before['catalog']], [1, 0])
        self.assertEqual([r['previous'] for r in before['catalog']], [0, 1])
        self.publish('alpha', 'v3', image=self.small_image('v3'))
        self.assertEqual(boot_files.versions(path.parent)['versions'], ['v3', 'v2', 'v1'])
        self.assertTrue(path.read_text().startswith('format=2\n'))
        self.assertEqual(self.check(self.ext4('upgraded'))['entries'], 3)

    def test_four_systems_eight_distinct_kernels_each(self):
        shutil.rmtree(self.tree/'kshim/systems/alpha')
        expected = {}
        expected_payloads = {}
        for s in range(4):
            system = f'linux{s}'
            for v in range(8):
                version = f'kernel{v}'
                name = f'{system}-{version}'
                cmdline = self.root/('cmdline-'+name)
                cmdline.write_text(f'root=UUID={system} kernel_entry={name} rw\n')
                initrd = self.root/('initrd-'+name)
                initrd.write_bytes(b'initrd '+name.encode()*64)
                dtb = self.root/(name+'.dtb')
                subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb', '-o', str(dtb)],
                    input=('/dts-v1/; / { compatible = "oneplus,opd2413", "qcom,sm8750"; '
                           f'test-kernel = "{name}"; }};').encode(), check=True)
                image = self.small_image(name)
                self.publish(system, version, image=image, dtb=dtb,
                    initrd=initrd if v % 2 else None, cmdline_file=cmdline, kernel_release=f'6.{s}.{v}')
                expected[(system, version)] = f'6.{s}.{v}'
                expected_payloads[(system, version)] = {
                    'image': hashlib.sha256(image.read_bytes()).hexdigest(),
                    'dtb': hashlib.sha256(dtb.read_bytes()).hexdigest(),
                    'initrd': hashlib.sha256(initrd.read_bytes()).hexdigest() if v % 2 else None}
        self.configure('linux0,linux1,linux2,linux3')
        boot_files.configure(argparse.Namespace(systems='linux0,linux1,linux2,linux3',
            default='linux2/kernel3', timeout_ms=0), self.tree)
        disk = self.ext4()
        result = self.check(disk)
        self.assertEqual(result['entries'], 32)
        self.assertEqual({(r['system'], r['version']): r['release'] for r in result['catalog']}, expected)
        self.assertTrue(all(r['payload_status'] == 0 for r in result['catalog']))
        for system in (f'linux{s}' for s in range(4)):
            rows = [r for r in result['catalog'] if r['system'] == system]
            self.assertEqual([r['version'] for r in rows], [f'kernel{v}' for v in reversed(range(8))])
            self.assertEqual([r['version'] for r in rows if r['current']], ['kernel7'])
            self.assertEqual([r['version'] for r in rows if r['previous']], ['kernel6'])
        for s in range(4):
            for v in range(8):
                # Exercise the runtime chooser against the catalog parsed from
                # ext4, then hash the actual selected payload buffers. Menu
                # order is newest first, independent of the version number.
                result = self.check(disk, choose=f'{s+1},{8-v}')
                selected = result['selection']
                self.assertEqual((selected['system'], selected['version']), (f'linux{s}', f'kernel{v}'))
                self.assertEqual(selected['cmdline'], f'root=UUID=linux{s} kernel_entry=linux{s}-kernel{v} rw')
                self.assertEqual(selected['payload_sha256'], expected_payloads[(f'linux{s}', f'kernel{v}')])
                self.assertEqual(sum(r['payload_checked'] for r in result['catalog']), 1)
        default = self.check(disk, choose='default,default')['selection']
        self.assertEqual((default['system'], default['version']), ('linux2', 'kernel3'))
        backed = self.check(disk, choose='2,0,4,8')['selection']
        self.assertEqual((backed['system'], backed['version']), ('linux3', 'kernel0'))
        cancelled = self.check(disk, choose='0')
        self.assertIsNone(cancelled['selection'])
        self.assertTrue(all(not r['payload_checked'] for r in cancelled['catalog']))

    def test_menu_reorder_select_hide_and_rollback_are_isolated(self):
        for v in ('v2', 'v3', 'v4'):
            self.publish('alpha', v, image=self.small_image(v), kernel_release='same-release')
        self.publish('beta', 'v1', image=self.small_image('beta'))
        boot_files.configure(argparse.Namespace(systems='alpha,beta', default='alpha/v1', timeout_ms=0), self.tree)
        shared = (self.tree/'kshim/boot.conf').read_bytes()
        beta = (self.tree/'kshim/systems/beta/entries.conf').read_bytes()
        system = self.tree/'kshim/systems/alpha'
        boot_files.menu(argparse.Namespace(system='alpha', versions='v2,v4,v3,v1'), self.tree)
        args = argparse.Namespace(system='alpha', version='v1')
        boot_files.select_kernel(args, self.tree)
        boot_files.select_kernel(args, self.tree)  # Same selection must keep the previous kernel.
        self.assertEqual(boot_files.versions(system)['previous'], 'v4')
        boot_files.rollback(args, self.tree)
        self.assertEqual(boot_files.versions(system)['current'], 'v4')
        boot_files.menu(argparse.Namespace(system='alpha', versions='v4,v1'), self.tree)
        self.assertTrue((system/'versions/v2/Image').is_file())
        boot_files.select_kernel(argparse.Namespace(system='alpha', version='v2'), self.tree)
        self.assertEqual(boot_files.versions(system)['versions'], ['v4', 'v1', 'v2'])
        self.assertEqual((self.tree/'kshim/boot.conf').read_bytes(), shared)
        self.assertEqual((self.tree/'kshim/systems/beta/entries.conf').read_bytes(), beta)
        result = self.check(self.ext4())
        self.assertEqual(result['entries'], 4)
        listing = subprocess.check_output([sys.executable, str(ROOT/'tools/boot_files.py'),
            '--staging-root', str(self.tree), 'list', '--system', 'alpha'], text=True)
        self.assertEqual([r['version'] for r in json.loads(listing)['kernels']], ['v4', 'v1', 'v2'])

    def test_more_than_eight_kernels_keep_old_versions(self):
        for v in range(2, 25):
            self.publish('alpha', f'v{v}', image=self.small_image(f'v{v}'))
        system = self.tree/'kshim/systems/alpha'
        self.assertEqual(boot_files.versions(system)['versions'],
                         [f'v{v}' for v in range(24, 0, -1)])
        self.assertTrue((system/'versions/v1/Image').is_file())
        self.assertEqual(self.check(self.ext4())['entries'], 24)

    def test_invalid_v2_lists_rejected_by_python_and_runtime(self):
        path = self.tree/'kshim/systems/alpha/entries.conf'
        for body, status in [
            ('format=2\ncurrent=v1\nprevious=none\nversions=v1,v1\n', -6),
            ('format=2\ncurrent=v1\nprevious=none\nversions=other\n', -3),
            ('format=2\ncurrent=v1\nprevious=v2\nversions=v1\n', -3),
            ('format=2\ncurrent=v1\nprevious=none\nversions=v1,../v2\n', -3),
            ('format=2\ncurrent=v1\nprevious=none\nversions=v1,none\n', -3),
            ('format=2\ncurrent=v1\nprevious=none\nversions=v1,\n', -3),
            ('format=1\ncurrent=v1\nprevious=none\nversions=v1\n', -3),
            ('format=2\ncurrent=v1\nprevious=none\nversions=v1\nunknown=1\n', -3),
        ]:
            path.write_text(body)
            with self.assertRaises(ValueError):
                boot_files.versions(path.parent)
            self.check(self.ext4('invalid-list'), status)

    def test_bad_kernel_does_not_hide_healthy_peers_or_other_systems(self):
        for v in ('v2', 'v3'):
            self.publish('alpha', v, image=self.small_image(v))
        self.publish('beta', 'v1', image=self.small_image('beta'))
        self.configure('alpha,beta')
        (self.tree/'kshim/systems/alpha/versions/v2/manifest.conf').unlink()
        disk = self.ext4()
        rows = self.check(disk, -5)['catalog']
        self.assertEqual(len(rows), 4)
        self.assertEqual([(r['system'], r['version']) for r in rows if r['payload_status'] == 0],
                         [('alpha', 'v3'), ('alpha', 'v1'), ('beta', 'v1')])
        for choices, expected in [('1,1', ('alpha', 'v3')), ('1,3', ('alpha', 'v1')), ('2,1', ('beta', 'v1'))]:
            selected = self.check(disk, choose=choices)['selection']
            self.assertEqual((selected['system'], selected['version']), expected)
        self.check(disk, -5, choose='1,2')

    def test_selection_rejects_corrupt_kernel_and_preserves_menu(self):
        self.publish('alpha', 'v2', image=self.small_image('v2'))
        system = self.tree/'kshim/systems/alpha'
        original = (system/'entries.conf').read_bytes()
        image = system/'versions/v1/Image'
        with image.open('r+b') as stream:
            stream.seek(100); stream.write(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            boot_files.select_kernel(argparse.Namespace(system='alpha', version='v1'), self.tree)
        self.assertEqual((system/'entries.conf').read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'Keep current and previous'):
            boot_files.menu(argparse.Namespace(system='alpha', versions='v2'), self.tree)

    def test_rollback_recovers_corrupt_current_but_refuses_corrupt_target(self):
        self.publish('alpha', 'v2', image=self.small_image('v2'))
        system = self.tree/'kshim/systems/alpha'
        image = system/'versions/v2/Image'
        with image.open('r+b') as stream:
            stream.seek(100); stream.write(b'corrupt')
        args = argparse.Namespace(system='alpha')
        boot_files.rollback(args, self.tree)
        self.assertEqual(boot_files.versions(system)['current'], 'v1')
        self.assertEqual(boot_files.versions(system)['previous'], 'v2')
        original = (system/'entries.conf').read_bytes()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            boot_files.rollback(args, self.tree)
        self.assertEqual((system/'entries.conf').read_bytes(), original)

    def test_payload_hash_corruption(self):
        image = self.tree/'kshim/systems/alpha/versions/v1/Image'
        with image.open('r+b') as f:
            f.seek(1000000)
            f.write(b'corrupt')
        self.check(self.ext4(), -13)

    def test_missing_and_symlink_files(self):
        path = self.tree/'kshim/systems/alpha/versions/v1/initramfs.img'
        path.unlink()
        self.check(self.ext4('missing'), -5)
        path.symlink_to('Image')
        self.check(self.ext4('symlink'), -11)

    def test_dirty_and_unsupported_features(self):
        clean = self.ext4()
        # Feature gates precede checksum admission. The clean fixture exercises
        # actual metadata checksums for directories, inodes and extent blocks.
        for name, offset, fmt, bit, expected in [
            ('dirty', 58, '<H', 2, -12),
            ('recover', 96, '<I', 4, -11),
            ('encrypt', 96, '<I', 0x10000, -11),
            ('inline', 96, '<I', 0x8000, -11),
            ('bigalloc', 100, '<I', 0x200, -11),
            ('orphan-present', 100, '<I', 0x10000, -11),
        ]:
            image = self.root/(name+'.img')
            shutil.copyfile(clean, image)
            with image.open('r+b') as f:
                f.seek(1024+offset)
                old = struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
                f.seek(1024+offset)
                f.write(struct.pack(fmt, bit if name == 'dirty' else old|bit))
            self.check(image, expected)

    def test_superblock_checksum_corruption(self):
        image = self.ext4()
        with image.open('r+b') as f:
            f.seek(1024+104)
            value = f.read(1)[0]
            f.seek(1024+104)
            f.write(bytes([value^1]))
        self.check(image, -3)

    def test_fragmented_extent_tree_and_metadata_corruption(self):
        import re
        image = self.ext4(fragmented=True)
        path = '/kshim/systems/alpha/versions/v1/Image'
        info = subprocess.check_output(['debugfs', '-R', 'stat '+path, str(image)], stderr=subprocess.DEVNULL, text=True)
        tree = re.search(r'\(ETB0\):(\d+)', info)
        self.assertIsNotNone(tree, info)  # Prove an external extent node exists.
        self.check(image)
        with image.open('r+b') as f:
            f.seek(int(tree.group(1))*4096+40)
            old = f.read(1)[0]
            f.seek(-1, os.SEEK_CUR)
            f.write(bytes([old^1]))
        self.check(image, -3)

    def test_missing_manifest_keeps_previous_visible(self):
        self.publish('alpha', 'v2')
        path = self.tree/'kshim/systems/alpha/versions/v2/manifest.conf'
        path.unlink()
        result = self.check(self.ext4(), -5)
        self.assertEqual(result['entries'], 2)

    def test_configuration_rejects_duplicate_unknown_and_traversal(self):
        path = self.tree/'kshim/systems/alpha/versions/v1/manifest.conf'
        original = path.read_text()
        for value in (original+'title=duplicate\n', original+'unknown=oops\n',
                      original.replace('image=Image', 'image=../Image'),
                      original.replace('device=oneplus,opd2413', 'device=another'),
                      original.replace('image_size=20971520', 'image_size=9999999999999999999999999')):
            path.write_text(value)
            self.check(self.ext4('config'), -3)

    def test_publication_interrupted_keeps_old_selection(self):
        path = self.tree/'kshim/systems/alpha/entries.conf'
        original = path.read_bytes()
        atomic = boot_files.atomic_text
        def fail_selection(p, text):
            if p.name == 'entries.conf':
                raise OSError('injected interruption before selection switch')
            return atomic(p, text)
        with mock.patch.object(boot_files, 'atomic_text', side_effect=fail_selection):
            with self.assertRaises(OSError):
                self.publish('alpha', 'v2')
        self.assertEqual(path.read_bytes(), original)
        self.check(self.ext4())

    def test_copy_failure_and_full_filesystem_keep_current(self):
        path = self.tree/'kshim/systems/alpha/entries.conf'
        original = path.read_bytes()
        with mock.patch.object(boot_files, 'copy_file', side_effect=OSError('ENOSPC')):
            with self.assertRaises(OSError):
                self.publish('alpha', 'v2')
        usage = shutil._ntuple_diskusage(100, 100, 0)
        with mock.patch.object(boot_files.shutil, 'disk_usage', return_value=usage):
            with self.assertRaises(ValueError):
                self.publish('alpha', 'v3')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list((path.parent/'versions').iterdir()), [path.parent/'versions/v1'])

    def test_unmounted_readonly_and_wrong_mount_rejected(self):
        args = argparse.Namespace(staging_root=None, boot_dir=self.tree, partuuid='d4d95497-250b-4023-98eb-a8977664e385')
        for row in [dict(target=str(self.tree), source='/dev/sda16', fstype='ext4', fsroot='/', partuuid=args.partuuid, options='ro'),
                    dict(target=str(self.tree), source='/dev/sda16', fstype='ext4', fsroot='/', partuuid=str(uuid.uuid4()), options='rw'),
                    dict(target=str(self.tree), source='/dev/sda16', fstype='ext4', fsroot='/subdir', partuuid=args.partuuid, options='rw')]:
            with mock.patch.object(boot_files.subprocess, 'check_output', return_value=json.dumps({'filesystems':[row]})):
                with self.assertRaises(ValueError):
                    boot_files.root(args)
        with mock.patch.object(boot_files.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, 'findmnt')):
            with self.assertRaises(subprocess.CalledProcessError):
                boot_files.root(args)

    def test_unique_versions_and_symlink_system(self):
        with self.assertRaises(ValueError):
            self.publish('alpha', 'v1')
        (self.tree/'kshim/systems/alias').symlink_to('alpha')
        with self.assertRaises(ValueError):
            self.publish('alias', 'v2')

    def test_runtime_image_memory_limit_keeps_old_version(self):
        selection = self.tree/'kshim/systems/alpha/entries.conf'
        original = selection.read_bytes()
        image = self.root/'large-bss-Image'
        header = bytearray(self.image.read_bytes()[:64])
        struct.pack_into('<Q', header, 16, boot_files.TOTAL_MAX)
        image.write_bytes(header)
        with self.assertRaisesRegex(ValueError, 'Total loaded memory'):
            self.publish('alpha', 'v2', image=image)
        self.assertEqual(selection.read_bytes(), original)
        self.assertEqual(list((selection.parent/'versions').iterdir()), [selection.parent/'versions/v1'])

    def test_duplicate_version_selection_is_rejected(self):
        selection = self.tree/'kshim/systems/alpha/entries.conf'
        invalid = b'format=1\ncurrent=v1\nprevious=v1\n'
        selection.write_bytes(invalid)
        with self.assertRaisesRegex(ValueError, 'must be different'):
            boot_files.rollback(argparse.Namespace(system='alpha'), self.tree)
        with self.assertRaisesRegex(ValueError, 'must be different'):
            self.publish('alpha', 'v2')
        self.assertEqual(selection.read_bytes(), invalid)

    def test_gpt_uuid_512_and_4096_and_crc(self):
        raw = self.ext4()
        uid = uuid.uuid4()
        for sector in (512, 4096):
            disk = self.root/f'gpt-{sector}.img'
            start = 2048*512//sector
            blocks = start+raw.stat().st_size//sector+2048
            table = bytearray(128*128)
            table[:16] = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
            table[16:32] = uid.bytes_le
            struct.pack_into('<QQ', table, 32, start, start+raw.stat().st_size//sector-1)
            table[56:76] = 'linux_boot'.encode('utf-16le')
            header = bytearray(sector)
            header[:8] = b'EFI PART'
            struct.pack_into('<IIIIQQQQ', header, 8, 0x10000, 92, 0, 0, 1, blocks-1, 2+len(table)//sector, blocks-2-len(table)//sector)
            header[56:72] = uuid.uuid4().bytes_le
            struct.pack_into('<QIII', header, 72, 2, 128, 128, zlib.crc32(table))
            struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
            with disk.open('wb') as f:
                f.truncate(blocks*sector)
                f.seek(sector)
                f.write(header)
                f.write(table)
                f.seek(start*sector)
                with raw.open('rb') as src:
                    shutil.copyfileobj(src,f)
            self.check(disk, sector=sector, partuuid=uid)
            with disk.open('r+b') as f:
                f.seek(2*sector+100)
                f.write(b'x')
            self.check(disk, -4, sector=sector, partuuid=uid)


if __name__ == '__main__':
    unittest.main()
