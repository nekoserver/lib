# Codex usage commands

Authenticated POST requests to `api/tunnels.rb` accept `message=/usage`,
`message=/status`, or `message=./usage`. Explicit `codex_prompt=/usage` also works.
Existing submit/poll response fields (`ask_id`, `ask_status`, `reply`) are retained.

Select the agent using the existing prefix: `message=codex_prompt="/usage"`
or `message=claude_prompt="/usage"`. The spelling `codex_prmpt` (and equivalent
prefixes for other engines) is accepted as an alias, both in `message` and as a
direct request field. Claude quota commands currently return an explicit
unsupported/unknown message without running a model or reading Codex's account.
Other unsupported engines retain the existing `unsupported_engine` response.

The queue worker intercepts exact commands before starting a model turn. It starts
Codex App Server as the existing `codex-web` identity in the existing read-only
namespace, initializes the stdio protocol, and calls `account/rateLimits/read`.
It returns remaining percentages and UTC reset times. Missing limits or failed
requests are reported as unknown, never inferred from a model answer. Requests
are bounded to 25 seconds; credentials and server error bodies are not returned.

Deployment: install `ops/llm_worker.py` as `/usr/local/libexec/lib-llm-worker.py`,
preserving the deployment's `WORKSPACE` and runtime PATH defaults. Restart the
worker only after pending/running jobs finish. `api/llm_prompt.rb` is loaded per CGI
request and needs no server restart.

Future: post completed Codex results to Slack through a separate delivery adapter.
Require an explicitly selected destination and posting instruction; retain a
delivery key per job to prevent duplicate messages on retries. Keep Slack tokens
server-side. No Slack posting is enabled by this change.

Protocol: https://learn.chatgpt.com/docs/app-server
