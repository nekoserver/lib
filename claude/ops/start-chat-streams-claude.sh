#!/bin/sh
# Start the AI chat stream servers as www-data in the background (hosts without systemd):
#   chat_http_stream.py on 127.0.0.1:8092 (embed page, chat/ assets, SSE/NDJSON/JSON seq, sessions)
#   chat_websocket.py   on 127.0.0.1:8091 (WebSocket)
# They run from the deployed copy (LIB_WWW, default /var/www/html/lib): www-data cannot traverse /root.
# Logs: /tmp/chat-http-stream-claude.log, /tmp/chat-websocket-claude.log.
# Needs ORIGIN_HMAC_SECRET in the environment. LIB_CHAT_ORIGINS defaults to stream_routes.py's value;
# LIB_CHAT_FRAME_ORIGINS defaults to those origins plus the parent Worker's origins.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
WWW=${LIB_WWW:-/var/www/html/lib}
SECRET=${ORIGIN_HMAC_SECRET:-${HMAC_SECRET:-}}
[ -n "$SECRET" ] || { echo "Set ORIGIN_HMAC_SECRET" >&2; exit 1; }
ORIGINS=${LIB_CHAT_ORIGINS:-$(python3 "$HERE/stream_routes.py" env | sed -n 's/^LIB_CHAT_ORIGINS=//p')}
[ -n "$ORIGINS" ] || { echo "No LIB_CHAT_ORIGINS (set it, or check /etc/cloudflared/ingress.yml)" >&2; exit 1; }
FRAMES=${LIB_CHAT_FRAME_ORIGINS:-$ORIGINS,https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev,https://dynamicneko.nekoflare.workers.dev}

start() {  # name port script
  if python3 -c 'import socket,sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 1)' "$2" 2>/dev/null; then
    echo "$1 already running on 127.0.0.1:$2"
    return
  fi
  : >>"/tmp/$1-claude.log"
  chown www-data:www-data "/tmp/$1-claude.log"
  # The secret goes only into the process environment, never onto the command line.
  ORIGIN_HMAC_SECRET=$SECRET LIB_CHAT_ORIGINS=$ORIGINS LIB_CHAT_FRAME_ORIGINS=$FRAMES \
    nohup setpriv --reuid=www-data --regid=www-data --init-groups \
    python3 "$WWW/ops/$3" >>"/tmp/$1-claude.log" 2>&1 &
  echo "$1 started (pid $!)"
}
start chat-http-stream 8092 chat_http_stream.py
start chat-websocket 8091 chat_websocket.py
