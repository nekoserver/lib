#!/usr/bin/python3
"""Root helper: accept only a bare RSA public key on stdin; fixed root target."""
import base64
import binascii
import fcntl
import hashlib
import json
import os
from pathlib import Path
import struct
import sys


def validate(text):
    parts = text.strip().split()
    if len(parts) not in (2, 3) or parts[0] != 'ssh-rsa':
        raise ValueError('Expected bare RSA public key')
    wire = base64.b64decode(parts[1], validate=True)
    offset = 0
    values = []
    for _ in range(3):
        if offset + 4 > len(wire):
            raise ValueError('Truncated key')
        size = struct.unpack('>I', wire[offset:offset+4])[0]
        offset += 4
        if not size or offset + size > len(wire):
            raise ValueError('Invalid field')
        values.append(wire[offset:offset+size])
        offset += size
    if offset != len(wire) or values[0] != b'ssh-rsa':
        raise ValueError('Invalid wire key')
    for value in values[1:]:
        if value[0] & 128 or (len(value) > 1 and value[0] == 0 and not value[1] & 128):
            raise ValueError('Invalid mpint')
    exponent, modulus = (int.from_bytes(value, 'big') for value in values[1:])
    if exponent != 65537 or modulus.bit_length() not in (3072, 4096) or not modulus & 1:
        raise ValueError('Unsupported RSA key')
    encoded = base64.b64encode(wire).decode()
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(wire).digest()).decode().rstrip('=')
    return 'ssh-rsa ' + encoded + ' browser-pkcs8', encoded, fingerprint


def append_key(path, line, encoded):
    # Fixed target in main; no paths or commands accepted from the caller.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+', encoding='utf-8') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        existing = handle.read()
        # Match type+blob even when a key has authorized_keys options.
        for row in existing.splitlines():
            if row.lstrip().startswith('#'):
                continue
            fields = row.split()
            if any(fields[i:i+2] == ['ssh-rsa', encoded] for i in range(len(fields)-1)):
                return False
        handle.seek(0, os.SEEK_END)
        handle.write(('\n' if existing and not existing.endswith('\n') else '') + line + '\n')
        handle.flush()
        os.fsync(handle.fileno())
        os.fchmod(handle.fileno(), 0o600)
        return True


def main():
    if len(sys.argv) != 1:
        return 2
    try:
        raw = sys.stdin.buffer.read(4097)
        if len(raw) > 4096:
            raise ValueError('Too long')
        line, encoded, fingerprint = validate(raw.decode('ascii'))
    except (ValueError, UnicodeError, binascii.Error):
        return 2
    ssh = Path('/root/.ssh')
    ssh.mkdir(mode=0o700, exist_ok=True)
    added = append_key(ssh / 'authorized_keys', line, encoded)
    print(json.dumps({'added': added, 'fingerprint': fingerprint, 'user': 'root'}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
