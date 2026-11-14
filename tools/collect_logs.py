#!/usr/bin/env python3
"""Collect read-only OPD2413 Linux diagnostic replies over USB ACM or QEMU."""
import argparse
import fcntl
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import select
import socket
import termios
import time
import tty


def usb_identity(port):
    node = Path('/sys/class/tty') / Path(port).name / 'device'
    for parent in [node.resolve(), *node.resolve().parents]:
        if (parent / 'idVendor').is_file():
            return {n: (parent / n).read_text().strip() for n in ['idVendor','idProduct','serial']}
    raise ValueError('Not a USB ACM device: ' + str(port))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    transport = p.add_mutually_exclusive_group()
    transport.add_argument('--port', help='OPD2413 /dev/ttyACM*; default auto-detects exact identity')
    transport.add_argument('--qemu-socket', type=Path, help='Test-only Virtio console socket, not physical USB evidence')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--timeout', type=float, default=20)
    p.add_argument('--queries', nargs='+', choices=['status','dmesg','system','cpu','input','journal','journal-system','desktop','board','journal-board','console','battery'], default=['status','dmesg','system','cpu','input','board'])
    a = p.parse_args()
    a.expected_build='rootfs1'
    expected = {'idVendor':'1d6b', 'idProduct':'0104', 'serial':'OPD2413-ROOTFS1'}
    connection = None
    if a.qemu_socket:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(str(a.qemu_socket));connection.setblocking(False)
        fd = connection.fileno();identity = None
    else:
        if not a.port:
            candidates = []
            for port in glob.glob('/dev/ttyACM*'):
                try:
                    if usb_identity(port) == expected:candidates.append(port)
                except (OSError, ValueError):pass
            if len(candidates) != 1:raise SystemExit('Connect the Linux OPD2413 USB serial device, or select it with --port')
            a.port = candidates[0]
        identity = usb_identity(a.port)
        if identity != expected:raise SystemExit('USB identity is not the OPD2413 '+a.expected_build+' ACM endpoint')
        fd = os.open(a.port, os.O_RDWR | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[2] |= termios.CLOCAL | termios.CREAD
        attrs[4] = attrs[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
    out = a.out.resolve();out.mkdir(parents=True, exist_ok=False)
    responses = {}

    def request(command):
        payload = (command + '\n').encode();sent = 0;data = bytearray()
        deadline = time.monotonic() + a.timeout
        retry_at = time.monotonic() + 2
        while time.monotonic() < deadline:
            if command == 'hello' and sent == len(payload) and time.monotonic() >= retry_at:
                sent = 0;retry_at = time.monotonic() + 2
            readable, writable, _ = select.select([fd], [fd] if sent < len(payload) else [], [], 0.2)
            if writable:
                try:sent += os.write(fd, payload[sent:])
                except BlockingIOError:pass
            if readable:
                try:part = os.read(fd, 65536)
                except BlockingIOError:continue
                if not part and connection:raise RuntimeError('QEMU serial disconnected')
                data += part
                if len(data) > 3 * 1024 * 1024:raise RuntimeError('Reply exceeds diagnostic limit')
                ending = ('OPD2413_DIAG_SERIAL build='+a.expected_build+'\n').encode() if command == 'hello' else ('\nEND ' + command + '\n').encode()
                if ending in data:
                    if command == 'hello':return bytes(data)
                    beginning = ('BEGIN '+command+'\n').encode()
                    start = data.find(beginning)
                    if start >= 0:
                        finish = data.find(ending,start)+len(ending)
                        return bytes(data[start:finish])
        (out / (command + '.partial')).write_bytes(data)
        raise TimeoutError('No complete reply for ' + command)

    try:
        hello = request('hello')
        if ('OPD2413_DIAG_SERIAL build='+a.expected_build+'\n').encode() not in hello:raise RuntimeError('Wrong diagnostic build')
        (out / 'hello.txt').write_bytes(hello)
        queries=a.queries
        for command in queries:
            data = request(command)
            if not data.startswith(('BEGIN '+command+'\n').encode()):raise RuntimeError('Malformed reply for '+command)
            (out / (command + '.txt')).write_bytes(data)
            responses[command] = len(data)
            print(command, len(data), 'bytes', flush=True)
        report = {'transport':'qemu-virtconsole' if a.qemu_socket else 'usb-acm','usb_identity':identity,
                  'physical_usb_verified':not bool(a.qemu_socket),'diagnostic_build':a.expected_build,
                  'read_only_commands':True,'flashed':False,'rebooted':False,'shell_executed':False,'responses':responses}
        (out / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
        (out / 'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n'
            for f in sorted(out.iterdir()) if f.is_file()))
        print('Saved diagnostic replies:',out)
    finally:
        if connection:connection.close()
        else:os.close(fd)


if __name__ == '__main__':
    main()
