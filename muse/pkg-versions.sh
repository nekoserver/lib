#!/bin/sh
# pkg-versions.sh - Nix 側と .deb 側のパッケージ版を分けて表示する（読み取り専用）
#
# Nix 側は ~/.nix-profile/manifest.json から、.deb 側は dpkg から読む。
# 「最新」はここでは引かない（ネットワーク取得は呼び出し側の判断）。
set -u

echo "== Nix profile =="
manifest="$HOME/.nix-profile/manifest.json"
if [ -f "$manifest" ]; then
  python3 - "$manifest" <<'PY'
import json, sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
for el in data.get("elements", []):
    for name in el.get("storePaths", []):
        base = name.rsplit("/", 1)[-1]
        print(base)
PY
elif [ -x "$HOME/bin/nix-env" ]; then
  # nix-env 管理のプロファイルはこちら（manifest.nix 形式）
  "$HOME/bin/nix-env" -q 2>/dev/null | sort
elif command -v nix-env >/dev/null 2>&1; then
  nix-env -q 2>/dev/null | sort
else
  echo "(nix profile unavailable)"
fi

echo
echo "== .deb (dpkg) =="
if command -v dpkg-query >/dev/null 2>&1; then
  total=$(dpkg-query -W -f='${binary:Package}\n' 2>/dev/null | wc -l)
  echo "installed packages: $total"
  for p in git curl python3 ruby qemu-system-x86 busybox; do
    v=$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null || true)
    [ -n "$v" ] && echo "$p $v"
  done
else
  echo "(dpkg not available)"
fi
