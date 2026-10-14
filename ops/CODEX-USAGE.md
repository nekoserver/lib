# Codex slash commands

Agent selection uses existing `message=codex_prompt="/status"` and
`message=claude_prompt="/usage"` prefixes. Direct `codex_prompt` fields are also
supported. Requests remain authenticated POSTs to `api/tunnels.rb` using the
existing `ask_id`, `ask_status`, `via`, and `reply` protocol.

## Canonical commands

| Command | Meaning and implementation |
| --- | --- |
| `/status` | Helper configuration from `config/read`, fixed execution policy, and account limits from `account/rateLimits/read`. Existing interactive session state is unavailable and explicitly excluded. |
| `/usage` | Usage menu: lists daily, weekly, cumulative views. It does not fetch quota or redeem a reset. |
| `/usage daily` | Account token activity from `account/usage/read`, daily buckets as returned. |
| `/usage weekly` | The returned daily buckets grouped into ISO calendar weeks; this text adapter reports its grouping and only includes the returned period. |
| `/usage cumulative` | Account token activity summary from `account/usage/read`. |

Native command semantics follow https://learn.chatgpt.com/docs/developer-commands?surface=cli.
This is a text adapter using supported RPCs, not the interactive TUI itself.
No model turn starts for slash commands. Unsupported commands return an explicit
unsupported response; they never silently become model questions. Missing data
is unknown, never zero or inferred. Session context remaining and quota percent
are different metrics; quota percent does not provide an exact remaining token
count or guarantee that a large request will fit. Claude commands are currently
unsupported and never use Codex's account as a substitute.

## Explicit compatibility aliases

| Alias | Canonical target | Scope |
| --- | --- | --- |
| `./usage` | `/usage` | Whole trimmed Codex command only; retained for existing callers. |
| `codex_prmpt` | `codex_prompt` | Direct field or message prefix. |
| `claude_prmpt` | `claude_prompt` | Direct field or message prefix. |
| `nemotron_prmpt` | `nemotron_prompt` | Routing only; engine execution remains unsupported. |

`/status` is not an alias of `/usage`. No other aliases are inferred.

## Operation

The worker starts App Server as the existing `codex-web` identity in the existing
read-only namespace, initializes stdio, and invokes read-only RPCs. Each RPC is
bounded to 25 seconds. Credentials and server error bodies are not returned.
`done` means a reply was produced; an unavailable/unsupported reply is not data.

Install `ops/llm_worker.py` as `/usr/local/libexec/lib-llm-worker.py`, preserving
WORKSPACE and runtime PATH defaults. Restart only after pending/running jobs
finish. Ruby CGI routing is loaded per request.

Agent slash-command results must be displayed without storing them in ordinary
AI response history (`ai_chat_shares`) in the caller Worker. Temporary job state
used by submit/poll remains necessary and is not ordinary AI response history.
The caller's separate change implements this; deploying this helper alone does
not change caller persistence.

Future Slack delivery remains separate: require a selected destination and
posting instruction, retain an idempotency key per job, keep tokens server-side.
No Slack posting is enabled.
