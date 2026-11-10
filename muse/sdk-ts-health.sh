#!/bin/sh
# sdk-ts-health.sh - TypeScript 版の health（Python 版と同等、ホスト側専用）
set -u
cd "$(dirname "$0")"
. ./sdk-ts-common.sh
ts_require || exit $?
exec "$NODE" ./ts/dist/health.js "$@"
