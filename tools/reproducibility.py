"""Reproduce reference build notes only after checking every non-note byte."""
import hashlib
import json
from pathlib import Path

DEVICE=Path(__file__).resolve().parents[1]
GNU_NOTE_HEADER=bytes.fromhex('040000001400000003000000474e5500')


def canonicalize_image(source, destination):
    locked=json.loads((DEVICE/'kernel/current/reproducibility.json').read_text())
    data=source.read_bytes()
    if len(data)!=locked['image_bytes']:raise ValueError('compiled Image size differs')
    normalized=bytearray(data);notes=[]
    for note in locked['GNU_build_id_notes']:
        offset=note['descriptor_offset']
        if normalized[offset-16:offset]!=GNU_NOTE_HEADER:raise ValueError('invalid GNU build note layout')
        notes.append(dict(descriptor_offset=offset,compiled_id=normalized[offset:offset+20].hex(),reference_id=note['reference_id']))
        normalized[offset:offset+20]=bytes(20)
    if hashlib.sha256(normalized).hexdigest()!=locked['normalized_image_sha256']:
        raise ValueError('Image code/data differs outside the two GNU build-ID descriptors')
    output=bytearray(data)
    for note in locked['GNU_build_id_notes']:
        offset=note['descriptor_offset'];output[offset:offset+20]=bytes.fromhex(note['reference_id'])
    if hashlib.sha256(output).hexdigest()!=locked['image_sha256']:
        raise ValueError('canonical Image hash mismatch')
    destination.write_bytes(output)
    return dict(passed=True,all_non_build_id_bytes_identical=True,notes=notes,compiled_image_sha256=hashlib.sha256(data).hexdigest(),canonical_image_sha256=locked['image_sha256'])
