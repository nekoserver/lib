#!/bin/sh
# muse-status.sh - muse-vm の常駐物の状態を確認する（読み取り専用）
#
# tailscaled の PID と開始時刻、API Bridge の /health、VM の稼働時間を表示する。
# 注意: tailscale CLI は呼ばない。この VM では nix 経由の CLI 呼び出しが
# デーモン再起動の副作用を持ちうるため、状態確認は ps と curl だけで行う。
set -u

echo "== tailscaled =="
pid=$(pgrep tailscaled | head -n 1 || true)
if [ -n "${pid:-}" ]; then
  echo "PID: $pid"
  ps -o lstart= -p "$pid" | sed 's/^/started: /'
else
  echo "not running"
fi

echo "== API Bridge =="
if command -v curl >/dev/null 2>&1; then
  curl -s -m 5 http://127.0.0.1:8080/health || echo "(no response)"
  echo
else
  echo "curl not found"
fi

echo "== uptime =="
uptime
cat /proc/uptime | awk '{printf "up %d seconds\n", $1}'
