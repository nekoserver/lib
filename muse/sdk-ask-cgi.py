#!/usr/bin/env python3
"""dashboard/ask.cgi の実体。ダッシュボードの実行系（赤）の受付口。

原則: 実行は、受ける側の承認なしには成立しない。
この CGI は送信を受け付けるだけで、実行はしない。検証を通った依頼は
「承認待ち」として登録され、受ける側ホストの sdk-approve.sh で承認された
場合にだけ実行される。

検証と記録:
- プロファイルは許可リスト（:read-only / :ask-me / :auto-review）のみ。
  :unrestricted はここからは選べない
- ワークスペースはホーム配下の既存ディレクトリのみ
- 指示は 8000 文字まで
- 受付のたびに監査ログ（~/.local/share/muse-sdk/exec-audit.jsonl）へ
  event=submitted を記録する（指示の本文は残さず、SHA-256 と文字数）
- 承認待ちの実体は ~/.local/share/muse-sdk/pending/<id>.json
"""
import datetime
import hashlib
import html
import json
import os
import sys
import urllib.parse

HOME = os.path.expanduser("~")
ALLOWED_PROFILES = (":read-only", ":ask-me", ":auto-review")
MAX_INSTRUCTION = 8000
BASE = os.path.join(HOME, ".local/share/muse-sdk")
PENDING_DIR = os.path.join(BASE, "pending")
AUDIT_LOG = os.path.join(BASE, "exec-audit.jsonl")


def page(title, body_html):
    print("Content-Type: text/html; charset=utf-8")
    print()
    print(f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  body {{ font-family: sans-serif; margin: 1em; background: #111; color: #ddd; }}
  pre {{ background: #1b1b1b; border: 1px solid #333; border-radius: 6px;
         padding: .6em 1em; overflow-x: auto; white-space: pre-wrap; }}
  .err {{ color: #f88; }}
  a {{ color: #8ab; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
{body_html}
<p><a href="index.shtml">ダッシュボードへ戻る</a></p>
</body></html>""")


def audit(event, **fields):
    rec = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "event": event}
    rec.update(fields)
    os.makedirs(BASE, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def fail(messages):
    lis = "".join(f'<li class="err">{html.escape(m)}</li>' for m in messages)
    page("受け付けできませんでした", f"<ul>{lis}</ul>")
    sys.exit(0)


def main():
    length = int(os.environ.get("CONTENT_LENGTH") or 0)
    body = sys.stdin.read(length) if length > 0 else ""
    form = urllib.parse.parse_qs(body)

    def field(name, default=""):
        values = form.get(name, [default])
        return values[0] if values else default

    instruction = field("instruction").strip()
    profile = field("profile", ":auto-review").strip()
    workspace = field("workspace").strip()

    if os.path.exists(os.path.join(BASE, "STOP")):
        audit("submit_refused", reason="emergency_stop")
        fail(["緊急停止中です。現在、実行依頼は受け付けていません"])

    errors = []
    if profile not in ALLOWED_PROFILES:
        errors.append(f"プロファイルは {', '.join(ALLOWED_PROFILES)} のみ許可されています: {profile}")
    if not instruction:
        errors.append("指示が空です")
    if len(instruction) > MAX_INSTRUCTION:
        errors.append(f"指示が長すぎます（{len(instruction)} 文字 > {MAX_INSTRUCTION}）")
    if not workspace:
        workspace = os.path.join(HOME, "sdk-ask-workspace")
        os.makedirs(workspace, exist_ok=True)
    else:
        ws_real = os.path.realpath(os.path.expanduser(workspace))
        if not (ws_real == HOME or ws_real.startswith(HOME + os.sep)):
            errors.append(f"ワークスペースはホーム配下のみ許可されています: {workspace}")
        elif not os.path.isdir(ws_real):
            errors.append(f"ワークスペースが存在しません: {workspace}")
        else:
            workspace = ws_real
    if errors:
        fail(errors)

    # 悪用の想定: 受付の洪水で承認待ちを溢れさせない（上限はホスト側の環境変数でのみ変更可）
    max_pending = int(os.environ.get("MUSE_MAX_PENDING") or 20)
    if os.path.isdir(PENDING_DIR):
        pending_count = 0
        for name in os.listdir(PENDING_DIR):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(PENDING_DIR, name), encoding="utf-8") as f:
                    if json.load(f).get("status") == "pending":
                        pending_count += 1
            except (ValueError, OSError):
                continue
        if pending_count >= max_pending:
            audit("submit_refused", reason="pending_full", count=pending_count)
            fail([f"承認待ちが上限（{max_pending} 件）に達しています。先に承認または却下してください"])

    digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    now = datetime.datetime.now().astimezone()
    req_id = now.strftime("%Y%m%d-%H%M%S") + "-" + digest[:8]
    record = {
        "id": req_id,
        "ts": now.isoformat(timespec="seconds"),
        "status": "pending",
        "profile": profile,
        "workspace": workspace,
        "instruction": instruction,
        "instruction_sha256": digest,
        "instruction_len": len(instruction),
    }
    os.makedirs(PENDING_DIR, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(PENDING_DIR, req_id + ".json"),
                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    audit("submitted", id=req_id, profile=profile, workspace=workspace,
          instruction_sha256=digest, instruction_len=len(instruction))

    body_html = (
        "<p>受け付けました。<strong>まだ実行されていません。</strong>"
        "実行には、受ける側ホストでの承認が必要です。</p>"
        "<h2>受付内容</h2>"
        f"<pre>id: {html.escape(req_id)}\nprofile: {html.escape(profile)}\n"
        f"workspace: {html.escape(workspace)}\ninstruction: {len(instruction)} 文字\n"
        f"instruction sha256: {digest}</pre>"
        "<h2>承認のしかた（受ける側ホストで）</h2>"
        f"<pre>sdk-approve.sh list\nsdk-approve.sh approve {html.escape(req_id)}</pre>"
    )
    page("承認待ちとして受け付けました", body_html)


main()
