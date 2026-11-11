#!/bin/sh
# sdk-ask.sh - Muse Code SDK で1ターンだけ指示を実行する
#
# 使い方:
#   sdk-ask.sh [-p profile] [-w workspace] [-t timeout秒] [-j] "指示文"
#   echo "指示文" | sdk-ask.sh [-p profile] [-w workspace]
#
# - 既定プロファイルは :auto-review（環境変数 MUSE_PROFILE でも指定可）。
#   指定したプロファイルが適用されなければ、黙って落とさずエラーにする。
# - :unrestricted は MUSE_ALLOW_UNRESTRICTED=1 のときだけ許可する。
# - -j を付けると、結果サマリを JSON で標準出力に出す（本文は標準エラー）。
# - 認証が無ければ、その旨のエラー（authRequired 等）が返る。
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh

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

sdk_require

export MUSE_BIN_PATH SDK_PY PROFILE WORKSPACE INSTRUCTION JSON
if command -v timeout >/dev/null 2>&1; then
  timeout "$TIMEOUT" "$SDK_PY" ./sdk-ask.py
  rc=$?
  if [ $rc -eq 124 ]; then
    echo "timeout: ${TIMEOUT}s を超えました" >&2
    exit 124
  fi
  exit $rc
else
  "$SDK_PY" ./sdk-ask.py
fi
