# sdk-common.sh - Muse Code SDK 連携スクリプト共通の解決処理
#
# 単体では実行せず、sdk-*.sh から読み込む（. sdk-common.sh）。
# muse 本体と、SDK 入りの python の場所を決める。

# muse 本体のパスを返す
muse_bin() {
  if [ -n "${MUSE_BIN:-}" ]; then
    echo "$MUSE_BIN"
  elif [ -x "$HOME/.local/bin/muse" ]; then
    echo "$HOME/.local/bin/muse"
  elif command -v muse >/dev/null 2>&1; then
    command -v muse
  else
    return 1
  fi
}

# SDK（muse_code パッケージ）を import できる python のパスを返す
sdk_python() {
  for p in "${MUSE_SDK_PYTHON:-}" \
           "$HOME/.local/share/muse-sdk-venv/bin/python" \
           /tmp/muse-sdk-venv*/bin/python \
           "$(command -v python3 2>/dev/null)"; do
    [ -n "$p" ] && [ -x "$p" ] || continue
    if "$p" -c 'import muse_code' >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

# SDK が見つからなければ案内を出して終了する
sdk_require() {
  if ! SDK_PY=$(sdk_python); then
    echo "Muse Code SDK が見つかりません。先に sdk-setup.sh を実行してください。" >&2
    exit 2
  fi
  if ! MUSE_BIN_PATH=$(muse_bin); then
    echo "muse 本体が見つかりません。" >&2
    exit 2
  fi
}
