#!/bin/sh
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
exec /opt/claude-web/claude -p --output-format stream-json --verbose --effort low --permission-mode dontAsk \
  --allowedTools 'Read,Grep,Glob,Bash,WebSearch,WebFetch' --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --settings '{"disableAllHooks":true}' --setting-sources user --no-session-persistence
