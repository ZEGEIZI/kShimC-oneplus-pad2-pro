"""Pack real 4/8 MiB shims and exercise independent slot/layout validation."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from boot_contract import check_external_packed


class RuntimeSlotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        subprocess.run(['cmake', '-S', str(ROOT/'boot/vendor/packer'),
                        '-B', str(cls.root/'tools'), '-DBUILD_SHIMS=OFF'],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['cmake', '--build', str(cls.root/'tools'), '--parallel', '2'],
                       check=True, stdout=subprocess.DEVNULL)
        cls.fixtures = {}
        for mib, debug in ((4, False), (8, False), (8, True)):
            work = cls.root/f'{mib}-{debug}'
            work.mkdir()
            base = bytearray(4096)
            struct.pack_into('<IIQQQ', base, 0, 0x14000010, 0xd503201f,
                             0x80000, 8192, 10)
            base[56:60] = b'ARM\x64'
            (work/'Base').write_bytes(base)
            runtime = bytearray(mib*1024*1024)
            struct.pack_into('<Q', runtime, 16, len(runtime))
            runtime[56:60] = b'ARM\x64'
            runtime[-32:] = b'\xa5'*32  # Include data beyond the old 4 MiB boundary.
            (work/'Shim').write_bytes(runtime)
            cfg = (f'[Pack]\nShim={work}/Shim\nOutput={work}/Packed\n'
                   'Default=Image-00\nTimeout=8000\n\n'
                   f'[Image-00]\nName=原厂 Android\nType=Linux\nPath={work}/Base\n'
                   'Align=21\nBaseImage=true\n')
            extra = None
            if debug:
                subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb', '-o', str(work/'DTB')],
                               input=b'/dts-v1/; / { compatible = "oneplus,opd2413"; };', check=True)
                (work/'Initrd').write_bytes(b'initrd payload')
                cfg += 'DeviceTreeBlob=Image-01\n'
                for i, kind, path, alignment in ((1, 'DTB', 'DTB', 3), (2, 'Blob', 'Initrd', 16)):
                    cfg += (f'\n[Image-{i:02d}]\nName={path}\nType={kind}\nPath={work}/{path}\n'
                            f'Align={alignment}\nBaseImage=false\n')
                extra = [(work/'DTB').read_bytes(), (work/'Initrd').read_bytes()]
            cfg += '\n[Manifest]\nType=Manifest\n'
            (work/'pack.cfg').write_text(cfg)
            subprocess.run([str(cls.root/'tools/MultiBootKernelPatcher'), str(work/'pack.cfg')],
                           check=True, stdout=subprocess.DEVNULL)
            cls.fixtures[mib, debug] = ((work/'Packed').read_bytes(), bytes(base), bytes(runtime), extra)

    def check(self, mib=8, debug=False, **changes):
        packed, base, runtime, extra = self.fixtures[mib, debug]
        values = dict(data=packed, base=base, runtime=runtime, timeout=8000,
                      debug_payloads=extra, runtime_slot_bytes=mib*1024*1024)
        values.update(changes)
        return check_external_packed(**values)

    def test_production_slots(self):
        for mib in (4, 8):
            with self.subTest(mib=mib):
                result = self.check(mib)
                self.assertEqual(result['runtime_slot_bytes'], mib*1024*1024)
                self.assertEqual(len(result['entries']), 2)
                self.assertTrue(result['android_retained'])

    def test_debug_payloads_follow_eight_mib_slot(self):
        result = self.check(debug=True)
        shim = result['entries'][-1]
        for row in result['entries'][1:-1]:
            self.assertGreaterEqual(row['offset'], shim['offset']+8*1024*1024)

    def test_stale_slot_metadata_rejected(self):
        with self.assertRaisesRegex(ValueError, 'size mismatch'):
            self.check(runtime_slot_bytes=4*1024*1024)

    def test_stale_image_header_rejected(self):
        packed, _, runtime, _ = self.fixtures[8, False]
        runtime = bytearray(runtime)
        struct.pack_into('<Q', runtime, 16, 4*1024*1024)
        packed = bytearray(packed)
        shim = struct.unpack_from('<Q', packed, 48)[0]
        packed[shim:shim+len(runtime)] = runtime
        with self.assertRaisesRegex(ValueError, 'size mismatch'):
            self.check(data=packed, runtime=runtime)

    def test_old_manifest_size_rejected(self):
        packed = bytearray(self.fixtures[8, False][0])
        manifest = struct.unpack_from('<Q', packed, 32)[0]
        first = manifest+60
        nlen = struct.unpack_from('<I', packed, first+52)[0]
        shim_entry = first+((56+nlen+3)//4)*4
        struct.pack_into('<Q', packed, shim_entry+8, 4*1024*1024)
        with self.assertRaisesRegex(ValueError, 'bad shim'):
            self.check(data=packed)

    def test_truncated_runtime_rejected(self):
        with self.assertRaisesRegex(ValueError, 'size mismatch'):
            self.check(runtime=self.fixtures[8, False][2][:-1])


if __name__ == '__main__':
    unittest.main()
