#!/bin/sh
# sdk-ts-profiles.sh - TypeScript 版の profiles（Python 版と同等、ホスト側専用）
set -u
cd "$(dirname "$0")"
. ./sdk-ts-common.sh
ts_require || exit $?
exec "$NODE" ./ts/dist/profiles.js "$@"
