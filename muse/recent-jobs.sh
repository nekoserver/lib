#!/bin/sh
# recent-jobs.sh - bridge-jobs の直近の完了ジョブを表示する（読み取り専用）
#
# 使い方: recent-jobs.sh [キューディレクトリ]（既定: ~/workspace/bridge-jobs）
set -u

base=${1:-"$HOME/workspace/bridge-jobs"}
done_dir="$base/done"

if [ ! -d "$done_dir" ]; then
  echo "done dir not found: $done_dir" >&2
  exit 1
fi

ls -t "$done_dir"/*.md 2>/dev/null | head -n 10 | while read -r f; do
  date=$(date -r "$f" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "?")
  title=$(grep -m1 '^#' "$f" 2>/dev/null | sed 's/^#* *//' | cut -c1-60)
  [ -z "$title" ] && title=$(basename "$f" .md)
  echo "$date  $title"
done
