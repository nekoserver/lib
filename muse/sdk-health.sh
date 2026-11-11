#!/bin/sh
# sdk-health.sh - Muse Code SDK 連携の前提を確認する（読み取り専用）
set -u
cd "$(dirname "$0")"
. ./sdk-common.sh

echo "== muse 本体 =="
if MUSE_BIN_PATH=$(muse_bin); then
  echo "path: $MUSE_BIN_PATH"
  "$MUSE_BIN_PATH" --version
else
  echo "not found"
fi

echo "== SDK =="
if SDK_PY=$(sdk_python); then
  echo "python: $SDK_PY"
  "$SDK_PY" -c 'import importlib.metadata as m; print("muse-code-sdk:", m.version("muse-code-sdk"))'
else
  echo "not installed (run sdk-setup.sh)"
fi

echo "== 認証 =="
# 値そのものは出さない。有無だけ。
if [ -n "${META_API_KEY:-}" ]; then
  echo "META_API_KEY: set"
else
  echo "META_API_KEY: not set（ブラウザサインイン側の状態はここでは分からない）"
fi
echo "profile (MUSE_PROFILE): ${MUSE_PROFILE:-:auto-review (default)}"

echo "== serve デーモン =="
state="$HOME/.local/share/muse-serve"
if [ -f "$state/serve.pid" ] && kill -0 "$(cat "$state/serve.pid")" 2>/dev/null; then
  echo "running (PID $(cat "$state/serve.pid"), socket: ~/.local/share/muse/session-server/session-server.sock)"
else
  echo "not running"
fi
