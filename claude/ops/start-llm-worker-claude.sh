#!/bin/sh
# Start the Claude variant of the LLM worker in the background (hosts without systemd).
# Log: /tmp/llm-worker-claude.log. Does nothing if a worker already answers on the socket.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SOCK=${LIB_CODEX_SOCKET:-/run/lib-codex/worker.sock}
if [ -S "$SOCK" ] && python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])' "$SOCK" 2>/dev/null; then
  echo "worker already running on $SOCK"
  exit 0
fi
nohup python3 "$HERE/llm_worker_claude.py" >>/tmp/llm-worker-claude.log 2>&1 &
echo "llm_worker_claude started (pid $!)"
