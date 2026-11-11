#!/bin/sh
# sdk-ts-setup.sh - TypeScript 版 SDK ツールの導入（依存の取得とビルド）
# ホスト側で1回実行する。@muse-code/sdk は本体 CLI と同版にピン留め。
set -eu
cd "$(dirname "$0")/ts"
npm ci
npm run build
echo "sdk-ts ready: $(node --version), @muse-code/sdk $(node -p "require('./node_modules/@muse-code/sdk/package.json').version")"
