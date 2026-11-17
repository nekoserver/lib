#!/bin/sh
# hooks.sh - hook の状態一覧（読み取り専用）
#
# ~/hooks/definitions/*.json（バックアップ *.before-* を除く）ごとに、
# 有効/無効・poll 間隔・delivery・script と、~/hooks/logs/<id>.jsonl から
# 直近の実行結果と直近の wake を出す。定義の prompt は出さない。
# 壊れた定義・ログ行があっても該当分だけ注記して続行し、rc=0 で終わる。
set -u
exec python3 - <<'PY'
import glob
import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DEFS = os.path.expanduser("~/hooks/definitions")
LOGS = os.path.expanduser("~/hooks/logs")


def fmt_ts(ms):
    if not isinstance(ms, (int, float)):
        return "?"
    return datetime.fromtimestamp(ms / 1000, JST).strftime("%Y-%m-%d %H:%M:%S JST")


def read_log(path):
    """(直近の実行, 直近の wake) を返す。読めない行は飛ばす。"""
    last = None
    last_wake = None
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None, None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if last is None:
            last = e
        if e.get("outcome") == "wake" and last_wake is None:
            last_wake = e
        if last is not None and last_wake is not None:
            break
    return last, last_wake


def fmt_run(e):
    if e is None:
        return "実行記録なし"
    s = f"{fmt_ts(e.get('finished_at_ms'))} outcome={e.get('outcome')} reason={e.get('reason')}"
    if e.get("dry_run"):
        s += " (dry_run)"
    return s


def main():
    paths = sorted(
        p for p in glob.glob(os.path.join(DEFS, "*.json"))
        if ".before-" not in os.path.basename(p)
    )
    print(f"hooks: {len(paths)} 件")
    for p in paths:
        print()
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"[{os.path.basename(p)}] 定義を読めない: {e}")
            continue
        hid = d.get("id", os.path.basename(p)[:-5])
        delivery = d.get("delivery") or []
        if isinstance(delivery, dict):
            delivery = [delivery]
        dest = ", ".join(
            (x.get("surface", "?") + (f":{x['to']}" if x.get("to") else ""))
            if isinstance(x, dict) else str(x)
            for x in delivery
        ) or "?"
        print(f"[{hid}] {'有効' if d.get('enabled') else '無効'}"
              f" / poll {d.get('poll_interval_secs')}s"
              f" / delivery {dest}")
        print(f"  script: {d.get('script_path')}")
        last, last_wake = read_log(os.path.join(LOGS, hid + ".jsonl"))
        print(f"  直近の実行: {fmt_run(last)}")
        if last_wake is not None and last_wake is not last:
            print(f"  直近の wake: {fmt_run(last_wake)}")


main()
PY
