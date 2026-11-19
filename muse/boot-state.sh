#!/bin/sh
# boot-state.sh - 再起動の識別と、対象パッケージの巻き戻りを表示する（読み取り専用）
#
# boot_id と起動日時、稼働時間、再起動要求の有無と、対象4件（apt、nodejs、
# libc6、python3-pil）の実測版を出す。vuln-watch の status-data.json が読める
# 環境では、各行の fixed（修正版）の先頭トークンを基準版として実測と比べ、
# 巻き戻り／対応済みのチップを付ける。基準データが無い環境では判定なしに倒す。
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
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
PKGS = [('APT', 'apt'), ('Node.js (nodesource)', 'nodejs'),
        ('glibc (libc6)', 'libc6'), ('Pillow (python3-pil)', 'python3-pil')]


def esc(s):
    return html.escape(str(s), quote=True)


def chip(kind, label):
    return f'<span class="st {kind}">{esc(label)}</span>'


def read_first(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read().strip()
    except OSError:
        return ''


boot_id = read_first('/proc/sys/kernel/random/boot_id') or 'unknown'

btime = None
try:
    with open('/proc/stat', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('btime '):
                btime = int(line.split()[1])
                break
except (OSError, ValueError, IndexError):
    btime = None
boot_str = (datetime.fromtimestamp(btime, JST).strftime('%Y-%m-%d %H:%M:%S JST')
            if btime else 'unknown')

up_str = 'unknown'
up_raw = read_first('/proc/uptime')
if up_raw:
    try:
        sec = int(float(up_raw.split()[0]))
        up_str = f'{sec // 86400}日 {(sec % 86400) // 3600}時間 {(sec % 3600) // 60}分'
    except (ValueError, IndexError):
        up_str = 'unknown'

rows = [('boot_id', esc(boot_id)), ('起動日時', esc(boot_str)), ('稼働時間', esc(up_str))]

rr_path = os.environ.get('MUSE_BOOT_STATE_REBOOT_REQUIRED', '/var/run/reboot-required')
if os.path.exists(rr_path):
    rows.append(('再起動要求', chip('ng', '再起動が必要')))

print('<table class="kv">')
for label, value in rows:
    print(f'<tr><th>{esc(label)}</th><td>{value}</td></tr>')
print('</table>')


def load_fixed():
    path = os.environ.get('MUSE_BOOT_STATE_FIXED_JSON')
    if not path:
        path = os.path.expanduser('~/workspace/security-patterns/status-data.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    fixed = {}
    for row in data.get('rows') or []:
        if not isinstance(row, dict) or row.get('env') != 'この VM':
            continue
        comp = row.get('component')
        if comp not in dict(PKGS):
            continue
        token = re.split(r'[\s（]', str(row.get('fixed') or ''))[0]
        if token and token[0].isdigit():
            fixed[comp] = token
    return fixed


print('<h3>対象パッケージと巻き戻り判定</h3>')
if shutil.which('dpkg-query') is None:
    print('<p>(dpkg unavailable)</p>')
else:
    fixed = load_fixed()
    print('<table class="kv">')
    for comp, dpkg_name in PKGS:
        try:
            r = subprocess.run(['dpkg-query', '-W', '-f=${Version}', dpkg_name],
                               capture_output=True, text=True, timeout=10)
            ver = r.stdout.strip() if r.returncode == 0 else ''
        except (OSError, subprocess.SubprocessError):
            ver = ''
        if not ver:
            print(f'<tr><th>{esc(dpkg_name)}</th><td>(not installed)</td><td></td></tr>')
            continue
        if fixed is None or comp not in fixed or shutil.which('dpkg') is None:
            judge = chip('na', '判定なし')
        else:
            try:
                lt = subprocess.run(['dpkg', '--compare-versions', ver, 'lt', fixed[comp]],
                                    timeout=10).returncode == 0
            except (OSError, subprocess.SubprocessError):
                lt = None
            if lt is None:
                judge = chip('na', '判定なし')
            elif lt:
                judge = chip('ng', '巻き戻り')
            else:
                judge = chip('ok', '対応済み')
        print(f'<tr><th>{esc(dpkg_name)}</th><td>{esc(ver)}</td><td>{judge}</td></tr>')
    print('</table>')
    if fixed is None:
        print('<p class="meta">基準データ（status-data.json）が読めないため、判定はしていません。</p>')
PY
