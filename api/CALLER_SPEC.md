# Caller agent spec — `/lib/api` HMAC auth

Ruby CGI under `/lib/api/` accepts Cloudflare Worker / machine callers via
shared-secret HMAC. Human browsers on the rest of `/lib` stay on the Apache IP
allowlist. Do **not** log or echo the secret.

## Secret

Env (prefer in Worker secrets / Apache env):

- `ORIGIN_HMAC_SECRET` (preferred)
- or `HMAC_SECRET`

Origin file (www-data readable):

- `/etc/apache2/secrets/origin-hmac` (mode `640`, owner `root:www-data`)

Fallback (box only; CGI may sudo-read):

- `/home/box/.config/origin-hmac-secret`

Fill the Apache file (or set env) before production Worker traffic. Never commit
the secret; rotate by rewriting the file / secret store.

## Headers (required for non-allowlisted clients)

| Header | Value |
|--------|--------|
| `X-Timestamp` | Unix epoch **seconds** (integer string) |
| `X-Signature` | lowercase or uppercase **hex** HMAC-SHA256 (compare is case-insensitive) |

Skew: origin rejects if `|now - timestamp| > 300` seconds.

## Canonical string to sign

```
METHOD\nPATH\nTIMESTAMP\nSHA256_HEX(body)
```

Exact rules:

1. **METHOD** — HTTP method uppercased (`GET`, `POST`, …).
2. **PATH** — request path **plus query string as received** (CGI `REQUEST_URI`).
   - Example: `/lib/api/tunnels` (or `/lib/api/tunnels.rb`)
   - Example with filters: `/lib/api/tunnels?status=healthy&name=neko`
   - Do **not** strip the query; do **not** add a host or scheme.
3. **TIMESTAMP** — same decimal string as `X-Timestamp`.
4. **SHA256_HEX(body)** — hex SHA-256 of the raw request body.
   - **GET** (and any method with empty body): hash of empty string =
     `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
5. Join with a single `\n` (LF) between the four fields. **No** trailing newline
   after the body hash.

Then:

```
X-Signature = HMAC_SHA256_HEX(secret, canonical_string)
```

## Auth decision (origin CGI)

1. If `X-Timestamp` + `X-Signature` present and HMAC valid (and skew OK) → **allow**
   (even if client IP is not allowlisted).
2. Else if `REMOTE_ADDR` (after `mod_remoteip` / `CF-Connecting-IP`) is in the
   IP allowlist (or loopback) → **allow** (local curl / on-net browsers).
3. Else → **401** JSON `{"error":"unauthorized","reason":"..."}`.

Apache: `<Location /lib/api/> Require all granted` so Worker egress reaches CGI.
Other `/lib` paths remain IP-allowlisted before CGI.

## Endpoints

### Codex / Claude CLI jobs

POST JSON `{"codex_prompt":"..."}` or `{"claude_prompt":"..."}` to
`/lib/api/tunnels.rb`. `message: "codex_prompt=..."` and
`message: "claude_prompt=..."` also route to the respective CLI helper.
All AI requests and polls require valid HMAC, including allowlisted/local callers.
The signing format and headers above are unchanged. A new CLI request must use POST.

The response contains `ask_id`, `via`, and `ask_status` (`pending` or `running`).
Poll `GET /lib/api/tunnels.rb?ask_id=<ask_id>` with HMAC signing the entire query.
Completed responses contain `ask_status: "done"` and `reply`; failures contain
`ask_status: "failed"` and `ask_error`. Polls never submit a second CLI run.
See `ops/LLM_SETUP.md` for limits, installation, and credential setup.

| Method | Path | Notes |
|--------|------|--------|
| GET/POST | `/lib/api/tunnels` (`.rb` also OK) | JSON tunnel list (default) |
| GET | `/lib/api/tunnels-filter.rb` | HTML fragment (SSI); same auth |

Optional filters: `status`, `name`, `format=json|html` (query or POST JSON/form). `message` is a question to 参謀. Same HTTP 200 includes `reply` (参謀の答え) plus tunnels. `message` is the question. Omitted on 401.

## Sample: sign GET with OpenSSL + curl

Replace `SECRET` from your secret store (do not paste real secrets into tickets).

```bash
SECRET="$(sudo cat /etc/apache2/secrets/origin-hmac)"   # origin box only
TS="$(date +%s)"
METHOD=GET
PATH_Q='/lib/api/tunnels'   # or /lib/api/tunnels.rb; include ?query if used
BODY_HASH="$(printf '%s' '' | openssl dgst -sha256 -hex | awk '{print $2}')"
CANON="$(printf '%s\n%s\n%s\n%s' "$METHOD" "$PATH_Q" "$TS" "$BODY_HASH")"
SIG="$(printf '%s' "$CANON" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')"

curl -sk "https://127.0.0.1${PATH_Q}" \
  -H "X-Timestamp: ${TS}" \
  -H "X-Signature: ${SIG}" \
  -H "CF-Connecting-IP: 203.0.113.10"
```

Foreign IP without a valid signature → `401`. Valid signature → `200` JSON.

## Sample: POST JSON body

```bash
BODY='{"status":"healthy"}'
BODY_HASH="$(printf '%s' "$BODY" | openssl dgst -sha256 -hex | awk '{print $2}')"
PATH_Q='/lib/api/tunnels'
TS="$(date +%s)"
CANON="$(printf '%s\n%s\n%s\n%s' POST "$PATH_Q" "$TS" "$BODY_HASH")"
SIG="$(printf '%s' "$CANON" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')"

curl -sk "https://127.0.0.1${PATH_Q}" \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: ${TS}" \
  -H "X-Signature: ${SIG}" \
  -H "CF-Connecting-IP: 203.0.113.10" \
  --data-binary "$BODY"
```

## Worker pseudocode

```js
async function signedFetch(url, secret, init = {}) {
  const u = new URL(url);
  const path = u.pathname + u.search; // path + query as received
  const method = (init.method || "GET").toUpperCase();
  const body = init.body || "";
  const ts = Math.floor(Date.now() / 1000).toString();
  const bodyHash = await sha256Hex(body); // empty string for GET
  const canon = `${method}\n${path}\n${ts}\n${bodyHash}`;
  const sig = await hmacSha256Hex(secret, canon);
  const headers = new Headers(init.headers || {});
  headers.set("X-Timestamp", ts);
  headers.set("X-Signature", sig);
  return fetch(url, { ...init, method, body: body || undefined, headers });
}
```

## Security notes

- Never print `ORIGIN_HMAC_SECRET` / file contents in logs or agent chat.
- Prefer Worker secret binding; origin file is for the CGI process.
- Clock skew window is 300s; keep Worker/origin NTP sane.
