#!/usr/bin/env python3
"""Build the OPD2413 audio kernel with the existing Bluetooth and battery fixes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_kernel import prepare_source

DEVICE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=12)
    p.add_argument('--reuse-base', action='store_true', help='reuse the verified base or prepared audio build in --out')
    a = p.parse_args(); out = a.out.resolve()
    if a.reuse_base:
        old = json.loads((out/'result.json').read_text())
        if old.get('profile') in ('audio-building','opd2413-audio-v1') and (out/'audio-sources.json').is_file():
            for path, expected in json.loads((out/'audio-sources.json').read_text()).items():
                if sha(out/'source'/path) != expected: p.error('prepared audio source changed: '+path)
        elif not old.get('passed') or not old.get('source_built_from_clean_upstream'):
            p.error('reuse requires a completed base build')
        elif sha(out/'build/.config') != old['config_sha256']:
            p.error('base configuration has changed')
        (out/'result.json').write_text('{"passed":false,"profile":"audio-building"}\n')
    else:
        if out.exists(): p.error('output directory must be new')
        out.mkdir(parents=True); prepare_source(out)
        (out/'build').mkdir()
        shutil.copyfile(DEVICE/'kernel/current/config', out/'build/.config')
    source = out/'source'
    prepared = (out/'audio-sources.json').exists()
    for f in (DEVICE/'kernel/current/final-modules').iterdir():
        if f.name.startswith('opd2413_speaker_id'): continue
        target = source/('drivers/tty/serial' if f.name == 'qcom_geni_serial.c' else 'drivers/bluetooth')/f.name
        shutil.copyfile(f, target)
    machine = source/'sound/soc/qcom'
    shutil.copyfile(DEVICE/'audio/opd2413.c', machine/'opd2413.c')
    if not prepared:
        with (machine/'Makefile').open('a') as f:
            f.write('\nsnd-soc-opd2413-y := opd2413.o\nobj-$(CONFIG_SND_SOC_OPD2413) += snd-soc-opd2413.o\n')
        with (machine/'Kconfig').open('a') as f:
            f.write('\nconfig SND_SOC_OPD2413\n\ttristate "OnePlus Pad 2 Pro audio"\n'
                    '\tdepends on QCOM_APR && SOUNDWIRE\n\tselect SND_SOC_QDSP6\n'
                    '\tselect SND_SOC_QCOM_COMMON\n\tselect SND_SOC_QCOM_SDW\n')
    for patch in [] if prepared else sorted((DEVICE/'audio').glob('*.patch')):
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=source, check=True)
    paths = ['sound/soc/qcom/'+f for f in ('opd2413.c','Makefile','Kconfig',
             'qdsp6/audioreach.c','qdsp6/audioreach.h','qdsp6/topology.c',
             'qdsp6/q6prm.h','qdsp6/q6prm-clocks.c','qdsp6/q6apm-dai.c')]
    paths += ['sound/soc/codecs/aw88261.c']
    (out/'audio-sources.json').write_text(json.dumps({path:sha(source/path) for path in paths},indent=2)+'\n')
    for test in ('check_audio_slots.py', 'check_audio_blob.py'):
        subprocess.run([sys.executable, str(DEVICE/'tests'/test),
                        '--kernel-source', str(source)], check=True)
    config = out/'build/.config'
    requested = dict(line.split('=', 1) for line in (DEVICE/'audio/config.fragment').read_text().splitlines() if line.startswith('CONFIG_'))
    requested['CONFIG_SND_SOC_OPD2413'] = 'm'
    import re
    text = config.read_text()
    for name, value in requested.items():
        text = re.sub(r'^(?:'+name+r'=.*|# '+name+r' is not set)\n', '', text, flags=re.M)
        text += name+'='+value+'\n'
    config.write_text(text)
    image = json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    base = ['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
        '--mount',f'type=bind,src={DEVICE},dst=/device,readonly',
        '--mount',f'type=bind,src={out},dst=/work',
        '-e','KBUILD_BUILD_USER=armada','-e','KBUILD_BUILD_HOST=opd2413-audio',
        '-e','KBUILD_BUILD_TIMESTAMP=2026-11-09 00:00:00 UTC','-e','KBUILD_BUILD_VERSION=1',image]
    make = ['make','-C','/work/source','O=/work/build','ARCH=arm64',
        'CROSS_COMPILE=aarch64-linux-gnu-','PAHOLE=/device/inputs/local/pahole132/run-pahole']
    for label, targets in [('audio-configure', ['olddefconfig']), ('audio-compile',[f'-j{a.jobs}','Image','modules'])]:
        with (out/(label+'.log')).open('w') as log:
            subprocess.run(base+make+targets, stdout=log, stderr=subprocess.STDOUT, check=True)
        if label == 'audio-configure':
            actual = dict(line.split('=',1) for line in config.read_text().splitlines() if line.startswith('CONFIG_') and '=' in line)
            for name, value in requested.items():
                if actual.get(name) != value: raise ValueError('Kconfig rejected '+name)
    # Battery clients remain under their already-tested channel-readiness service.
    battery = out/'battery-modules'; battery.mkdir(exist_ok=True)
    for name, folder in [('pmic_glink','drivers/soc/qcom'), ('qcom_battmgr','drivers/power/supply')]:
        shutil.copyfile(source/folder/(name+'.c'), battery/(name+'.c'))
    for patch in sorted((DEVICE/'research/battery').glob('*.patch')):
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(patch)], cwd=battery, check=True)
    (battery/'Makefile').write_text('obj-m += pmic_glink.o qcom_battmgr.o\n')
    with (out/'audio-battery.log').open('w') as log:
        subprocess.run(base+make+['M=/work/battery-modules','modules'], stdout=log, stderr=subprocess.STDOUT, check=True)
    stage = out/'stage'
    if stage.exists(): shutil.rmtree(stage)
    with (out/'audio-install.log').open('w') as log:
        subprocess.run(base+make+['INSTALL_MOD_PATH=/work/stage','INSTALL_MOD_STRIP=1','DEPMOD=true','modules_install'], stdout=log, stderr=subprocess.STDOUT, check=True)
    from host_tools import command
    release = '7.2.6-opd2413-full-system03'
    module_dir = stage/'lib/modules'/release
    for name in ('build','source'):
        f = module_dir/name
        if f.is_symlink(): f.unlink()
    shutil.copyfile(config, module_dir/'config')
    subprocess.run(command('depmod')+['-b',str(stage),release], check=True)
    shutil.copyfile(out/'build/arch/arm64/boot/Image',out/'Image')
    modules = {str(f.relative_to(module_dir)):sha(f) for f in module_dir.rglob('*') if f.is_file()}
    report = dict(passed=True,profile='opd2413-audio-v1',hardware_verified=False,
        image_sha256=sha(out/'Image'),config_sha256=sha(config),modules=modules,
        compiler=image,bluetooth29_sources_preserved=True,battery_channel_wait_preserved=True)
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='modules'},indent=2))


if __name__ == '__main__': main()
