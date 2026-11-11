#!/bin/sh
# sdk-serve.sh - muse serve のソケットデーモン（--listen）を管理する
#
# 使い方: sdk-serve.sh {start|stop|status}
#
# SDK の通常経路はクライアントごとの spawn（sdk-ask.sh 等が使う）。
# こちらは複数クライアントで共有する常駐ホストが要る場合のもの。
# ソケットは well-known の ~/.local/share/muse/session-server/session-server.sock
# （この版の --listen は任意パスを受け付けず、well-known のみ）。
# PID とログは ~/.local/share/muse-serve/ に置く。
# 注意: デーモン上のセッションは既定で untrusted（--allow-workspace-trust は付けていない）。
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh

STATE="$HOME/.local/share/muse-serve"
SOCK="$HOME/.local/share/muse/session-server/session-server.sock"
PIDFILE="$STATE/serve.pid"
LOG="$STATE/serve.log"

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "${1:-}" in
  start)
    if is_running; then
      echo "already running (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    MUSE_BIN_PATH=$(muse_bin) || { echo "muse 本体が見つかりません。" >&2; exit 1; }
    mkdir -p "$STATE"
    nohup "$MUSE_BIN_PATH" serve --listen >>"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    i=0
    while [ $i -lt 20 ]; do
      [ -S "$SOCK" ] && break
      is_running || { echo "起動に失敗しました。ログ: $LOG" >&2; exit 1; }
      sleep 0.5
      i=$((i + 1))
    done
    echo "started (PID $(cat "$PIDFILE"), socket: $SOCK)"
    ;;
  stop)
    if is_running; then
      kill "$(cat "$PIDFILE")"
      rm -f "$PIDFILE"
      echo "stopped"
    else
      echo "not running"
    fi
    ;;
  status)
    if is_running; then
      echo "running (PID $(cat "$PIDFILE"), socket: $SOCK)"
    else
      echo "not running"
    fi
    ;;
  *)
    echo "usage: $0 {start|stop|status}" >&2
    exit 64
    ;;
esac
