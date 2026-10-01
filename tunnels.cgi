#!/bin/bash
# Cloudflare tunnel status CGI (outbound API via cf).
# Prefer CLOUDFLARE_API_TOKEN if set; on empty/403 fall back to OAuth as box.
# Data source is always Cloudflare API from this origin — independent of tunnel up/down.
# Never prints OAuth/API/tunnel tokens.
set -u
ACCOUNT_ID=4eb48547c6f6a8194e6c3eb5e700463f
CF=/usr/local/bin/cf
AUTH_MODE=""
RAW=""
ERR=""

printf 'Content-Type: text/html; charset=utf-8\r\n\r\n'

fetch_with_token() {
  if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
    return 1
  fi
  local out ec=0
  out=$(CLOUDFLARE_ACCOUNT_ID="$ACCOUNT_ID" CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" \
        "$CF" tunnels list 2>&1) || ec=$?
  if [ "$ec" -ne 0 ]; then
    ERR="$out"
    return 1
  fi
  if printf '%s' "$out" | grep -qiE '403|forbidden|unauthorized|authentication'; then
    ERR="$out"
    return 1
  fi
  if [ "$out" = "[]" ] || [ -z "$out" ]; then
    return 1
  fi
  RAW="$out"
  AUTH_MODE="api-token"
  return 0
}

fetch_with_oauth() {
  local out ec=0
  out=$(sudo -n -u box /usr/local/libexec/cf-tunnels-list 2>&1) || ec=$?
  if [ "$ec" -ne 0 ]; then
    ERR="$out"
    return 1
  fi
  RAW="$out"
  AUTH_MODE="oauth"
  return 0
}

if ! fetch_with_token; then
  fetch_with_oauth || true
fi

if [ -z "$RAW" ]; then
  SAFE_ERR=$(printf '%s' "${ERR:-unknown}" | sed -E 's/[A-Za-z0-9_-]{20,}/[REDACTED]/g' | head -c 400)
  SAFE_ERR=$(printf '%s' "$SAFE_ERR" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
  printf '<div class="cf-tunnels" data-auth="error">\n'
  printf '<p class="cf-tunnels-error">Failed to list tunnels (outbound Cloudflare API).</p>\n'
  printf '<pre class="cf-tunnels-error-detail">%s</pre>\n' "$SAFE_ERR"
  printf '</div>\n'
  exit 0
fi

export TUNNELS_RAW="$RAW"
export TUNNELS_AUTH="$AUTH_MODE"
python3 - << 'PY'
import json, os, html, sys

auth = os.environ.get("TUNNELS_AUTH", "?")
raw = os.environ.get("TUNNELS_RAW", "")
try:
    data = json.loads(raw)
except Exception:
    print('<div class="cf-tunnels" data-auth="error"><p>JSON parse error.</p></div>')
    sys.exit(0)

if not isinstance(data, list):
    data = []

print(f'<div class="cf-tunnels" data-auth="{html.escape(auth)}" data-count="{len(data)}">')
print(f'<p class="cf-tunnels-meta">tunnels: {len(data)} (auth={html.escape(auth)}; source=cloudflare-api)</p>')
if not data:
    print('<p class="cf-tunnels-empty">(no tunnels)</p>')
else:
    print('<table class="cf-tunnels-table">')
    print('<thead><tr><th>name</th><th>status</th><th>id</th><th>connections</th><th>created_at</th></tr></thead>')
    print('<tbody>')
    for t in data:
        name = html.escape(str(t.get("name") or ""))
        status = html.escape(str(t.get("status") or ""))
        tid = html.escape(str(t.get("id") or ""))
        created = html.escape(str(t.get("created_at") or ""))
        conns = t.get("connections") or []
        n = len(conns)
        parts = []
        for c in conns:
            colo = html.escape(str(c.get("colo_name") or "?"))
            flag = " pending" if c.get("is_pending_reconnect") else ""
            parts.append(f"{colo}{flag}")
        conn_s = f"{n}" + (f" ({', '.join(parts)})" if parts else "")
        print(f"<tr><td>{name}</td><td>{status}</td><td><code>{tid}</code></td><td>{conn_s}</td><td>{created}</td></tr>")
    print("</tbody></table>")
print("</div>")
PY
