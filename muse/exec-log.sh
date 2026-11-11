#!/bin/sh
# exec-log.sh - SDK 実行系の監査ログを表示する（読み取り専用）
set -u

LOG="$HOME/.local/share/muse-sdk/exec-audit.jsonl"
if [ ! -f "$LOG" ]; then
  echo "（実行ログはまだありません）"
  exit 0
fi

python3 - "$LOG" <<'PY'
import json, sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()[-10:]
for line in reversed(lines):
    try:
        r = json.loads(line)
    except ValueError:
        continue
    result = r.get("error_kind") or f"{r.get('outcome')}/{r.get('terminal')}"
    event = r.get("event") or "executed"
    print(f"{r.get('ts')}  {event}  {r.get('profile')}  {result}  "
          f"len={r.get('instruction_len')}  sha256={str(r.get('instruction_sha256'))[:12]}…  "
          f"ws={r.get('workspace')}")
PY
