#!/usr/bin/env python3
"""Package the audio kernel, exact module delta, board DT and RAM audio service."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

from boot_contract import align, check_linux_packed
from build_bundle import extract_dictionary
from build_console_boot import replace_entry, repack_payloads
from cpio import assemble, decode, parse as parse_cpio
from dtb import parse as parse_dtb
from host_tools import command

DEVICE = Path(__file__).resolve().parents[1]
RELEASE = '7.2.6-opd2413-full-system03'
REFERENCE_SHA = '0ccf10f07aafa16062df60b7e5ec8ec2bee91aa71250e1478954f8a489e92b11'


def sha(data): return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--speakers-only', action='store_true', help='isolate TDM playback without SoundWire or microphone DT nodes')
    p.add_argument('--default-linux-test', action='store_true', help='select Linux after eight seconds in a temporary fastboot boot test image')
    p.add_argument('--defer-audio', action='store_true', help='stage audio for manual module loading after the desktop starts')
    a = p.parse_args(); out = a.out.resolve(); kernel = a.kernel.resolve()
    if out.exists(): p.error('output directory must be new')
    report = json.loads((kernel/'result.json').read_text())
    if not report['passed'] or report['profile'] != 'opd2413-audio-v1': raise ValueError('unverified audio kernel')
    image = (kernel/'Image').read_bytes()
    if sha(image) != report['image_sha256'] or len(image)>30867456: raise ValueError('audio kernel identity or slot size')
    reference = a.reference.read_bytes()
    if sha(reference) != REFERENCE_SHA: raise ValueError('reference must be the verified battery/console boot')
    out.mkdir(parents=True)
    packed = reference[4096:4096+struct.unpack_from('<I',reference,8)[0]]
    cursor=struct.unpack_from('<Q',packed,32)[0]+60; payloads=[]
    for _ in range(5):
        off,size=struct.unpack_from('<QQ',packed,cursor);payloads.append(packed[off:off+size])
        cursor+=align(56+struct.unpack_from('<I',packed,cursor+52)[0],4)
    entries,trailer=parse_cpio(decode(payloads[3]))
    old={e['path']:e['sha256'] for e in entries}
    def put(path,data,mode=0o100644):
        parent=Path(path).parent
        for directory in reversed([parent,*parent.parents]):
            if str(directory)!='.': replace_entry(entries,str(directory),b'',0o40755)
        replace_entry(entries,path,data,mode)
    # Replace every initrd module and index with the new kernel's own build.
    tree=kernel/'stage/lib/modules'/RELEASE
    for path,expected in report['modules'].items():
        if sha((tree/path).read_bytes())!=expected: raise ValueError('module tree changed: '+path)
    module_prefix='usr/lib/modules/'+RELEASE+'/'
    for e in entries:
        if e['path'].startswith(module_prefix):
            rel=e['path'][len(module_prefix):]; source=tree/rel
            if source.is_file(): replace_entry(entries,e['path'],source.read_bytes())
    obsolete=('usr/lib/armada/opd2413-speaker-id','var/lib/dracut/hooks/pre-pivot/88-opd2413-speaker-id.sh',
        'etc/modprobe.d/99-opd2413-speaker-id.conf')
    entries[:]=[e for e in entries if not any(e['path']==x or e['path'].startswith(x+'/') for x in obsolete)
        and not e['path'].endswith('/opd2413_speaker_id.ko')]
    # Retain the original verified module dictionary only as a delta input.
    dictionary=out/'dictionary';dictionary.mkdir();expected=extract_dictionary(dictionary)
    marker=next(e['data'] for e in entries if e['path']==module_prefix+'.armada-opd2413')
    files={f.relative_to(tree).as_posix():f.read_bytes() for f in sorted(tree.rglob('*')) if f.is_file() and f.name != 'config'}
    files['.armada-opd2413']=marker
    config=(tree/'config').read_bytes()
    put(module_prefix+'config',config)
    bundle_prefix='usr/lib/armada/opd2413-full-modules/bundle/'
    entries[:]=[e for e in entries if not e['path'].startswith(bundle_prefix)]
    rows=[];total=0;payload_dir=out/'delta';payload_dir.mkdir()
    for index,(rel,data) in enumerate(sorted(files.items())):
        target=out/'delta-input';target.write_bytes(data)
        base=dictionary/rel if rel in expected else None
        name=f'{index:03d}.zst';dest=payload_dir/name
        compress=command('zstd')+['-q','-19','-T1','--stdout']
        if base: compress+=['--patch-from='+str(base)]
        with dest.open('wb') as stream: subprocess.run(compress+[str(target)],stdout=stream,check=True)
        check=command('zstd')+['-q','-d','--stdout']
        if base:check+=['--patch-from='+str(base)]
        if subprocess.check_output(check+[str(dest)])!=data:raise ValueError('delta roundtrip: '+rel)
        delta=dest.read_bytes();total+=len(data)
        rows.append([name,str(base.stat().st_size if base else 0),expected[rel]['stripped_sha256'] if base else '-',
            str(len(data)),sha(data),str(len(delta)),sha(delta),rel])
        put(bundle_prefix+name,delta)
    (out/'delta-input').unlink()
    if len(rows)>256 or total>64*1024*1024: raise ValueError('reconstructor limits exceeded')
    manifest='OPD2413_MODULE_DELTA_V1\ncount\t'+str(len(rows))+'\n'+''.join('\t'.join(row)+'\n' for row in rows)
    put(bundle_prefix+'manifest.tsv',manifest.encode())
    (payload_dir/'manifest.tsv').write_text(manifest)
    # Exercise the real allowlist, parser, decoder and digest checks; zstd
    # roundtrips alone do not prove that the boot-time consumer accepts it.
    validator=out/'validate-reconstruction'
    subprocess.run(['cc','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        str(DEVICE/'rootfs/helpers/reconstructor/reconstruct.c'),'-lcrypto','-lzstd','-o',str(validator)],check=True)
    with tempfile.TemporaryDirectory(prefix='opd2413-audio-',dir='/dev/shm') as work:
        rebuilt=Path(work)/'tree'
        run=subprocess.run([str(validator),str(dictionary),str(payload_dir),str(rebuilt)],capture_output=True,text=True,check=True)
        for name,data in files.items():
            if (rebuilt/name).read_bytes()!=data:raise ValueError('actual reconstructor differs: '+name)
        (out/'reconstruction.log').write_text(run.stdout+run.stderr)
    sums=''.join(sha(data)+'  '+name+'\n' for name,data in sorted(files.items()))
    sums+=sha(config)+'  config\n'
    put('usr/lib/armada/opd2413-full-modules/SHA256SUMS',sums.encode())
    summary=f'OPD2413_MODULE_DELTA_READY files={len(rows)} bytes={total}'.encode()
    for name in ('var/lib/dracut/hooks/pre-pivot/86-opd2413-full-modules.sh',
                 'usr/lib/armada/opd2413-full-modules/guard-switch-root.sh'):
        e=next(e for e in entries if e['path']==name)
        data,n=re.subn(rb'OPD2413_MODULE_DELTA_READY files=182 bytes=21686181',summary,e['data'])
        if n!=1: raise ValueError('unknown module staging contract')
        if name.endswith('86-opd2413-full-modules.sh'):
            copy=('    cp /usr/lib/modules/'+RELEASE+'/config "$ram/tree/config" || return 1\n').encode()
            data=data.replace(b'    # Preserve the installed',copy+b'    # Preserve the installed',1)
        put(name,data,0o100755)
    # Remove the obsolete identity-only amplifier staging from the audio boot.
    name='var/lib/dracut/hooks/pre-pivot/87-opd2413-brahma08.sh'
    data=next(e['data'] for e in entries if e['path']==name).replace(b' /run/systemd/system/opd2413-speaker-id.service.d',b'')
    data=b'\n'.join(line for line in data.split(b'\n') if b'cp -p /run/systemd/system/opd2413-brahma08.service.d/60-full-modules.conf' not in line)
    put(name,data,0o100755)
    name='usr/lib/armada/opd2413-brahma08/SHA256SUMS'
    data=next(e['data'] for e in entries if e['path']==name)
    other=b'\n'.join(line for line in data.split(b'\n') if line and b'  lib/modules/' not in line)
    put(name,(''.join(sha(data)+'  lib/modules/'+RELEASE+'/'+name+'\n' for name,data in sorted(files.items()))).encode()+other+b'\n')
    for name in ('pmic_glink','qcom_battmgr'):
        data=(kernel/'battery-modules'/(name+'.ko')).read_bytes()
        put('usr/lib/armada/opd2413-battery/'+name+'.ko',data)
    put('usr/lib/armada/opd2413-battery/SHA256SUMS',''.join(sha((kernel/'battery-modules'/(n+'.ko')).read_bytes())+'  '+n+'.ko\n' for n in ('pmic_glink','qcom_battmgr')).encode())
    stock_lock=json.loads((DEVICE/'audio/stock-inputs.json').read_text())
    for name,expected_hash in stock_lock['files'].items():
        if sha((DEVICE/'inputs/local/audio'/name).read_bytes())!=expected_hash:raise ValueError('stock audio input changed: '+name)
    topology=(DEVICE/'audio/OnePlus-Pad-2-Pro.conf').read_text()
    if a.speakers_only:
        topology=re.sub(r'(?ms)^Section[^\n]*\{.*?^\}',lambda m: '' if re.search(
            r'stream1\.|device120\.|MultiMedia2|TX_CODEC_DMA_TX_3',m.group().splitlines()[0]) else m.group(),topology)
    (out/'topology.conf').write_text(topology)
    subprocess.run(['alsatplg','-c',str(out/'topology.conf'),'-o',str(out/'topology.bin')],check=True)
    prefix='usr/lib/armada/opd2413-audio/'
    if a.defer_audio:put(prefix+'manual-load',b'Load /run/opd2413-audio/load-audio.sh after collecting boot diagnostics.\n')
    put(prefix+'firmware/qcom/sm8750/OnePlus-Pad-2-Pro-tplg.bin',(out/'topology.bin').read_bytes())
    put(prefix+'firmware/aw88261_acf.bin',(DEVICE/'inputs/local/audio/aw882xx_acf.bin').read_bytes())
    for name in ('load-audio.sh','setup-alsa.sh','opd2413-audio.service'):put(prefix+name,(DEVICE/'audio'/name).read_bytes())
    for directory in ('ucm2',):
        for path in sorted((DEVICE/'audio'/directory).rglob('*')):
            if path.is_file():put(prefix+str(path.relative_to(DEVICE/'audio')),path.read_bytes())
    put('var/lib/dracut/hooks/pre-udev/01-opd2413-audio.sh',(DEVICE/'audio/early-audio.sh').read_bytes(),0o100755)
    put('var/lib/dracut/hooks/pre-pivot/89-opd2413-audio.sh',(DEVICE/'audio/stage-audio.sh').read_bytes(),0o100755)
    # DT compiler resolves new phandles above the existing explicit inventory.
    dts=(DEVICE/'boot/dt/reference-rootfs.dts').read_text()
    dts+='\n/ { pmic-glink { compatible = "qcom,sm8750-pmic-glink", "qcom,sm8550-pmic-glink", "qcom,pmic-glink"; }; chosen { armada,audio-profile = "opd2413-audio-v1"; }; };\n'
    dts+='#include "'+str(DEVICE/'audio/opd2413.dtsi')+'"\n'
    if not a.speakers_only:
        dts+='#include "'+str(DEVICE/'audio/opd2413-microphones.dtsi')+'"\n'
    raw_source=out/'audio.dts';raw_source.write_text(dts)
    preprocessed=subprocess.check_output(['cpp','-nostdinc','-undef','-D__DTS__','-x','assembler-with-cpp',
        '-I',str(kernel/'source/include'),str(raw_source)])
    subprocess.run(command('dtc')+['-q','-I','dts','-O','dtb','-o',str(out/'audio.dtb')],input=preprocessed,check=True)
    from build_console_boot import console_dtb
    dtb=console_dtb((out/'audio.dtb').read_bytes())
    before,_,_=parse_dtb(payloads[2]);after,_,_=parse_dtb(dtb)
    # Existing hardware, storage and console policy must be preserved.
    changed=[]
    for key,value in before.items():
        if after.get(key)==value:continue
        if '/amplifier@' in key and key.endswith(':compatible'):changed.append(key);continue
        raise ValueError('audio DT changed unrelated property: '+key)
    (out/'audio.dtb').write_bytes(dtb)
    raw=assemble(entries,trailer,lambda e:e['data']);(out/'initramfs.cpio').write_bytes(raw)
    with (out/'initramfs.img').open('wb') as stream:
        subprocess.run(command('xz')+['-9e','--check=crc32','--threads=1','--stdout',str(out/'initramfs.cpio')],stdout=stream,check=True)
    initrd=(out/'initramfs.img').read_bytes();again,_=parse_cpio(decode(initrd))
    if {e['path']:e['sha256'] for e in entries}!={e['path']:e['sha256'] for e in again}:raise ValueError('initrd roundtrip')
    subprocess.run([sys.executable,str(DEVICE/'tools/check_audio_vm.py'),
        '--kernel',str(kernel),'--initramfs',str(out/'initramfs.img'),
        '--out',str(out/'cold-pcm')],check=True)
    original=(DEVICE/'inputs/local/stock-android-boot.img').read_bytes()
    stock=original[4096:4096+struct.unpack_from('<I',original,8)[0]]
    new,layout=repack_payloads(packed,stock,dtb,initrd,kernel_bytes=image.ljust(30867456,b'\0'))
    if a.default_linux_test:
        new = bytearray(new)
        struct.pack_into('<I', new, struct.unpack_from('<Q', new, 32)[0] + 12, 1)
        new = bytes(new)
        layout = check_linux_packed(new, stock, payloads[4], 8000,
            [image.ljust(30867456,b'\0'), dtb, initrd], default_index=1,
            payload_names=('Linux 系统（实验）', 'OPD2413 rootfs DTB', 'standard dracut initramfs'))
    (out/'PackedKernel').write_bytes(new)
    subprocess.run([sys.executable,str(DEVICE/'tools/repack_boot_v4.py'),'--original',str(a.reference.resolve()),
        '--kernel',str(out/'PackedKernel'),'--output',str(out/'boot.img'),'--report',str(out/'repack.json'),
        '--avbtool',str(DEVICE/'tools/avbtool.py')],check=True)
    subprocess.run(command('img2simg')+[str(out/'boot.img'),str(out/'boot.sparse'),'4096'],check=True)
    subprocess.run(command('simg2img')+[str(out/'boot.sparse'),str(out/'expanded.img')],check=True)
    if (out/'expanded.img').read_bytes()!=(out/'boot.img').read_bytes():raise ValueError('sparse roundtrip')
    (out/'expanded.img').unlink()
    result=dict(passed=True,profile='opd2413-audio-v1',hardware_verified=False,
        speakers_only=a.speakers_only,
        temporary_menu_default='Linux' if a.default_linux_test else 'Android',
        manual_audio_load=a.defer_audio,
        boot_sha256=sha((out/'boot.img').read_bytes()),kernel_sha256=sha(image),
        module_files=len(rows),module_bytes=total,delta_roundtrips_verified=True,
        changed_existing_dt_properties=changed,layout=layout)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(sha((out/n).read_bytes())+'  '+n+'\n' for n in ('boot.img','boot.sparse')))
    print(json.dumps({k:v for k,v in result.items() if k!='layout'},indent=2))


if __name__=='__main__':main()
