#!/bin/sh
# sdk-ts-serve.sh - TypeScript 版の serve（Python 版と同等、ホスト側専用）
set -u
cd "$(dirname "$0")"
. ./sdk-ts-common.sh
ts_require || exit $?
exec "$NODE" ./ts/dist/serve.js "$@"
