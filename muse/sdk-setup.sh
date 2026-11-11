#!/bin/sh
# sdk-setup.sh - Muse Code SDK 用の venv を用意する
#
# ~/.local/share/muse-sdk-venv に venv を作り、muse 本体と同版の
# muse-code-sdk を入れる（版を揃えるのがこの SDK の前提）。
# 冪等: 何度実行してもよい。
set -eu

VENV="$HOME/.local/share/muse-sdk-venv"

muse_path=""
if [ -x "$HOME/.local/bin/muse" ]; then
  muse_path="$HOME/.local/bin/muse"
elif command -v muse >/dev/null 2>&1; then
  muse_path=$(command -v muse)
else
  echo "muse 本体が見つかりません。" >&2
  exit 1
fi

# "Muse Code 1.4.15 (1.4.15-R8339.1)" から 1.4.15 を取る
ver=$("$muse_path" --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)
echo "muse version: $ver"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

if "$VENV/bin/pip" install -q "muse-code-sdk==$ver"; then
  echo "muse-code-sdk==$ver を入れました"
else
  echo "同版 $ver が無いため、最新の muse-code-sdk を入れます（版ずれに注意）" >&2
  "$VENV/bin/pip" install -q muse-code-sdk
fi

"$VENV/bin/python" -c 'import muse_code; print("SDK import OK")'
"$VENV/bin/pip" show muse-code-sdk | grep -E '^(Name|Version)'
echo "venv: $VENV"
