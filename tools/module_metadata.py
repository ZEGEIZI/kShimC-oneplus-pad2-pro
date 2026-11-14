"""Regenerate deterministic kmod indexes for the source-built167 module tree."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from host_tools import command

DEVICE=Path(__file__).resolve().parents[1]
RELEASE='7.2.6-opd2413-full-system03'


def stage_metadata(build, stage):
    tree=stage/'lib/modules'/RELEASE
    for name in ['modules.builtin','modules.builtin.modinfo']:
        shutil.copyfile(build/name,tree/name)
    objects=(build/'modules.order').read_text().splitlines()
    if not all(x.endswith('.o') and not x.startswith('kernel/') for x in objects):
        raise ValueError('unexpected core module order')
    order=['kernel/'+x[:-2]+'.ko' for x in objects]
    order+=['kernel/drivers/misc/opd2413_speaker_id.ko','kernel/drivers/tty/serial/qcom_geni_serial.ko']
    (tree/'modules.order').write_text('\n'.join(order)+'\n')
    (tree/'.armada-opd2413').write_text('opd2413-rootfs-study-v1\n')
    result=subprocess.run(command('depmod')+['-b',str(stage),RELEASE],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    locked=json.loads((DEVICE/'kernel/current/module-metadata.lock.json').read_text())
    for record in locked['files']:
        path=tree/record['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
            raise ValueError('regenerated kmod index differs: '+record['path'])
    return dict(passed=True,metadata_files=len(locked['files']),all_metadata_byte_identical=True)
