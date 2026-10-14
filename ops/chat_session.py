"""Eight-hour, origin-bound capability for read-only conversation observation."""
import base64
import hashlib
import hmac
import json
import secrets
import time

TTL = 8 * 60 * 60

def issue(secret, origin):
    payload = json.dumps({'scope': 'observe', 'origin': origin, 'expires': int(time.time()) + TTL, 'nonce': secrets.token_hex(16)}, separators=(',', ':')).encode()
    wire = base64.urlsafe_b64encode(payload).rstrip(b'=').decode()
    signature = hmac.new(secret, ('chat-session-v1:' + wire).encode(), hashlib.sha256).hexdigest()
    return wire + '.' + signature

def valid(secret, token, origin):
    if not isinstance(token, str) or len(token) > 1024:
        return False
    try:
        wire, signature = token.split('.')
        expected = hmac.new(secret, ('chat-session-v1:' + wire).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        data = json.loads(base64.urlsafe_b64decode(wire + '=' * (-len(wire) % 4)))
        now = time.time()
        return data['scope'] == 'observe' and data['origin'] == origin and now < data['expires'] <= now + TTL
    except (ValueError, KeyError, TypeError):
        return False
