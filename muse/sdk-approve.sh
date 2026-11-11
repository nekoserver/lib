#!/bin/sh
# sdk-approve.sh - 受ける側ホストでの承認ツール（実体は sdk-approve.py）
#
# 使い方: sdk-approve.sh {list|show <id>|approve <id>|reject <id>}
# ダッシュボード（ask.cgi）は受付のみで、実行はここでの承認があって初めて成立する。
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh

PY=$(sdk_python 2>/dev/null || command -v python3)
exec "$PY" ./sdk-approve.py "$@"
