# AI chat over WebSocket

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
   Use an interpreter accessible to `www-data`, e.g.
   `uv venv --python /usr/bin/python3 /opt/lib-chat`; an interpreter under
   `/root` cannot be used by the unprivileged service.
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
6. Inside Caddy's existing `(origin-proxy)` snippet, add this specific route
   before its existing unmatched `reverse_proxy https://127.0.0.1:8443`:

   ```caddyfile
   @chat_ws path /lib/api/chat/ws
   reverse_proxy @chat_ws 127.0.0.1:8091
   ```

   Keep each listener's top-level `import origin-proxy`. Do not place that
   import inside a `handle` block: the snippet includes the site-level `log`
   directive, which is invalid there. The matched proxy runs before the
   unmatched Apache proxy. Caddy handles HTTP Upgrade automatically.
   External clients must use `wss`;
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
with the input cleared on use. Replies are rendered using textContent.

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
