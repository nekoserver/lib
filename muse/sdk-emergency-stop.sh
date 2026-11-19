#!/bin/sh
# sdk-emergency-stop.sh - 実行経路の緊急停止装置（ホスト側専用）
#
# 使い方:
#   sdk-emergency-stop.sh stop [理由]   停止する（STOP ファイルを置く）
#   sdk-emergency-stop.sh resume        再開する（STOP ファイルを外す）
#   sdk-emergency-stop.sh status        状態を見る
#
# 停止中は、受付（ask.cgi）も承認（sdk-approve.sh）もすべて拒否され、
# 監査ログに残る。制御不能な事態でも、ホストのシェルからこの1操作で止められる。
# Web 側からは操作できない。
set -u
BASE="${MUSE_SDK_BASE:-$HOME/.local/share/muse-sdk}"
STOPFILE="$BASE/STOP"
AUDIT="$BASE/exec-audit.jsonl"

audit() {
  mkdir -p "$BASE"
  ts=$(date -Iseconds)
  printf '{"ts": "%s", "event": "%s", "detail": "%s"}\n' "$ts" "$1" "${2:-}" >> "$AUDIT"
}

case "${1:-}" in
  stop)
    mkdir -p "$BASE"
    printf '%s %s\n' "$(date -Iseconds)" "${2:-}" > "$STOPFILE"
    chmod 600 "$STOPFILE"
    audit "emergency_stop" "${2:-}"
    echo "緊急停止しました。以後の受付・承認・実行はすべて拒否されます。"
    ;;
  resume)
    if [ -f "$STOPFILE" ]; then
      rm -f "$STOPFILE"
      audit "emergency_stop_released" ""
      echo "緊急停止を解除しました。"
    else
      echo "停止していません。"
    fi
    ;;
  status)
    if [ -f "$STOPFILE" ]; then
      echo "STOPPED: $(cat "$STOPFILE")"
    else
      echo "not stopped"
    fi
    ;;
  *)
    echo "usage: $0 {stop [reason]|resume|status}" >&2
    exit 64
    ;;
esac
