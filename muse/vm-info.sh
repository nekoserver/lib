#!/bin/sh
# vm-info.sh - VM の基本情報を表示する（読み取り専用）
set -u

echo "== CPU =="
echo "vCPUs: $(nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo)"
grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//'

echo "== Memory =="
free -h | awk 'NR==1 || /^Mem:/ || /^Swap:/'

echo "== Disk =="
df -h / "$HOME" 2>/dev/null | awk 'NR==1 || !seen[$6]++'

echo "== OS =="
. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"
uname -r | sed 's/^/kernel: /'
