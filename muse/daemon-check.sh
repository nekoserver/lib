#!/bin/sh
# daemon-check.sh - muse デーモン（muse serve --listen）の起動確認（読み取り専用）
#
# 確認はシェルだけで完結する: PID の生存と well-known ソケットの有無を見る。
# 終了コード: 起動していれば 0、いなければ 1。-q で無言（cron 等向け）。
# ついでに、SDK クライアントが spawn した stdio 版ホストの数も参考表示する。
set -u

SOCK="$HOME/.local/share/muse/session-server/session-server.sock"
PIDFILE="$HOME/.local/share/muse-serve/serve.pid"
quiet=0
[ "${1:-}" = "-q" ] && quiet=1

pid=""
if [ -f "$PIDFILE" ]; then
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    pid=""
  fi
fi
if [ -z "$pid" ]; then
  pid=$(pgrep -f 'muse serve --listen' 2>/dev/null | head -n 1 || true)
fi

if [ -n "$pid" ] && [ -S "$SOCK" ]; then
  [ "$quiet" -eq 0 ] && echo "muse daemon: running (PID $pid, socket: $SOCK)"
  exit 0
fi

stdio_hosts=$(pgrep -f 'muse serve' 2>/dev/null | wc -l)
if [ "$quiet" -eq 0 ]; then
  echo "muse daemon: not running"
  echo "stdio hosts (spawned by SDK clients): $stdio_hosts"
fi
exit 1
