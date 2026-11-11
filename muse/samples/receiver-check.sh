#!/bin/sh
# receiver-check.sh [ポート] - muse-vm の受信側(receiver.py)が最善の状態かを確かめる。読み取りのみ。
# 最善の状態は muse/SPEC.scripts.md の 4.0。全部 OK なら終了コード0、1つでも NG なら1。
# 受信側を変えたとき・muse-vm を再起動したときは、これが全部 OK になるまで直す。
set -u
PORT=${1:-8090}
ENV_FILE="$HOME/.config/muse-receiver.env"
status=0
ok() { echo "OK  $1"; }
ng() { echo "NG  $1"; status=1; }

# 1. 鍵(muse-monitor と同じ TS_API_KEY)の置き場所と権限
key=''
if [ -f "$ENV_FILE" ]; then
  mode=$(stat -c %a "$ENV_FILE" 2>/dev/null || echo '?')
  case "$mode" in
    600|400) ok "鍵ファイル $ENV_FILE (権限 $mode)" ;;
    *) ng "鍵ファイルの権限が $mode。chmod 600 $ENV_FILE にする" ;;
  esac
  key=$(sed -n 's/^TS_API_KEY=//p' "$ENV_FILE" | tail -n 1)
  if [ -n "$key" ]; then ok "TS_API_KEY がある"; else ng "$ENV_FILE に TS_API_KEY= が無い"; fi
else
  ng "鍵ファイル $ENV_FILE が無い。TS_API_KEY=<muse-monitorと同じ値> を書き、chmod 600 にする"
fi

# 2. 待ち受け(127.0.0.1 だけでは muse-monitor から届かない)
listen=$(ss -tln 2>/dev/null | awk -v p=":$PORT" 'substr($4, length($4) - length(p) + 1) == p { print $4 }')
host=''
if [ -z "$listen" ]; then
  ng "ポート $PORT で何も待ち受けていない。systemctl --user start muse-receiver で起動する"
elif echo "$listen" | grep -qvE '^(127\.0\.0\.1|\[::1\]):'; then
  ok "待ち受け: $(echo $listen)"
  first=$(echo "$listen" | grep -vE '^(127\.0\.0\.1|\[::1\]):' | head -n 1)
  case "$first" in
    0.0.0.0:*|\*:*|\[::\]:*) host=127.0.0.1 ;;
    *) host=${first%:*} ;;
  esac
else
  ng "127.0.0.1 だけで待ち受けている(muse-monitor から届かない)。--host を外して(既定 0.0.0.0)起動し直す"
  host=127.0.0.1
fi

# 3. /health と 4. 鍵の一致(鍵はコマンドの引数に出さず、標準入力から curl に渡す)
if [ -n "$host" ]; then
  body=$(curl -s -m 5 "http://$host:$PORT/health" 2>/dev/null)
  case "$body" in
    *'"ok"'*) ok "/health が ok" ;;
    *) ng "/health が ok を返さない: ${body:-応答なし}" ;;
  esac
  if [ -n "$key" ]; then
    code=$(printf 'header = "Authorization: Bearer %s"\n' "$key" | curl -s -m 5 -K - -o /dev/null -w '%{http_code}' "http://$host:$PORT/queue" 2>/dev/null)
    if [ "$code" = 200 ]; then ok "鍵が受信側と一致する"; else ng "鍵で /queue が HTTP ${code:-応答なし}。受信側の TS_API_KEY と $ENV_FILE が違う"; fi
  fi
fi

exit $status
