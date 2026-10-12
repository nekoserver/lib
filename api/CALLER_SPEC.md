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

### Railway list commands through message

Send POST JSON `{"message":"railway_exec=\"railway_list_services\""}`,
or GET `?message=railway_exec%3D%22railway_list_services%22`.
Quoted content is URL decoded once, as with CLI prompts. Spaces are supported:
`{"message":"railway_exec=\"service%20list%20--json\""}` executes
`railway service list --json`. A literal `+` must be encoded as `%2B`.
The command names below are also accepted inside `railway_exec="..."`.
Valid HMAC is required, including loopback and allowlisted callers; sign the
actual query or raw POST body. No LLM job or Cloudflare fetch is started.

| Name inside `railway_exec="..."` | Railway CLI |
| --- | --- |
| `railway_get_usage` | `railway usage --json` |
| `railway_list_project_usage` | `railway usage projects --json` |
| `railway_get_usage_limits` | `railway usage limit status --json` |
| `railway_get_service_status` | `railway service status --json` |
| `railway_list_environments` | `railway environment list --json` |
| `railway_list_cloud_agents` | `railway ca list --json` |
| `railway_get_status` | `railway status --json` |
| `railway_whoami` | `railway whoami --json` |
| `railway_list_projects` | `railway project list --json` |
| `railway_list_services` | `railway service list --json` |
| `railway_list_deployments` | `railway deployment list --json` |
| `railway_list_domains` | `railway domain list --json` |
| `railway_list_buckets` | `railway bucket list --json` |

Names map to fixed CLI argument arrays using the CGI's current project context.
CLI-style arguments accept the listed read commands, optionally preceded by
`railway`, and `--json` (added automatically if omitted).
Supported value options are `--project`/`-p`, `--environment`/`-e`,
`--service`/`-s`, and `--limit`; actual support depends on the CLI subcommand.
Other commands and options are rejected. Arguments are passed as an array,
without invoking a shell.
Command names also accept these options, for example
`railway_exec="railway_get_service_status%20--service%20api%20--environment%20production"`.

For service start/stop preparation, first retrieve `railway_get_status`
(project/environment/service selectors), `railway_list_environments`,
`railway_get_service_status` (current deployment state), and
`railway_list_deployments` (deployment IDs and statuses). For Cloud Agent
VM sleep/wake preparation, use `railway_list_cloud_agents`.
These routes retrieve information only; they do not start or stop resources.
The successful response's `command` is the decoded content inside the quotes.

Usage examples (quoted content is inner URL encoded):

```json
{"message":"railway_exec=\"railway%20usage\""}
{"message":"railway_exec=\"usage%20--period%20previous\""}
{"message":"railway_exec=\"usage%20projects%20--project%20strong-spirit\""}
{"message":"railway_exec=\"usage%20limit%20status%20--target%20agent\""}
```

`usage` accepts `--workspace` and `--period`; `usage projects` also accepts
`--project` and `--limit`. `usage limit status` accepts `--workspace` and
`--target`. Usage reads are workspace/billing-period scoped. Billing access is
required in the CGI execution environment. Limit changes (`set`, `update`,
`remove`) are rejected. CLI output and authentication errors are returned in
`reply` with the existing `exit_code` / `ask_status` fields.

The response contains `reply` (CLI output), `exit_code`, `ask_status`, and
`ask_error` on failure. Execution is limited to 20 seconds and output to 16 KiB.
The CGI execution user must have Railway CLI credentials and project context;
SSH session authentication alone does not establish CGI authentication.
Set `LIB_RAILWAY_BIN` to override `/usr/local/bin/railway` when needed.

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
