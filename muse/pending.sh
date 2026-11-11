#!/bin/sh
# pending.sh - SDK 実行系の承認待ち一覧を表示する（読み取り専用）
set -u
exec "$(dirname "$0")/sdk-approve.sh" list
