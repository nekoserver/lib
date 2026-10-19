"""Read both fixed HMAC configs without executing shell or exposing key values."""
import hashlib
import hmac
import logging
import os
from pathlib import Path
import re
import shlex

SECRET_FILES = ('/etc/lib-hmac.env', '/etc/lib-chat.env')


class KeyRing(bytes):
    def __new__(cls, keys):
        instance = super().__new__(cls, keys[0])
        instance.keys = tuple(keys)
        return instance


def load_secret(paths=SECRET_FILES):
    values = [os.environ.get(name, '').strip() for name in ('ORIGIN_HMAC_SECRET', 'HMAC_SECRET')]
    for path in paths:
        try:
            lines = Path(path).read_text().splitlines()
        except (FileNotFoundError, PermissionError):
            continue
        for line in lines:
            match = re.fullmatch(r'\s*(?:export\s+)?(?:ORIGIN_HMAC_SECRET|HMAC_SECRET)=(.*)', line)
            if match:
                try:
                    parts = shlex.split(match[1])
                except ValueError:
                    continue
                if len(parts) == 1:
                    values.append(parts[0].strip())
    keys = list(dict.fromkeys(value.encode() for value in values if value))
    if not keys:
        raise RuntimeError('Configure the existing origin HMAC secret before starting.')
    if len(keys) > 1:
        logging.warning('HMAC: configured keys differ; accepting either configured key')
    return KeyRing(keys)


def matches(secret, message, signature):
    return any(hmac.compare_digest(hmac.new(key, message, hashlib.sha256).hexdigest(), signature)
               for key in getattr(secret, 'keys', (secret,)))
