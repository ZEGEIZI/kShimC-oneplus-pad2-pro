#!/usr/bin/env python3
"""Install the tested persistent /etc Bluetooth provisioning on this tablet."""
import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
DEVICE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--address-file',type=Path,required=True);parser.add_argument('--root',type=Path,default=Path('/'));args=parser.parse_args();root=args.root.resolve()
    if root==Path('/'):
        if os.geteuid()!=0:parser.error('run as root on the tablet')
        if b'oneplus,opd2413' not in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'):raise ValueError('not an OPD2413 Linux system')
    helper=DEVICE/'rootfs/overlay/usr/libexec/armada/opd2413-btaddr'
    loader=importlib.machinery.SourceFileLoader('opd2413_btaddr',str(helper));spec=importlib.util.spec_from_loader(loader.name,loader);bt=importlib.util.module_from_spec(spec);loader.exec_module(bt)
    address=bt.read_address(args.address_file)
    config=root/'etc/armada/opd2413';config.mkdir(parents=True,exist_ok=True)
    for parent in [root/'etc',root/'etc/armada',config]:
        if parent.is_symlink():raise ValueError('symlink in provisioning path')
    existing=config/'bt-address'
    if existing.exists() and bt.read_address(existing)!=address:raise ValueError('existing device identity differs')
    unit=(DEVICE/'rootfs/overlay/usr/lib/systemd/system/opd2413-btaddr.service').read_bytes().replace(b'ExecStart=/usr/libexec/armada/opd2413-btaddr',b'ExecStart=/etc/armada/opd2413/btaddr-helper')
    payloads=[(existing,(address+'\n').encode(),0o600),(config/'btaddr-helper',helper.read_bytes(),0o700),(root/'etc/systemd/system/opd2413-btaddr.service',unit,0o644)]
    for path,data,mode in payloads:
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():raise ValueError('symlink at destination')
        path.write_bytes(data);path.chmod(mode)
    link=root/'etc/systemd/system/bluetooth.service.wants/opd2413-btaddr.service';link.parent.mkdir(parents=True,exist_ok=True)
    if not link.is_symlink():link.symlink_to('../opd2413-btaddr.service')
    elif os.readlink(link)!='../opd2413-btaddr.service':raise ValueError('unexpected service link')
    if root==Path('/'):
        subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','start','opd2413-btaddr.service'],check=True)
    print('Persistent factory Bluetooth identity and service provisioned.')

if __name__=='__main__':main()
