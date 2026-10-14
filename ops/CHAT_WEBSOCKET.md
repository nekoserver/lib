# AI chat over WebSocket

SSE・NDJSON・JSON Text Sequenceの切替と、この会話の閲覧専用接続は
[STREAM_FINDINGS.md](STREAM_FINDINGS.md) を参照。

`llm-chat-api-react.html` now connects to the same-origin `/lib/api/chat/ws`.
It offers Codex/Claude selection, HMAC authentication, job status, final reply,
model/effort metadata, stop-watching, and reconnect-to-result controls.
The previous standalone HTTP sample is retained as `llm-chat-http-react.html`.
No React/CDN dependency is needed for the new screen.

This is a WebSocket transport for the existing `ops/llm_worker.py` queue,
not token streaming: the queue publishes its final answer on completion.
The bridge polls the private Unix socket; the browser receives updates over
one WebSocket connection. Existing signed HTTP CGI endpoints remain available.

## Install before switching the public page

This PR does not apply production configuration. A merge alone does not start
the bridge or add a public WebSocket route. Install the service and route below
before using the new chat screen. The existing private queue must be running.

1. Create `/opt/lib-chat` as a Python 3.11+ venv and install
   `ops/chat-websocket-requirements.txt` into it (tested with Python 3.14).
2. Place the checkout at `/var/www/html/lib`, or update the service's ExecStart
   to its actual location (e.g. `/app/railway/redmine/public/lib`). Keep `ops`
   and `test` excluded from public file serving.
3. Create `/etc/lib-chat.env` (root-owned, mode 0600) containing exact allowed
   origins, e.g. `LIB_CHAT_ORIGINS=https://mynw.nekomaneki.work`.
   Add the exact Railway HTTPS preview origin separated by a comma if needed.
   Wildcards and origins without a scheme are not supported.
4. The bridge runs as `www-data`, which can read the existing
   `/etc/apache2/secrets/origin-hmac` (0640 root:www-data) and connect to
   `/run/lib-codex/worker.sock`. Do not copy the secret into the checkout.
   `LIB_CHAT_SECRET_FILE`, `LIB_CODEX_SOCKET`, and `LIB_CHAT_PORT` may override
   defaults. The bind address remains loopback-only.
5. Install `ops/chat-websocket.service` into `/etc/systemd/system/`, run
   `systemctl daemon-reload`, and enable/start `chat-websocket`.
   For a VM without systemd, have its existing bootstrap supervisor start the
   same command as www-data with the environment above. Do not launch a second
   LLM execution worker.
