#!/bin/sh
# sdk-sessions.sh - ホストのセッション一覧と使用量を表示する（読み取り専用）
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh

sdk_require
export MUSE_BIN_PATH
"$SDK_PY" ./sdk-sessions.py
