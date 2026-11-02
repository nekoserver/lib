#!/bin/sh
# Start the Claude variant of the chat observer in the background (hosts without systemd).
# Log: /tmp/chat-observer-claude.log. Does nothing if an observer already answers on the socket.
# LIB_CHAT_CLAUDE_SESSION defaults to following the newest Claude Code session in /root.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SOCK=${LIB_CHAT_OBSERVER_SOCKET:-/run/lib-chat-observer/observer.sock}
if [ -S "$SOCK" ] && python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])' "$SOCK" 2>/dev/null; then
  echo "observer already running on $SOCK"
  exit 0
fi
install -d -m 0700 /var/lib/lib-chat-observer
LIB_CHAT_CLAUDE_SESSION=${LIB_CHAT_CLAUDE_SESSION:-workspace:/root} \
  nohup python3 "$HERE/chat_observer_claude.py" >>/tmp/chat-observer-claude.log 2>&1 &
echo "chat_observer_claude started (pid $!)"
