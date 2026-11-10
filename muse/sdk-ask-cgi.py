#!/usr/bin/env python3
"""dashboard/ask.cgi の実体。ダッシュボードの実行系（赤）の入口。

厳密な精査のための仕掛け:
- プロファイルは許可リスト（:read-only / :ask-me / :auto-review）のみ。
  :unrestricted はここからは選べない
- ワークスペースはホーム配下の既存ディレクトリのみ
- 指示は 8000 文字まで
- 実行のたびに監査ログ（~/.local/share/muse-sdk/exec-audit.jsonl）へ
  時刻・プロファイル・ワークスペース・指示の SHA-256 と文字数・結果を残す
  （指示の本文そのものはログに残さない）
- 結果は要約せず、sdk-ask.sh -j の JSON 全文と本文をそのまま表示する
"""
import datetime
import hashlib
import html
import json
import os
import subprocess
import sys
import urllib.parse

HOME = os.path.expanduser("~")
ALLOWED_PROFILES = (":read-only", ":ask-me", ":auto-review")
MAX_INSTRUCTION = 8000
AUDIT_LOG = os.path.join(HOME, ".local/share/muse-sdk/exec-audit.jsonl")
HERE = os.path.dirname(os.path.abspath(__file__))


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


def fail(messages):
    lis = "".join(f'<li class="err">{html.escape(m)}</li>' for m in messages)
    page("実行できませんでした", f"<ul>{lis}</ul>")
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

    cmd = [
        os.path.join(HERE, "sdk-ask.sh"),
        "-p", profile,
        "-w", workspace,
        "-t", "600",
        "-j", instruction,
    ]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=660)
    try:
        summary = json.loads(run.stdout)
    except (ValueError, TypeError):
        summary = {"raw_stdout": run.stdout, "raw_stderr": run.stderr, "exit": run.returncode}

    digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    audit = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "profile": profile,
        "workspace": workspace,
        "instruction_sha256": digest,
        "instruction_len": len(instruction),
        "session_id": summary.get("session_id"),
        "outcome": summary.get("outcome"),
        "terminal": summary.get("terminal"),
        "error_kind": (summary.get("error") or {}).get("kind") if summary.get("error") else None,
    }
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit, ensure_ascii=False) + "\n")

    body_text = run.stderr or ""
    body_html = (
        "<h2>結果サマリ（全文）</h2>"
        f"<pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>"
        "<h2>本文</h2>"
        f"<pre>{html.escape(body_text)}</pre>"
        "<h2>精査情報</h2>"
        f"<pre>command: sdk-ask.sh -p {html.escape(profile)} -w {html.escape(workspace)} -t 600 -j\n"
        f"instruction sha256: {digest}\ninstruction length: {len(instruction)}\n"
        f"audit log: {html.escape(AUDIT_LOG)}</pre>"
    )
    page("実行結果", body_html)


main()
