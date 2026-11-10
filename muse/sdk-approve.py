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
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
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


def diag_gate(record, req_id):
    """防波堤: SSI ダッシュボードと同じ diag.sh を承認の直前に走らせる。

    終了コード 2（FAIL あり）のときは実行しない。1（WARN）は記録して通す。
    ホスト側の環境変数でのみ制御できる（Web 側からは触れない）:
      MUSE_DIAG_GATE=off  ゲートを無効化（監査に残る）
      MUSE_DIAG_CMD=<cmd> 診断コマンドの差し替え（テスト用）
    戻り値: (通してよいか, 診断の記録 dict)
    """
    if os.environ.get("MUSE_DIAG_GATE") == "off":
        audit("diag_gate_skipped", id=req_id)
        return True, {"gate": "off"}
    cmd = os.environ.get("MUSE_DIAG_CMD") or os.path.join(HERE, "diag.sh")
    env = dict(os.environ, DIAG_QUICK="1")
    run = subprocess.run([cmd, "-s"], capture_output=True, text=True, env=env, timeout=120)
    info = {"gate": "on", "rc": run.returncode, "summary": (run.stdout or "").strip()}
    if run.returncode >= 2:
        audit("diag_blocked", id=req_id, diag_rc=run.returncode)
        print("診断ゲートで遮断しました（FAIL あり）。実行していません。", file=sys.stderr)
        print(info["summary"], file=sys.stderr)
        return False, info
    return True, info


ALLOWED_PROFILES = (":read-only", ":ask-me", ":auto-review")
MAX_INSTRUCTION = 8000


def validate_record(record, req_id):
    """悪用・改竄の想定: 承認の直前に、登録内容を再検証する。

    承認待ちファイルが登録後に書き換えられていても、ここで止める。
    - プロファイルが許可リストにあるか（手書きの :unrestricted 等を弾く）
    - ワークスペースがホーム配下の実在ディレクトリか（symlink 解決後に判定）
    - 指示の SHA-256 が登録時の値と一致するか（本文の差し替え検知）
    - 指示の長さが上限以内か
    問題があれば監査に integrity_failed を残して False を返す。
    """
    import hashlib

    problems = []
    if record.get("profile") not in ALLOWED_PROFILES:
        problems.append(f"profile not allowed: {record.get('profile')}")
    ws = os.path.realpath(os.path.expanduser(record.get("workspace") or ""))
    if not (ws == HOME or ws.startswith(HOME + os.sep)) or not os.path.isdir(ws):
        problems.append(f"workspace invalid: {record.get('workspace')}")
    instruction = record.get("instruction") or ""
    if len(instruction) > MAX_INSTRUCTION:
        problems.append(f"instruction too long: {len(instruction)}")
    digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    if digest != record.get("instruction_sha256"):
        problems.append("instruction sha256 mismatch (tampered?)")
    if problems:
        audit("integrity_failed", id=req_id, problems=problems)
        for p in problems:
            print(f"整合性チェックで拒否しました: {p}", file=sys.stderr)
        return False
    return True


def cmd_approve(req_id):
    record, path = load(req_id)
    if record.get("status") != "pending":
        print(f"承認待ちではありません（status: {record.get('status')}）", file=sys.stderr)
        sys.exit(1)
    if not validate_record(record, req_id):
        sys.exit(3)
    ok, gate_info = diag_gate(record, req_id)
    record["diag_gate"] = gate_info
    save(record, path)
    if not ok:
        sys.exit(2)
    audit("approved", id=req_id, profile=record["profile"], workspace=record["workspace"],
          instruction_sha256=record["instruction_sha256"],
          instruction_len=record["instruction_len"],
          diag_rc=gate_info.get("rc"))
    # 実行コアはホスト側の指定でのみ切り替える（Web 側からは指定できない）。
    # 既定は Python 版。MUSE_ASK_IMPL=ts で TypeScript 版になる。
    ask_script = "sdk-ts-ask.sh" if os.environ.get("MUSE_ASK_IMPL") == "ts" else "sdk-ask.sh"
    cmd = [os.path.join(HERE, ask_script), "-p", record["profile"],
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
