#!/bin/sh
# bridge-jobs.sh - bridge-jobs キューの一覧を表示する（読み取り専用）
#
# 処理順（優先度 priority の降順、同点は created の昇順）で queued な
# ジョブを表示し、最後に done 件数を出す。
# 使い方: bridge-jobs.sh [キューディレクトリ]（既定: ~/workspace/bridge-jobs）
set -u

base=${1:-"$HOME/workspace/bridge-jobs"}
queue="$base/queue"
done_dir="$base/done"

if [ ! -d "$queue" ]; then
  echo "queue not found: $queue" >&2
  exit 1
fi

python3 - "$queue" <<'PY'
import glob, json, os, sys

jobs = []
for path in glob.glob(os.path.join(sys.argv[1], "*.json")):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
    except Exception as e:
        print(f"(unreadable: {os.path.basename(path)}: {e})")
        continue
    if j.get("status") == "queued":
        jobs.append(j)

jobs.sort(key=lambda j: (-(j.get("priority") or 0), j.get("created") or 0))
if not jobs:
    print("queued: 0")
for j in jobs:
    req = (j.get("request") or "").replace("\n", " ")
    print(f"prio {j.get('priority', 0)}  {j.get('job_id', '?')}  {req[:80]}")
PY

if [ -d "$done_dir" ]; then
  count=$(ls "$done_dir"/*.json 2>/dev/null | wc -l)
  echo "done: $count"
fi
