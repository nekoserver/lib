"""Framework-independent HMAC/session verification for protected HTTP resources."""
import hashlib
import hmac
import re
import time
from chat_session import valid

COOKIE = '__Host-conversation-observer'


def authorize_request(secret, *, method, path, headers, cookies, origin,
                      allowed_origins, body=b'', cookie_name=COOKIE):
    """Return bool, without I/O, cookies, redirects, logging, or global secrets.

    Supply the actual HTTP method, raw path including query, raw body bytes,
    and case-insensitive HTTP headers. ``origin`` must be a server-selected
    resource origin, never a user-selected redirect or unchecked Origin header.
    For state-changing cookie-authenticated routes, the caller must separately
    apply its CSRF policy. Explicit signature headers override saved cookies.
    """
    if not secret or origin not in allowed_origins:
        return False
    if 'X-Signature' in headers or 'X-Timestamp' in headers:
        ts = headers.get('X-Timestamp', '')
        sig = headers.get('X-Signature', '')
        if not re.fullmatch(r'[0-9]{1,12}', ts) or abs(time.time() - int(ts)) > 300:
            return False
        if not re.fullmatch(r'[0-9a-f]{64}', sig):
            return False
        canonical = f'{method.upper()}\n{path}\n{ts}\n{hashlib.sha256(body).hexdigest()}'
        expected = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    return valid(secret, cookies.get(cookie_name), origin)
