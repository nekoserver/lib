# Authenticated Codex and Claude CGI

Endpoint: `POST /lib/api/tunnels.rb` (also `/api/tunnels.rb` at the document root).
The existing HMAC canonical string and headers in `api/CALLER_SPEC.md` are unchanged.
AI submission and polling require a valid HMAC even for local or allowlisted clients.
GET requests can poll jobs but cannot start a new CLI run.

## Worker caller

Sign the raw JSON bytes exactly as sent:

```json
{"codex_prompt":"Read the repository and explain its structure."}
```

Claude uses `claude_prompt`. The existing `message=codex_prompt=...` and
`message=claude_prompt=...` forms are also supported. Do not double URL-encode JSON.
Supplying both engines returns `codex_and_claude_both_given`.

The Worker-compatible `message` value `codex_prompt="URL-encoded prompt"`
(or `claude_prompt="..."`) removes the surrounding double quotes and decodes
the inner value once as form URL encoding (`+` is a space; `%2B` is a plus).
Unquoted values and direct JSON prompt fields remain literal. Message submissions
wait up to 90 seconds for `reply`; if still running, they return the job ID for
polling. Direct prompt-field submissions remain asynchronous.

Submission returns `ask_id`, `via`, and `ask_status: pending`. Poll with the same
HMAC protocol (sign the full path including its query):

```text
GET /lib/api/tunnels.rb?ask_id=codex-<uuid>
```

`ask_status` is `pending`, `running`, `done`, or `failed`. Successful completion
includes `reply`. Failure includes `ask_error`. Jobs expire after 24 hours;
process restart marks unfinished jobs failed. Prompt maximum is 16 KiB, output
maximum 32 KiB, execution timeout 300 seconds, and eight jobs can wait in the queue.
Polling does not trigger another model call. Requests and replies are never cached.
Completed replies and job polls include `llm_model` and `llm_effort`.
Codex metadata comes from the native execution summary, with its answer read
from the CLI's final-answer file. Codex's `none` effort value is the CLI's
display for an unset reasoning-effort override, not a measurement of reasoning
tokens. Claude's model comes from the final main assistant event; the helper
uses `--effort low` so replies fit within the 90-second message wait.
Captured CLI output is capped at 4 MiB by the parent process, independently of
files written by the CLI runtime. The CLI's filesystem restrictions remain intact.

The caller's shared secret must match the CGI and stream service environment:
`ORIGIN_HMAC_SECRET` takes precedence over `HMAC_SECRET`. File-based fallback is
disabled. Preserve the existing value and never commit or print it. CLI
credentials remain in the dedicated helper home, inaccessible to Apache.

## VM runtime

`ops/llm_worker.py` is installed as `/usr/local/libexec/lib-llm-worker.py`.
Root creates a read-only filesystem namespace using bubblewrap, then drops all
supplementary groups and switches to `codex-web` before launching either CLI.
Only `/var/lib/codex-web` and private temporary directories are writable.
Prompts are passed through stdin, never shell interpolation or command-line options.
CGI communicates with the private Unix socket `/run/lib-codex/worker.sock`;
the worker verifies peer credentials. Job records are outside DocumentRoot.
The CLI is configured for externally sandboxed operation; the read-only mount
namespace, not Codex's disabled internal sandbox, enforces filesystem protection.

Codex is installed under `/opt/codex-web`; its account auth is stored in
`/var/lib/codex-web/.codex/auth.json`, mode 600 codex-web:codex-web.
Use dedicated credentials for this service. Neither this file nor a token goes
in the repository or Apache environment.

Claude is invoked by `/usr/local/libexec/lib-claude-helper` (installed from
`ops/claude-helper.sh`) and `/opt/claude-web/claude`. Authenticate the dedicated
user, or provision one of these files, owned by codex-web with mode 600:

- `/var/lib/codex-web/.claude/.credentials.json` (Claude account credentials)
- `/var/lib/codex-web/.claude-api-key` (Anthropic API key)
- `/var/lib/codex-web/.claude-oauth-token` (Claude setup-token output)

Missing Claude authentication produces `claude_not_authenticated` before any job
is launched. The helper disables hooks and external MCP servers.
Its `dontAsk` mode explicitly allows `Read`, `Grep`, `Glob`, `Bash`, `WebSearch`,
and `WebFetch`, so searching for current information does not require an
interactive permission prompt.

`ops/tunnel_cache.py` periodically writes a credential-free tunnel snapshot to
`/var/cache/lib-api/tunnels.json`; configure Apache's `LIB_TUNNELS_CACHE` to that
path. Older environments may continue using their existing Cloudflare helper.

Apache in this VM serves `/app/lib` on localhost TLS :8443. The Cloudflare origin
uses HTTPS and verifies the local CA. Plain :8080 only redirects to the public
HTTPS hostname. SSI `.shtml`, CGI `.cgi`, and Ruby CGI `.rb` are enabled; `.git`,
ops, and test directories are denied. Redmine's site remains available but disabled.

Start this VM setup after sleep/restart with `/app/start-web.sh`.

## Verification

```sh
/opt/rbenv/versions/4.0.7/bin/ruby test/llm_prompt_test.rb
```

Additionally verify a real signed POST, signed poll, unsigned rejection, CGI/SSI,
and local TLS certificate verification in the deployed environment.
