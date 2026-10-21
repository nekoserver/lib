# Key-gated page access

The conversation HTML and existing chat JS/CSS remain unchanged. The optional
page gate serves only a minimal key-entry form until the browser exchanges a
valid HMAC signature for the existing Secure/HttpOnly observation cookie.
The raw key is not sent to the server, placed in a URL, or saved by the form.
After authentication, the existing page loads and restores its existing session.
WebSocket, SSE, console permissions and demo behavior are unchanged.

## Reusable verification

`chat_access.authorize_request` has no web-framework dependency or I/O:

```python
from chat_access import authorize_request

allowed = authorize_request(
    secret,  # Existing HMAC secret as bytes; never generate a replacement here.
    method=request.method,
    path=request.raw_path,  # Includes the original query string.
    headers=request.headers,  # Case-insensitive mapping.
    cookies=request.cookies,
    origin='https://' + request.host,
    allowed_origins=configured_origins,
    body=body_bytes,  # Exact raw bytes; omit only for an empty body.
)
```

The caller chooses its response on rejection. Supply the actual method/path/body
and a trusted resource origin; do not use arbitrary client identity claims.
For writes authenticated by a cookie, separately enforce the route's CSRF policy.
An explicit bad or expired signature always rejects, even with a valid cookie.
Cookies are checked for observation scope, expiration, signature and origin.
This is shared-key authorization, not GitHub identity authorization.

`chat_site.register_site(app, secret, origins, root=..., frame_origins=...)`
attaches a minimal authentication entry at `/` and authenticated file handlers
for `/lib/conversation-embed.html` and `/lib/chat/`. It must run after API route
registration. It does not modify files or register a global middleware over
unrelated API routes. `create_app` in `chat_http_stream.py` uses this function.

Other clients can exchange signatures at the existing
`POST /lib/api/chat/session`; authenticated browser code can also reuse the
existing exported `startSession(secret)` in `chat/session.mjs`.

## Apache integration

Install the three Python files `chat_access.py`, `chat_site.py` and the updated
`chat_http_stream.py` under the same deployed `ops` directory. Restart only the
HTTP stream process on localhost:8092. Keep the existing HMAC environment.

Place these rules immediately after `RewriteEngine On` in the TLS virtual host,
before generic proxies and the static asset alias:

```apache
RewriteCond %{HTTP_HOST} ^stream\.test\.cfc\.nekomaneki\.work(?::443)?$ [NC]
RewriteRule ^/$ http://127.0.0.1:8092/ [P,L]
RewriteRule ^/lib/(conversation-embed\.html|chat/.*)$ http://127.0.0.1:8092/lib/$1 [P,L]
```

The page/assets rule deliberately applies on all aliases of this origin so an
alternate Host cannot bypass authentication. Other static files and API proxy
routes remain on their existing handlers. `run_worker_first` or equivalent is
required if another hosting layer serves these same files directly.

Configure `LIB_CHAT_FRAME_ORIGINS` with trusted embedding origins, including
`https://dynamicneko.nekoflare.workers.dev` for the current deployment. These
origins may frame the login form; they do not grant access without a key/session.
Without this setting, the allowed page origins are used as frame origins.

HTML browser requests without authentication receive only the login form. Raw
HTML/JS/CSS requests without a valid cookie/signature receive 401. Protected
responses use `private, no-store`; this cannot revoke already downloaded copies.

The current cookie lifetime is the existing seven days. New clients need the
key; a browser retaining a valid cookie can return without entering it again.

## Verification

```sh
/opt/lib-chat/bin/python -m unittest discover -s test -p 'chat*test.py'
```

Also check public unauthenticated HTML/assets, invalid signatures, the signed
session exchange, valid-cookie assets, alternate-host aliases and authenticated
WebSocket conversation delivery. Never include keys, tokens, signatures or
conversation text in shared logs. A real browser iframe interaction should also
be checked separately; HTTP and protocol tests alone do not prove browser UI use.