6. In each Caddy public listener, replace its standalone `import origin-proxy`
   with these two mutually exclusive handlers:

   ```caddyfile
   handle /lib/api/chat/ws {
       reverse_proxy 127.0.0.1:8091
   }
   handle {
       import origin-proxy
   }
   ```

   Caddy handles HTTP Upgrade automatically. External clients must use `wss`;
   the plaintext hop is loopback-only. The route bypasses Apache CGI/Passenger.
   Preserve existing TLS and ordinary-page headers in the fallback handler.
   Do not log WebSocket frames. Validate Caddy before reloading the Web proxy.
   Serve `.mjs` with a JavaScript MIME type (Apache's `AddType text/javascript
   .mjs` if its MIME database lacks this mapping).
7. Verify through the public HTTPS hostname that the handshake returns 101,
   a wrong key cannot enqueue a job, and a real request progresses through
   pending/running to done or failed. Check reconnection without resubmission.

## Wire protocol

Only the exact endpoint path is accepted (no query string). Only configured
Origin headers are accepted; missing Origin headers are rejected.

The server first sends `{"type":"challenge","nonce":"<64 hex chars>"}`.
The client responds with `{"type":"auth","signature":"<hex>"}` where the
signature is HMAC-SHA256 of `WS\n/lib/api/chat/ws\n<nonce>` using the existing
origin secret. Each connection gets a fresh nonce, so a captured signature
cannot authenticate a new connection. Authentication has a ten-second deadline.
The key itself never leaves the browser. This handshake is distinct from the
unchanged HTTP CGI HMAC protocol.

After `{"type":"authenticated"}`, send exactly one operation:

```json
{"type":"submit","engine":"codex","prompt":"Hello"}
```

or reconnect to an existing job:

```json
{"type":"resume","ask_id":"codex-00000000-0000-0000-0000-000000000000"}
```

Responses have `type: job` plus the worker's existing `ask_id`, `ask_status`,
`reply`, `ask_error`, `llm_model`, and `llm_effort` fields when present.
Unchanged snapshots are suppressed. The connection closes after a terminal
result. Invalid requests and worker outages produce a fixed error code.
Prompt limit is 16 KiB, WebSocket message limit 32 KiB; reply bounds and execution
limits remain those of the private worker. Browser keys live only in memory,
with the input cleared on use. Replies are rendered as Markdown with the
vendored markdown-it browser parser (no runtime CDN). Raw HTML is disabled;
code fences are escaped and unsafe link schemes are rejected. Headings, lists,
tables, quotes, and links are styled for desktop and mobile layouts.

Stopping reception/disconnecting never cancels the CLI job. Reconnect requires
authentication and only polls the existing ID: no automatic retry submits a new
prompt. If the connection is lost before its first job ID arrives, inspect the
worker rather than automatically resending (submission may have succeeded).

## Tests

```sh
python -m unittest discover -s test -p 'chat_websocket_test.py'
node --test test/chat_socket_test.mjs
```

Integration tests use a real local WebSocket server and a fake private Unix
queue; no paid model execution or production configuration is involved.

During PR preparation, Chromium also verified the page against this bridge
through a temporary Caddy route: wrong-key rejection, final-answer display,
safe text rendering, reconnect without duplicate submission, and mobile layout.
This local smoke check does not verify the deployed public endpoint.

## Conversation authentication session

The embedded conversation view asks for the HMAC key once. A signed POST to `/lib/api/chat/session` exchanges it for a seven-day, origin-bound, read-only observation token. The authentication result is retained in a seven-day `__Host-conversation-observer` cookie with Secure, HttpOnly, SameSite=None and Partitioned. The HMAC key is cleared and never stored. GET `/lib/api/chat/session` restores the cookie capability when an iframe or a new tab opens; DELETE clears it. Restoring reuses the original token expiry rather than extending it. An existing tab token can migrate through an authenticated Bearer GET without re-entering the key. iframe sessionStorage remains a per-tab cache. Expiry, secret rotation, clearing cookies, or browser cookie restrictions can require authentication again.

The token permits `observe` only, not job submission/resume. HTTP streams accept it as a Bearer header; WebSocket accepts `session_auth`. The origin allowlist and existing HMAC routes remain enforced. Session responses use no-store. Add `/lib/api/chat/session` to the Caddy matcher forwarding HTTP streams to port 8092. Deploy `chat_session.py`, both bridge changes, frontend modules, embed CSS and conversation-embed.html together; restart the HTTP and WebSocket bridges. The parent Worker UI PR removes its old key instructions.

The observer follows an explicitly selected conversation, never the globally newest conversation. Environment variables LIB_CHAT_APP_SOCKET and LIB_CHAT_THREAD_ID are the fallback. A root-owned private `/var/lib/lib-chat-observer/source.json` (directory 0700, file 0600) can override them with `appSocket` and `threadId`. Validate the intended conversation against the user request, then replace the file atomically. The observer checks this selection each polling cycle and switches the upstream read connection without dropping browser subscribers. Symlinks, oversized files, non-private permissions and invalid settings are rejected. After moving to another conversation, update this server-side selection; browser clients cannot select a thread or submit arbitrary RPC. A notLoaded conversation is displayed as ended rather than implying updates will arrive.

Authenticated observation automatically reconnects after transient transport/observer failures, with delays of 1, 2, 4, 8 and at most 15 seconds. Receiving conversation data resets the delay. Stop, pagehide, authentication rejection and permanent request errors do not restart observation. Retries only send observe; AI submit/resume requests are never automatically replayed. Existing open panels need a reload once to load the new fingerprinted frontend.

The embedded view omits the old read-only/job explanation and accepts start/stop controls from the fixed parent toolbar. postMessage commands require the exact approved parent origin and window.parent as source; parent state updates target that origin. The embedded duplicate buttons and authenticated form are hidden only when the parent handshake is active. In standalone use, start/stop buttons remain available. The answer section scrolls independently. If WebSocket fails to connect, an authenticated observer falls back to SSE and notifies the parent to select SSE. This fallback does not remove authentication.

Run `python3 ops/build_chat_embed.py` after updating embed frontend sources. Commit the generated content-fingerprinted assets and updated conversation-embed.html, and deploy them together. Public testing found Cloudflare serving an old embed.css from cache even with a new query string; filename fingerprints prevent cache rules that ignore query parameters from mixing old CSS or transport modules with the current application.

On initial observation and reconnection, the embedded answer section scrolls to the latest message and focuses it without an additional scroll jump. Later updates follow the bottom only while the viewer remains near the bottom, preserving an older reading position. Embedded body text is 11px and metadata 9px. Parent stream toolbar buttons use 7px text (6px on narrow screens), with protocol/start/stop controls on the same row and no visible panel heading.

Markdown links, including PRs and detected URLs, use target=_blank with noopener/noreferrer. The parent iframe must allow-popups and allow-popups-to-escape-sandbox so GitHub and other destinations open as normal tabs rather than inside the embedded frame. Embedded links have no underline. Regenerate fingerprinted assets after changing the Markdown renderer.
