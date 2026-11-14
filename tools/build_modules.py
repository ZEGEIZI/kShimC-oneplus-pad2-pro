#!/usr/bin/env python3
"""Rebuild final Bluetooth/UART/speaker modules using a fresh core build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from elf import canonical_module_build_id, module_load_identity
from module_metadata import stage_metadata

DEVICE=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();kernel=args.kernel.resolve();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    if not json.loads((kernel/'result.json').read_text())['passed']:raise ValueError('kernel build not verified')
    out.mkdir(parents=True);source=out/'source';source.mkdir()
    for p in (DEVICE/'kernel/current/final-modules').iterdir():shutil.copyfile(p,source/p.name)
    build=kernel/'build';objects=build/'drivers/bluetooth';image=json.loads((DEVICE/'inputs/toolchain.json').read_text())['image_id']
    prefix=['docker','run','--rm','--network=none','--user',f'{os.getuid()}:{os.getgid()}',
            '--mount',f'type=bind,src={kernel},dst=/work',
            '--mount',f'type=bind,src={out},dst=/modules',
            '--workdir','/work/build',image]
    commands=[]
    def run(label,command):
        result=subprocess.run(prefix+command,capture_output=True,text=True)
        (out/(label+'.log')).write_text(result.stdout+result.stderr)
        commands.append(dict(stage=label,returncode=result.returncode))
        if result.returncode:raise RuntimeError(label+' failed; see '+str(out/(label+'.log')))
        return result.stdout
    def compile_object(template,filename,target,module,basename=None,extra=(),fixdep=False):
        cmd=shlex.split(template.read_text().splitlines()[0].split(' := ',1)[1])
        if cmd[0]!='aarch64-linux-gnu-gcc':raise ValueError('unexpected compiler')
        name=basename or target.removesuffix('.o');dependency='/modules/.'+target+'.d'
        for i,arg in enumerate(cmd):
            if arg.startswith('-Wp,-MMD,'):cmd[i]='-Wp,-MMD,'+dependency
            elif arg.startswith('-DKBUILD_BASENAME='):cmd[i]='-DKBUILD_BASENAME="'+name+'"'
            elif arg.startswith('-DKBUILD_MODNAME='):cmd[i]='-DKBUILD_MODNAME="'+module+'"'
            elif arg.startswith('-D__KBUILD_MODNAME='):cmd[i]='-D__KBUILD_MODNAME='+module
            elif i>0 and cmd[i-1]=='-o':cmd[i]='/modules/'+target
            elif arg.endswith('.c') and not arg.startswith('-'):cmd[i]=filename
        cmd+=list(extra)
        run('compile-'+target,cmd)
        if fixdep:
            fixed=run('fixdep-'+target,['scripts/basic/fixdep',dependency,'/modules/'+target,shlex.join(cmd)])
            (out/('.'+target+'.cmd')).write_text(fixed)
    # Preserve the already verified module layout, including the original ldisc/h4.
    for name,module in [('btqca','btqca'),('hci_qca','hci_uart'),('hci_serdev','hci_uart')]:
        compile_object(objects/('.'+name+'.o.cmd'),'/modules/source/'+name+'.c',name+'.o',module,fixdep=True)
    parts=['drivers/bluetooth/hci_ldisc.o','/modules/hci_serdev.o','drivers/bluetooth/hci_h4.o','/modules/hci_qca.o']
    (out/'hci_uart.mod').write_text('\n'.join(parts)+'\n');(out/'btqca.mod').write_text('/modules/btqca.o\n')
    run('aggregate-hci_uart',['aarch64-linux-gnu-ld','-r','-EL','-maarch64elf','-z','noexecstack','-o','/modules/hci_uart.o',*parts])
    run('modpost-Bluetooth',['scripts/mod/modpost','-e','-M','-i','Module.symvers','-o','/modules/Module.symvers','/modules/btqca.o','/modules/hci_uart.o'])
    for module,template,extra in [
        ('qcom_geni_serial',build/'drivers/spi/.spi-geni-qcom.o.cmd',['-DCONFIG_SERIAL_QCOM_GENI_MODULE=1','-DCONFIG_SERIAL_QCOM_GENI_UART_PORTS=8']),
        ('opd2413_speaker_id',build/'drivers/i2c/busses/.i2c-qcom-geni.o.cmd',[])]:
        compile_object(template,'/modules/source/'+module+'.c',module+'.o',module,extra=extra,fixdep=True)
        (out/(module+'.mod')).write_text('/modules/'+module+'.o\n')
        run('modpost-'+module,['scripts/mod/modpost','-e','-M','-i','Module.symvers','-o','/modules/'+module+'.symvers','/modules/'+module+'.o'])
    for module in ['btqca','hci_uart','qcom_geni_serial','opd2413_speaker_id']:
        template=objects/('.'+module+'.mod.o.cmd') if module in ['btqca','hci_uart'] else objects/'.btqca.mod.o.cmd'
        compile_object(template,'/modules/'+module+'.mod.c',module+'.mod.o',module,basename=module+'.mod')
        run('link-'+module,['aarch64-linux-gnu-ld','-r','-EL','-maarch64elf','-z','noexecstack','--no-warn-rwx-segments','--build-id=sha1','-T','./scripts/module.lds','-o','/modules/'+module+'.ko','/modules/'+module+'.o','/modules/'+module+'.mod.o','.module-common.o'])
    locked=json.loads((DEVICE/'kernel/current/modules.lock.json').read_text());stage=out/'stage/lib/modules'/locked['kernel_release'];records=[]
    replaced={'kernel/drivers/bluetooth/btqca.ko':'btqca','kernel/drivers/bluetooth/hci_uart.ko':'hci_uart','kernel/drivers/tty/serial/qcom_geni_serial.ko':'qcom_geni_serial','kernel/drivers/misc/opd2413_speaker_id.ko':'opd2413_speaker_id'}
    for row in locked['modules']:
        rel=row['path'];target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True)
        src='/modules/'+replaced[rel]+'.ko' if rel in replaced else '/work/build/'+rel.removeprefix('kernel/')
        temporary='/modules/strip-'+Path(rel).name
        run('strip-'+Path(rel).stem,['aarch64-linux-gnu-objcopy','--strip-debug',src,temporary])
        raw=(out/Path(temporary).name).read_bytes();zero,(offset,actual_id)=canonical_module_build_id(raw)
        identity=module_load_identity(zero)
        if identity!=row['normalized_load_identity']:
            raise ValueError('module code/data/BTF/relocation identity differs: '+rel)
        result=bytearray(raw);result[offset:offset+20]=bytes.fromhex(row['reference_build_id'])
        target.write_bytes(result)
        exact=sha(target)==row['sha256'];records.append(dict(path=rel,allocated_identity_identical=True,reference_build_id_restored=True,byte_identical=exact,sha256=sha(target)))
        if not exact:raise ValueError('stripped module bytes differ after build-ID normalization: '+rel)
    metadata=stage_metadata(build,out/'stage')
    result=dict(passed=True,metadata=metadata,module_count=len(records),all_modules_byte_identical=True,only_GNU_build_id_notes_normalized=True,fresh_core_build_used=True,old_build_not_mounted=True,commands=commands,modules=records)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['commands','modules']},indent=2))


if __name__=='__main__':main()
