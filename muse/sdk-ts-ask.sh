#!/bin/sh
# sdk-ts-ask.sh - Muse Code SDK（TypeScript 版）で1ターンだけ指示を実行する
#
# 使い方: sdk-ts-ask.sh [-p profile] [-w workspace] [-t timeout秒] [-j] "指示文"
# 意味・制約は Python 版（sdk-ask.sh）と同じ:
# - 既定プロファイルは :auto-review（MUSE_PROFILE でも指定可）
# - :unrestricted は MUSE_ALLOW_UNRESTRICTED=1 のときだけ
# - Web から直結せず、ホストのシェルか承認ツール経由でのみ呼ぶ
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh
. ./sdk-ts-common.sh

PROFILE=${MUSE_PROFILE:-:auto-review}
WORKSPACE=$PWD
TIMEOUT=600
JSON=0
while getopts 'p:w:t:j' opt; do
  case "$opt" in
    p) PROFILE=$OPTARG ;;
    w) WORKSPACE=$OPTARG ;;
    t) TIMEOUT=$OPTARG ;;
    j) JSON=1 ;;
    *) echo "usage: $0 [-p profile] [-w workspace] [-t sec] [-j] instruction" >&2; exit 64 ;;
  esac
done
shift $((OPTIND - 1))

if [ $# -gt 0 ]; then
  INSTRUCTION=$*
else
  INSTRUCTION=$(cat)
fi
if [ -z "${INSTRUCTION:-}" ]; then
  echo "指示が空です。" >&2
  exit 64
fi
if [ "$PROFILE" = ":unrestricted" ] && [ "${MUSE_ALLOW_UNRESTRICTED:-}" != "1" ]; then
  echo ":unrestricted は MUSE_ALLOW_UNRESTRICTED=1 のときだけ使えます。" >&2
  exit 64
fi

MUSE_BIN_PATH=$(muse_bin) || { echo "muse 本体が見つかりません。" >&2; exit 1; }
ts_require || exit $?

export MUSE_BIN_PATH PROFILE WORKSPACE INSTRUCTION JSON
if command -v timeout >/dev/null 2>&1; then
  timeout "$TIMEOUT" "$NODE" ./ts/dist/ask.js
  rc=$?
  if [ $rc -eq 124 ]; then
    echo "timeout: ${TIMEOUT}s を超えました" >&2
    exit 124
  fi
  exit $rc
else
  "$NODE" ./ts/dist/ask.js
fi
