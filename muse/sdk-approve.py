#!/usr/bin/env python3
"""sdk-approve.sh の実体。受ける側ホストでの承認ツール。

使い方:
  sdk-approve.py list            承認待ちの一覧
  sdk-approve.py show <id>       依頼の全文表示
  sdk-approve.py approve <id>    承認して実行する（sdk-ask.sh を呼ぶ）
  sdk-approve.py reject <id>     却下する

承認・却下・実行はすべて監査ログ（exec-audit.jsonl）に残る。
結果は依頼ファイル（pending/<id>.json）に status と一緒に保存される。
"""
import datetime
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, ".local/share/muse-sdk")
PENDING_DIR = os.path.join(BASE, "pending")
AUDIT_LOG = os.path.join(BASE, "exec-audit.jsonl")
HERE = os.path.dirname(os.path.abspath(__file__))


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def audit(event, **fields):
    rec = {"ts": now(), "event": event}
    rec.update(fields)
    os.makedirs(BASE, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load(req_id):
    path = os.path.join(PENDING_DIR, req_id + ".json")
    if not os.path.isfile(path):
        print(f"依頼が見つかりません: {req_id}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def save(record, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def cmd_list():
    if not os.path.isdir(PENDING_DIR):
        print("（承認待ちはありません）")
        return
    rows = []
    for name in sorted(os.listdir(PENDING_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(PENDING_DIR, name), encoding="utf-8") as f:
            r = json.load(f)
        if r.get("status") == "pending":
            head = (r.get("instruction") or "").replace("\n", " ")[:60]
            rows.append(f"{r['id']}  {r['ts']}  {r['profile']}  len={r['instruction_len']}  {head}")
    print("\n".join(rows) if rows else "（承認待ちはありません）")


def cmd_show(req_id):
    record, _ = load(req_id)
    print(json.dumps(record, ensure_ascii=False, indent=2))


def cmd_approve(req_id):
    record, path = load(req_id)
    if record.get("status") != "pending":
        print(f"承認待ちではありません（status: {record.get('status')}）", file=sys.stderr)
        sys.exit(1)
    audit("approved", id=req_id, profile=record["profile"], workspace=record["workspace"],
          instruction_sha256=record["instruction_sha256"],
          instruction_len=record["instruction_len"])
    cmd = [os.path.join(HERE, "sdk-ask.sh"), "-p", record["profile"],
           "-w", record["workspace"], "-t", "600", "-j", record["instruction"]]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=660)
    try:
        summary = json.loads(run.stdout)
    except (ValueError, TypeError):
        summary = {"raw_stdout": run.stdout, "raw_stderr": run.stderr, "exit": run.returncode}
    record["status"] = "done"
    record["decided_ts"] = now()
    record["result"] = summary
    record["output"] = run.stderr or ""
    save(record, path)
    audit("executed", id=req_id, profile=record["profile"], workspace=record["workspace"],
          instruction_sha256=record["instruction_sha256"],
          instruction_len=record["instruction_len"],
          session_id=summary.get("session_id"), outcome=summary.get("outcome"),
          terminal=summary.get("terminal"),
          error_kind=(summary.get("error") or {}).get("kind") if summary.get("error") else None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if record["output"]:
        print(record["output"], file=sys.stderr)


def cmd_reject(req_id):
    record, path = load(req_id)
    if record.get("status") != "pending":
        print(f"承認待ちではありません（status: {record.get('status')}）", file=sys.stderr)
        sys.exit(1)
    record["status"] = "rejected"
    record["decided_ts"] = now()
    save(record, path)
    audit("rejected", id=req_id, profile=record["profile"], workspace=record["workspace"],
          instruction_sha256=record["instruction_sha256"],
          instruction_len=record["instruction_len"])
    print(f"rejected: {req_id}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(64)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "show" and len(sys.argv) == 3:
        cmd_show(sys.argv[2])
    elif cmd == "approve" and len(sys.argv) == 3:
        cmd_approve(sys.argv[2])
    elif cmd == "reject" and len(sys.argv) == 3:
        cmd_reject(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(64)


main()
