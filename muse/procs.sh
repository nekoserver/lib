#!/bin/sh
# procs.sh - メモリ使用量の上位プロセスを表示する（読み取り専用）
set -u

echo "PID COMMAND RSS"
ps -eo pid=,comm=,rss= --sort=-rss 2>/dev/null | head -n 10 | awk '{printf "%s %s %.1f MiB\n", $1, $2, $3/1024}'
