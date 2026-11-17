#!/usr/bin/env python3
"""承認の自動処理（SPEC.lib.muse.execution-path REQ-EP-028〜030）。

定期実行（cron）でのみ動く。承認待ちのうち、送信者が管理者であると
検証できた最新の1件だけを sdk-approve.sh の承認経路（整合性再検証・
診断ゲートを含む）で承認し、それ以外の承認待ちは却下する。

検証（すべて満たす場合のみ対象）:
  (a) sender_token が ソルト+ユーザー名+ログイン日時 の SHA-256 再計算と一致
  (b) sender_user が admin-user 設定の管理者と一致
  (c) login_at が login-state.json の最終ログイン日時と一致
  (d) 現在時刻が login_at + login_ttl_sec（auto-approve.json、既定86400）の範囲内

ソルト・管理者設定・セッション記録のいずれかが無ければ何もしない
（fail-closed）。承認・却下の実体は sdk-approve.sh が行い、監査もそちらに
残る。本スクリプトは判定を auto_selected / auto_refused として監査に残す。
"""
import datetime
import hashlib
import hmac
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, ".local/share/muse-sdk")
PENDING_DIR = os.path.join(BASE, "pending")
AUDIT_LOG = os.path.join(BASE, "exec-audit.jsonl")
SALT_PATH = os.path.join(BASE, "sender-salt")
ADMIN_PATH = os.path.join(BASE, "admin-user")
LOGIN_STATE_PATH = os.path.join(BASE, "login-state.json")
CONFIG_PATH = os.path.join(BASE, "auto-approve.json")
DEFAULT_TTL_SEC = 86400


def audit(event, **fields):
    rec = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "event": event}
    rec.update(fields)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_pending():
    out = []
    if not os.path.isdir(PENDING_DIR):
        return out
    for name in sorted(os.listdir(PENDING_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(PENDING_DIR, name), encoding="utf-8") as f:
                rec = json.load(f)
        except (ValueError, OSError):
            continue
        if rec.get("status") == "pending":
            out.append(rec)
    return out


def verify(rec, salt, admin_user, login_state, ttl_sec, now):
    user = rec.get("sender_user")
    login_at = rec.get("login_at")
    token = rec.get("sender_token")
    if not user or not login_at or not token:
        return "sender_unknown"
    expect = hashlib.sha256(f"{salt}\n{user}\n{login_at}".encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expect, token):
        return "token_mismatch"
    if user != admin_user:
        return "not_admin"
    if login_state.get("user") != user or login_state.get("login_at") != login_at:
        return "login_state_mismatch"
    try:
        login_dt = datetime.datetime.fromisoformat(login_at)
    except ValueError:
        return "login_at_unparseable"
    if login_dt.tzinfo is None:
        login_dt = login_dt.astimezone()
    if now > login_dt + datetime.timedelta(seconds=ttl_sec):
        return "login_expired"
    return None


def run_approve(action, req_id):
    env = dict(os.environ, HOME=HOME)
    run = subprocess.run([os.path.join(HERE, "sdk-approve.sh"), action, req_id],
                         capture_output=True, text=True, env=env, timeout=700)
    return run.returncode, (run.stdout + run.stderr).strip()


def main():
    if os.path.exists(os.path.join(BASE, "STOP")):
        return 0
    pending = load_pending()
    if not pending:
        return 0
    missing = [p for p in (SALT_PATH, ADMIN_PATH, LOGIN_STATE_PATH)
               if not os.path.isfile(p)]
    if missing:
        audit("auto_refused", reason="config_missing",
              missing=[os.path.basename(p) for p in missing],
              pending=len(pending))
        return 0
    with open(SALT_PATH, encoding="utf-8") as f:
        salt = f.read().strip()
    with open(ADMIN_PATH, encoding="utf-8") as f:
        admin_user = f.read().strip()
    with open(LOGIN_STATE_PATH, encoding="utf-8") as f:
        login_state = json.load(f)
    ttl_sec = DEFAULT_TTL_SEC
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            ttl_sec = int(json.load(f).get("login_ttl_sec", DEFAULT_TTL_SEC))
    now = datetime.datetime.now().astimezone()

    verified, refused = [], []
    for rec in pending:
        reason = verify(rec, salt, admin_user, login_state, ttl_sec, now)
        if reason is None:
            verified.append(rec)
        else:
            refused.append((rec, reason))
    for rec, reason in refused:
        audit("auto_refused", id=rec["id"], reason=reason,
              sender_user=rec.get("sender_user"))
    selected = verified[-1] if verified else None
    # 却下は診断ゲートの対象ではないため、承認の成否にかかわらず先に行う
    for rec in pending:
        if selected is not None and rec["id"] == selected["id"]:
            continue
        rc, out = run_approve("reject", rec["id"])
        if rc != 0:
            print(f"auto-approve: reject failed for {rec['id']}: {out}",
                  file=sys.stderr)
            return 1
    if selected is not None:
        audit("auto_selected", id=selected["id"], sender_user=selected["sender_user"])
        rc, out = run_approve("approve", selected["id"])
        if rc != 0:
            # 診断ゲートの遮断は正常な関門動作であり、依頼は承認待ちに残る（REQ-EP-018）
            if "診断ゲートで遮断" in out:
                audit("auto_blocked", id=selected["id"], reason="diag_gate")
                return 0
            print(f"auto-approve: approve failed for {selected['id']}: {out}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
