#!/bin/sh
# tailnet-health.sh - muse-vm の Tailscale ノードのヘルスを表示する（読み取り専用）
#
# tailscaled の PID と開始時刻、LocalAPI（unix ソケット）から読むノードの状態と
# 自身の IPv4、レシーバー（:8090）と API Bridge（:8080）の /health を表示する。
# 注意: tailscale CLI は呼ばない。この VM では nix 経由の CLI 呼び出しが
# デーモン再起動の副作用を持ちうるため、状態確認は ps と curl だけで行う。
# LocalAPI の応答は全文を出さず、決められた項目だけを python3 で抽出する
# （応答にはノードの公開鍵も含まれるため）。
# 仕様: SPEC.lib.tailnet-health.shtml
set -u

# アクセス制御 (REQ-TH-011): 配信側の Apache が SetEnvIf で X-Forwarded-User
# ヘッダを正規ユーザー名と照合して立てたフラグがある場合にだけ表示する。フラグが無い・
# 値が違う・認証されていない場合はすべて拒否で、拒否の1行だけを出す
# (fail-closed)。設定サンプルは dashboard/README.md の「Apache 側の前提」。
if [ "${MUSE_TAILNET_HEALTH_OK:-}" != "1" ]; then
  echo "(access denied)"
  exit 0
fi

echo "== tailscaled =="
pid=$(pgrep tailscaled | head -n 1 || true)
if [ -n "${pid:-}" ]; then
  echo "PID: $pid"
  ps -o lstart= -p "$pid" | sed 's/^/started: /'
else
  echo "not running"
fi

echo "== node =="
sock="/var/run/tailscale/tailscaled.sock"
api="http://local-tailscaled.sock/localapi/v0/status"
if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found"
elif ! command -v python3 >/dev/null 2>&1; then
  echo "(local API unavailable)"
else
  node=$(curl -s -m 5 --unix-socket "$sock" "$api" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if not isinstance(d, dict):
    sys.exit(1)
ips = d.get("TailscaleIPs") or []
v4 = ""
for x in ips:
    if isinstance(x, str) and "." in x and ":" not in x:
        v4 = x
        break
s = d.get("Self") or {}
print("state: " + str(d.get("BackendState") or "unknown"))
print("version: " + str(d.get("Version") or "unknown"))
print("IPv4: " + (v4 if v4 else "(no IPv4)"))
print("host: " + str(s.get("HostName") or "unknown"))
print("DNS: " + str(s.get("DNSName") or "unknown"))
print("online: " + ("true" if s.get("Online") else "false"))
' || true)
  if [ -n "${node:-}" ]; then
    echo "$node"
  else
    echo "(local API unavailable)"
  fi
fi

echo "== receiver (:8090) =="
if command -v curl >/dev/null 2>&1; then
  curl -s -m 5 http://127.0.0.1:8090/health || echo "(no response)"
  echo
else
  echo "curl not found"
fi

echo "== API Bridge =="
if command -v curl >/dev/null 2>&1; then
  curl -s -m 5 http://127.0.0.1:8080/health || echo "(no response)"
  echo
else
  echo "curl not found"
fi
