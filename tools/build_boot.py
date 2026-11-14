#!/usr/bin/env python3
"""Rebuild the current Android/default8s + Linux persistent boot and sparse."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from boot_contract import check_linux_packed
from host_tools import command
DEVICE=Path(__file__).resolve().parents[1]
BOOT_SHA='fb87bebc109c8b5fd4fb0422e66b1250147ca6f251aade86bfb07ccbeeb76de9'
SPARSE_SHA='bbd5340c91824c6da086cb460c5035928450bf7426a60dedb9e0ddd648ba9a25'
STOCK_SHA='2225e3447ee3c3833dea11aedc82f3123d3d391ab231b791c4b90a65e56169ce'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['kernel','boot-tools','dtb','initramfs','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists():parser.error('output directory must be new')
    for name in ['kernel','boot_tools','dtb','initramfs']:
        if not json.loads((getattr(args,name)/'result.json').read_text())['passed']:raise ValueError('unverified component '+name)
    out.mkdir(parents=True);stock=DEVICE/'inputs/local/stock-android-boot.img'
    if sha(stock)!=STOCK_SHA:raise ValueError('stock Android boot mismatch')
    original=stock.read_bytes();base=original[4096:4096+struct.unpack_from('<I',original,8)[0]];(out/'StockImage').write_bytes(base)
    image=(args.kernel/'Image').read_bytes()
    # Keep the verified manifest slot length; touch18 is smaller than the
    # original full-system03 Image that defined this established layout.
    if len(image)>30867456:raise ValueError('kernel exceeds verified payload slot')
    kernel=out/'LinuxImage';kernel.write_bytes(image.ljust(30867456,b'\0'))
    initrd=args.initramfs/'initramfs.img';dtb=args.dtb/'opd2413-rootfs.dtb';runtime=args.boot_tools/'kshim/kShimC.bin'
    cfg='[Pack]\nShim='+str(runtime.resolve())+'\nOutput='+str(out/'PackedKernel')+'\nDefault=Image-00\nTimeout=8000\n\n'
    for number,name,kind,path,alignment,extra in [(0,'原厂 Android','Linux',out/'StockImage',21,'BaseImage=true\n'),(1,'Linux 系统（实验）','Linux',kernel,21,'BaseImage=false\nDeviceTreeBlob=Image-02\n'),(2,'OPD2413 rootfs DTB','DTB',dtb,3,'BaseImage=false\n'),(3,'standard dracut initramfs','Blob',initrd,16,'BaseImage=false\n')]:
        cfg+=f'[Image-{number:02d}]\nName={name}\nType={kind}\nPath={path.resolve()}\nAlign={alignment}\n'+extra+'\n'
    cfg+='[Manifest]\nType=Manifest\n';(out/'build.cfg').write_text(cfg)
    with (out/'packer.log').open('w') as log:subprocess.run([str((args.boot_tools/'packer/MultiBootKernelPatcher').resolve()),str(out/'build.cfg')],stdout=log,stderr=subprocess.STDOUT,check=True)
    check=check_linux_packed((out/'PackedKernel').read_bytes(),base,runtime.read_bytes(),8000,[p.read_bytes() for p in [kernel,dtb,initrd]],payload_names=('Linux 系统（实验）','OPD2413 rootfs DTB','standard dracut initramfs'))
    # Same measured, bounded three report slots as the deployed runtime.
    header=bytearray(original[:4096]);value='pending'+'_'*73
    text=' '.join(k+'='+value for k in ['kshimreport.kshim_probe','kshimreport.kshim_s0','androidboot.kshim_s1']).encode()
    if any(header[44:1580]) or len(text)>400:raise ValueError('unexpected stock command line')
    header[44:1580]=text.ljust(1536,b'\0');source=out/'header-source.img'
    with source.open('wb') as f:f.write(header);f.write(original[4096:])
    subprocess.run([sys.executable,str(DEVICE/'tools/repack_boot_v4.py'),'--original',str(source),'--kernel',str(out/'PackedKernel'),'--output',str(out/'boot.img'),'--report',str(out/'repack.json'),'--avbtool',str(DEVICE/'tools/avbtool.py')],stdout=(out/'repack.log').open('w'),stderr=subprocess.STDOUT,check=True)
    sparse=out/'boot.sparse';subprocess.run(command('img2simg')+[str(out/'boot.img'),str(sparse),'4096'],check=True)
    subprocess.run(command('simg2img')+[str(sparse),str(out/'expanded.img')],check=True)
    if (out/'expanded.img').read_bytes()!=(out/'boot.img').read_bytes():raise ValueError('sparse expansion differs')
    actual=sha(out/'boot.img');sparse_actual=sha(sparse)
    if actual!=BOOT_SHA or sparse_actual!=SPARSE_SHA:raise ValueError('boot differs: '+actual+' / '+sparse_actual)
    source.unlink();(out/'expanded.img').unlink()
    result=dict(passed=True,all_device_code_rebuilt=True,boot_sha256=actual,sparse_sha256=sparse_actual,sparse_round_trip_verified=True,byte_identical=True,Android_default=True,timeout_ms=8000,layout=check)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='layout'},indent=2))

if __name__=='__main__':main()
