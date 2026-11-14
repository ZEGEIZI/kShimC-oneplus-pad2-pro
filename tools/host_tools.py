"""Use locked host utilities with their saved dynamic-library closure."""
from pathlib import Path
import hashlib
import json

DEVICE=Path(__file__).resolve().parents[1]


def command(name):
    locked=json.loads((DEVICE/'inputs/host-tools.json').read_text())
    root=DEVICE/'inputs/local/host-tools';record=locked['tools'][name];binary=root/record['binary']
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=record['sha256']:
        raise ValueError('host utility hash mismatch: '+name)
    if record['static']:return [str(binary)]
    return [str(root/locked['loader']),'--library-path',str(root/'lib'),str(binary)]
