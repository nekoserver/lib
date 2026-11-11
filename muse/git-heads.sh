#!/bin/sh
# git-heads.sh - ローカルの git リポジトリの状態を表示する（読み取り専用）
#
# ~/muse-vm-hacks と ~/workspace 配下（深さ3まで）の .git を探し、
# ブランチ、先頭コミット、未コミット変更数、未 push コミット数を出す。
# ネットワークには出ない（fetch はしない。未 push 数は手元の upstream 情報との差）。
set -u

find_repos() {
  [ -d "$HOME/muse-vm-hacks/.git" ] && echo "$HOME/muse-vm-hacks"
  find "$HOME/workspace" -maxdepth 3 -name .git -type d 2>/dev/null | sed 's|/.git$||'
}

find_repos | sort -u | while read -r repo; do
  branch=$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null) || continue
  head=$(git -C "$repo" log -1 --format='%h %s' 2>/dev/null | cut -c1-60)
  dirty=$(git -C "$repo" status --porcelain 2>/dev/null | wc -l)
  ahead=$(git -C "$repo" rev-list --count '@{u}..HEAD' 2>/dev/null || echo "?")
  echo "${repo#$HOME/} [$branch] $head (dirty: $dirty, unpushed: $ahead)"
done
