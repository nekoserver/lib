#!/bin/sh
# Claude variant of lib/ops/claude-helper.sh, bound into the worker sandbox at /run/claude-helper.
set -eu
export HOME=/var/lib/codex-web
export CLAUDE_CONFIG_DIR="$HOME/.claude"
if [ -f "$HOME/.claude-api-key" ]; then
  ANTHROPIC_API_KEY=$(cat "$HOME/.claude-api-key")
  export ANTHROPIC_API_KEY
elif [ -f "$HOME/.claude-oauth-token" ]; then
  CLAUDE_CODE_OAUTH_TOKEN=$(cat "$HOME/.claude-oauth-token")
  export CLAUDE_CODE_OAUTH_TOKEN
fi
# This host has no /opt/claude-web; fall back to the npm package's native binary
# (the /opt/node22/bin/claude launcher is a stub without it).
CLAUDE=/opt/claude-web/claude
[ -x "$CLAUDE" ] || CLAUDE=/opt/node22/lib/node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai/claude-code-linux-x64/claude
exec "$CLAUDE" -p --output-format stream-json --verbose --effort low --permission-mode dontAsk \
  --allowedTools 'Read,Grep,Glob,Bash,WebSearch,WebFetch' --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --settings '{"disableAllHooks":true}' --setting-sources user --no-session-persistence
