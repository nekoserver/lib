#!/bin/sh
# cron-state.sh - 状態ファイルを残す定期実行の最終更新を表示する（読み取り専用）
#
# vm-auto-update と vuln-watch の状態ファイルについて、最終更新日時と直近の
# 見出し（日付を含む最後の行）を出す。ファイルが無い環境（コンテナ配置など）
# では「記録なし」に倒す。Muse ランタイムの cron 定義や実行履歴そのものは
# ファイルとして読めないため、対象は状態ファイルを持つものに限る。
# SSI の #exec から直接呼ばれる前提で、完成した HTML を出す（graphs.sh と
# 同じ方式）。動的な値は python3 側で HTML エスケープしてから埋め込む。
# 仕様: SPEC.lib.dashboard-state.shtml
set -u

# アクセス制御 (REQ-DS-001): 配信側の Apache が SetEnvIf で立てたフラグが
# ある場合にだけ表示する。フラグは lib vhost 全体に立つ（前提 P6）。
if [ "${MUSE_TAILNET_HEALTH_OK:-}" != "1" ]; then
  echo "(access denied)"
  exit 0
fi

exec python3 - <<'PY'
import html
import os
import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = os.path.expanduser('~/workspace/goals/musevm-kernel-build-environment/hidden_files')
FILES = [('vm-auto-update', 'vm-auto-update-state.md'),
         ('vuln-watch', 'vuln-watch-state.md')]
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def esc(s):
    return html.escape(str(s), quote=True)


def chip(kind, label):
    return f'<span class="st {kind}">{esc(label)}</span>'


print('<table class="kv">')
for label, name in FILES:
    path = os.path.join(BASE, name)
    try:
        st = os.stat(path)
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        print(f'<tr><th>{esc(label)}</th><td>{chip("na", "記録なし")}</td><td></td></tr>')
        continue
    mtime = datetime.fromtimestamp(st.st_mtime, JST).strftime('%Y-%m-%d %H:%M:%S JST')
    if not lines:
        heading = '(empty)'
    else:
        dated = [ln for ln in lines if DATE.search(ln)]
        heading = (dated[-1] if dated else lines[-1]).lstrip('#').strip()[:100]
    print(f'<tr><th>{esc(label)}</th><td>{esc(mtime)}</td><td>{esc(heading)}</td></tr>')
print('</table>')
PY
