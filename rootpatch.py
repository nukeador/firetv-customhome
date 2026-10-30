"""Reconstruct the reviewed home-only helper from the exact upstream release."""
import bz2
import hashlib
from pathlib import Path
from downloads import request

UPSTREAM_URL = 'https://github.com/Delitants/GhostLock/releases/download/kara-PS7713-5443-v1/kara-ghostlock-PS7713-5443.arm'
UPSTREAM_SHA256 = 'a42185d743ee1d4c9c46c1e35f5fa0a40f5e9a7f81450308c3eab297677847d5'
PATCH_SHA256 = '14c1db49a5444143c3c25cbfacf0b35e3477c8b88e0fccde96c416e685806f6b'
OUTPUT_SHA256 = '46804934a67e34f260ee324161ec26288bc95a464fe02cb8dde93feb50d2aec0'


def number(data):
    if len(data) != 8:
        raise ValueError('Truncated bsdiff integer')
    value = data[7] & 0x7f
    for i in range(6, -1, -1):
        value = value * 256 + data[i]
    return -value if data[7] & 0x80 else value


def apply_patch(original, patch):
    if len(patch) < 32 or patch[:8] != b'BSDIFF40':
        raise ValueError('Invalid patch')
    ctrl_size, diff_size, new_size = number(patch[8:16]), number(patch[16:24]), number(patch[24:32])
    if min(ctrl_size, diff_size, new_size) < 0 or new_size > 4 * 1024 * 1024 or 32 + ctrl_size + diff_size > len(patch):
        raise ValueError('Invalid patch sizes')
    ctrl = bz2.decompress(patch[32:32 + ctrl_size])
    diff = bz2.decompress(patch[32 + ctrl_size:32 + ctrl_size + diff_size])
    extra = bz2.decompress(patch[32 + ctrl_size + diff_size:])
    new = bytearray(new_size)
    old_pos = new_pos = ctrl_pos = diff_pos = extra_pos = 0
    while new_pos < new_size:
        if ctrl_pos + 24 > len(ctrl):
            raise ValueError('Truncated patch control')
        x = number(ctrl[ctrl_pos:ctrl_pos + 8])
        y = number(ctrl[ctrl_pos + 8:ctrl_pos + 16])
        z = number(ctrl[ctrl_pos + 16:ctrl_pos + 24])
        ctrl_pos += 24
        if x < 0 or y < 0 or new_pos + x + y > new_size or diff_pos + x > len(diff) or extra_pos + y > len(extra):
            raise ValueError('Invalid patch control')
        for i in range(x):
            index = old_pos + i
            old = original[index] if 0 <= index < len(original) else 0
            new[new_pos + i] = (diff[diff_pos + i] + old) & 0xff
        new_pos += x
        old_pos += x
        diff_pos += x
        new[new_pos:new_pos + y] = extra[extra_pos:extra_pos + y]
        new_pos += y
        old_pos += z
        extra_pos += y
    return bytes(new)


def reconstruct(patch_path, output):
    original = request(UPSTREAM_URL, 4 * 1024 * 1024)
    patch = Path(patch_path).read_bytes()
    if hashlib.sha256(original).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('Upstream GhostLock SHA-256 mismatch')
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise ValueError('Home-only patch SHA-256 mismatch')
    result = apply_patch(original, patch)
    if hashlib.sha256(result).hexdigest() != OUTPUT_SHA256:
        raise ValueError('Reconstructed helper SHA-256 mismatch')
    Path(output).write_bytes(result)
    return Path(output)


def reconstruct_sheldon(patch_path, output):
    url = 'https://github.com/nukeador/firetv-customhome/releases/download/0.1.12/ghostlock-sheldon-1.1.0-original-arm'
    original = request(url, 4 * 1024 * 1024)
    patch = Path(patch_path).read_bytes()
    if hashlib.sha256(original).hexdigest() != 'e6c5afb143ebf03114b941b1298b0d8b9b7d156071d6d37deb4fdcb09fbd1b32':
        raise ValueError('Original GhostLock SHA-256 mismatch')
    if hashlib.sha256(patch).hexdigest() != 'dcff3d3af2f695f3b0c1a668094a27682ae28e577e9852ca948792e6f45bd75d':
        raise ValueError('Sheldon patch SHA-256 mismatch')
    result = apply_patch(original, patch)
    if hashlib.sha256(result).hexdigest() != '7db65c5570309b20f6664cf48ed2d141ae9d0a42a2ed35035d79662269d96ff2':
        raise ValueError('Reconstructed Sheldon helper SHA-256 mismatch')
    Path(output).write_bytes(result)
    return Path(output)
