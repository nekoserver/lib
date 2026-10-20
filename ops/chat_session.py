"""Seven-day, origin-bound capabilities for conversation observation and input."""
import base64
import hashlib
import hmac
import json
import secrets
import time

TTL = 7 * 24 * 60 * 60

def issue(secret, origin, scope='observe'):
    if scope not in ('observe', 'console'):
        raise ValueError('invalid_scope')
    payload = json.dumps({'scope': scope, 'origin': origin, 'expires': int(time.time()) + TTL, 'nonce': secrets.token_hex(16)}, separators=(',', ':')).encode()
    wire = base64.urlsafe_b64encode(payload).rstrip(b'=').decode()
    signature = hmac.new(secret, ('chat-session-v1:' + wire).encode(), hashlib.sha256).hexdigest()
    return wire + '.' + signature

def valid(secret, token, origin, scope='observe'):
    if not isinstance(token, str) or len(token) > 1024:
        return False
    try:
        wire, signature = token.split('.')
        expected = hmac.new(secret, ('chat-session-v1:' + wire).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        data = json.loads(base64.urlsafe_b64decode(wire + '=' * (-len(wire) % 4)))
        now = time.time()
        return data['scope'] == scope and data['origin'] == origin and now < data['expires'] <= now + TTL
    except (ValueError, KeyError, TypeError):
        return False

def remaining(secret, token, origin, scope='observe'):
    if not valid(secret, token, origin, scope):
        return 0
    wire = token.split('.')[0]
    data = json.loads(base64.urlsafe_b64decode(wire + '=' * (-len(wire) % 4)))
    return max(0, int(data['expires'] - time.time()))
