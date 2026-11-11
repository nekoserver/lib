#!/bin/sh
# ports.sh - 待ち受けポートの一覧を表示する（読み取り専用）
set -u

if command -v ss >/dev/null 2>&1; then
  ss -tuln 2>/dev/null | awk '$1 ~ /^(tcp|udp)/ {print $1, $5}'
else
  echo "ss not found"
fi
