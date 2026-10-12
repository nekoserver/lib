#!/usr/bin/python3
"""Narrow root worker for the authenticated SSH public-key registration CGI."""
import fcntl
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import socket
import struct

spec = importlib.util.spec_from_file_location('register', '/usr/local/libexec/lib-ssh-key-register.py')
register = importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)


def main():
    directory = Path('/run/lib-ssh-keys')
    directory.mkdir(mode=0o750, exist_ok=True)
    os.chown(directory, 0, grp.getgrnam('www-data').gr_gid)
    os.chmod(directory, 0o750)
    lock = (directory / 'worker.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    path = directory / 'worker.sock'
    path.unlink(missing_ok=True)
    allowed_uid = pwd.getpwnam('www-data').pw_uid
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        os.chown(path, 0, grp.getgrnam('www-data').gr_gid)
        os.chmod(path, 0o660)
        server.listen(8)
        while True:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(3)
                try:
                    _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != allowed_uid:
                        raise ValueError('Caller not allowed')
                    with conn.makefile('rb') as stream:
                        raw = stream.readline(4097)
                    if len(raw) > 4096 or not raw.endswith(b'\n'):
                        raise ValueError('Invalid request')
                    data = json.loads(raw)
                    if not isinstance(data, dict) or list(data) != ['public_key'] or not isinstance(data['public_key'], str):
                        raise ValueError('Invalid request')
                    line, encoded, fingerprint = register.validate(data['public_key'])
                    ssh = Path('/root/.ssh')
                    ssh.mkdir(mode=0o700, exist_ok=True)
                    added = register.append_key(ssh / 'authorized_keys', line, encoded)
                    result = {'added': added, 'fingerprint': fingerprint, 'user': 'root'}
                except (ValueError, UnicodeError, KeyError, TypeError):
                    result = {'error': 'invalid_ed25519_public_key'}
                except (OSError, TimeoutError):
                    result = {'error': 'registration_unavailable'}
                try:
                    conn.sendall(json.dumps(result).encode() + b'\n')
                except OSError:
                    pass


if __name__ == '__main__':
    main()
