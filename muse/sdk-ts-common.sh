# sdk-ts-common.sh - TypeScript 版 SDK ツール共通（sdk-ts-*.sh から source される）
# 前提: ホスト側でのみ使う。Web（Apache）からは直結しない。
# 呼び出しはシェルから、または承認ツール（sdk-approve.sh、MUSE_ASK_IMPL=ts）経由。

# node の解決。無ければ 127。
ts_node() {
  if [ -n "${MUSE_NODE:-}" ]; then
    printf '%s' "$MUSE_NODE"
  elif command -v node >/dev/null 2>&1; then
    command -v node
  else
    return 127
  fi
}

# dist が無ければ案内して失敗する。
ts_require() {
  NODE=$(ts_node) || { echo "node が見つかりません（20 以上が必要）。" >&2; return 127; }
  if [ ! -f "$PWD/ts/dist/ask.js" ]; then
    echo "TypeScript 版が未ビルドです。sdk-ts-setup.sh を実行してください。" >&2
    return 1
  fi
}
