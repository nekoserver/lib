#!/bin/sh
# sdk-profiles.sh - ホストの権限プロファイルとモデルを一覧する（読み取り専用）
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh

sdk_require
export MUSE_BIN_PATH
"$SDK_PY" ./sdk-profiles.py
