#!/usr/bin/env python3
"""本体コンテナのClaude Code・Codex CLIが、D1に積まれたジョブを1件ずつ取り出して片付ける。

仕様: cloudflare-workers-github-oauth-1 の SPEC.cloudflare-workers-github-oauth-1.20261107.bridge-job-queue.md 5章・12章。
- ジョブは依頼した側がD1(bridge_jobs・bridge_job_locks)に入れる。muse-vmのキューとSSHは使わない。Museは関わらない。
- 取り合いはD1の条件付きUPDATE 1文とclaim_tokenで決める。時刻はD1の時計(epoch秒)だけを使う。
- 期限内は lease_until > 今、期限切れは lease_until <= 今。ロックがあって結果が無く、期限が切れていれば取り直して再実行する。
- 外部へ書き込むジョブは max_attempts = 1 で登録し、期限切れは failed にして人が確かめる。
- 結果は bridge_job_results に claim_token ごとに保存し、上書きしない。状態の履歴はロックの表のトリガーが書く。
- 起動はまず手動で1件ずつ(run-once)。子プロセスにはトークンや秘密の値を渡さない。
- 変更件数は >= 1 で判定する。対象は主キー1行だけなので意味は同じで、D1のmeta.changesがトリガーで書いた行を含む場合も誤らない。

使い方:
  bridge_jobs.py register --origin aichat --created-by NAME [--external] [--job-id HEX32] < 依頼文
  bridge_jobs.py run-once --executor claude|codex [--worker NAME] [--cwd DIR]
  bridge_jobs.py list
  bridge_jobs.py cancel JOB_ID --reason 理由
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

SCHEMA_PATH = Path(__file__).with_name('bridge_jobs_schema.sql')
JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')
NOW = "CAST(strftime('%s','now') AS INTEGER)"
DEFAULT_DB_ID = 'ab65ff96-6333-4673-9ad4-4324be622184'  # D1 agent-inquiries
LEASE_SECONDS = 1800
HEARTBEAT_SECONDS = 300
TIMEOUT_SECONDS = 3 * 3600
RESULT_MAX_CHARS = 200_000
CHILD_ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'USER', 'LOGNAME', 'TERM', 'TMPDIR')
EXECUTORS = {
    'claude': ['claude', '-p', '--output-format', 'text'],
    'codex': ['codex', 'exec', '--skip-git-repo-check', '-'],
}


class D1Error(Exception):
    """D1が要求を拒んだ(SQLの誤りや制約違反)。"""


class D1Unknown(Exception):
    """要求を送ったが応答が返らなかった。D1が更新したかどうかは分からない。"""


class RestD1:
    """D1のREST API。query(sql, params) -> {'results': [...], 'changes': n}。"""

    def __init__(self, account_id, database_id, token, timeout=60):
        self.url = f'https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query'
        self.token = token
        self.timeout = timeout

    def query(self, sql, params=()):
        body = json.dumps({'sql': sql, 'params': list(params)}).encode()
        req = urllib.request.Request(self.url, body, {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                data = json.load(res)
        except urllib.error.HTTPError as err:
            raise D1Error(err.read().decode(errors='replace')[:500]) from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise D1Unknown(str(err)) from err
        if not data.get('success'):
            raise D1Error(json.dumps(data.get('errors'), ensure_ascii=False)[:500])
        result = data['result'][-1]
        return {'results': result.get('results') or [], 'changes': (result.get('meta') or {}).get('changes', 0)}


def _one(db, sql, params=()):
    rows = db.query(sql, params)['results']
    return rows[0] if rows else None


def register(db, job_id, request_text, *, origin, created_by, external_write=False, ai_chat_share_id=None):
    """依頼した側がジョブとロックの行を作る。同じjob_idで2回呼んでも上書きしない。作ったらTrue。"""
    if not JOB_ID_RE.match(job_id or ''):
        raise ValueError('job_idは32桁の小文字16進です')
    if not str(request_text or '').strip():
        raise ValueError('依頼文が空です')
    created = db.query(
        'INSERT OR IGNORE INTO bridge_jobs (job_id, origin, created_by, ai_chat_share_id, external_write, request_text) VALUES (?, ?, ?, ?, ?, ?)',
        [job_id, origin, created_by, ai_chat_share_id, 1 if external_write else 0, request_text])['changes'] >= 1
    db.query('INSERT OR IGNORE INTO bridge_job_locks (job_id, created_by, max_attempts) VALUES (?, ?, ?)',
             [job_id, created_by, 1 if external_write else 3])
    return created


def candidates(db, limit=10):
    rows = db.query(
        f"SELECT job_id FROM bridge_job_locks WHERE attempts < max_attempts AND result_path IS NULL "
        f"AND (status = 'queued' OR (status = 'claimed' AND lease_until <= {NOW})) ORDER BY created_at, job_id LIMIT ?",
        [limit])['results']
    return [r['job_id'] for r in rows]


def _token_is(db, job_id, token, status):
    row = _one(db, 'SELECT claim_token, status FROM bridge_job_locks WHERE job_id = ?', [job_id])
    return bool(row) and row['claim_token'] == token and row['status'] == status


def claim(db, job_id, token, worker, lease_seconds=LEASE_SECONDS):
    """条件付きUPDATE 1文で取る。応答が返らなければ、自分のclaim_tokenが入っているかで決める。"""
    sql = (f"UPDATE bridge_job_locks SET status = 'claimed', claim_token = ?1, claimed_by = ?2, claimed_at = {NOW}, "
           f"lease_until = {NOW} + ?3, attempts = attempts + 1, updated_at = {NOW} "
           f"WHERE job_id = ?4 AND attempts < max_attempts AND result_path IS NULL "
           f"AND (status = 'queued' OR (status = 'claimed' AND lease_until <= {NOW}))")
    try:
        return db.query(sql, [token, worker, lease_seconds, job_id])['changes'] >= 1
    except D1Unknown:
        return _token_is(db, job_id, token, 'claimed')


def extend(db, job_id, token, lease_seconds=LEASE_SECONDS):
    sql = (f"UPDATE bridge_job_locks SET lease_until = {NOW} + ?1, updated_at = {NOW} "
           f"WHERE job_id = ?2 AND claim_token = ?3 AND status = 'claimed' AND lease_until > {NOW}")
    try:
        return db.query(sql, [lease_seconds, job_id, token])['changes'] >= 1
    except D1Unknown:
        return False


def complete(db, job_id, token, result_text, exit_code):
    """結果をclaim_tokenごとに保存し、期限内で自分が持っているときだけ完了にする。"""
    text = str(result_text)[:RESULT_MAX_CHARS]
    digest = hashlib.sha256(text.encode()).hexdigest()
    saved = db.query(
        f"INSERT OR IGNORE INTO bridge_job_results (job_id, claim_token, result_text, result_sha256, exit_code) "
        f"SELECT ?1, ?2, ?3, ?4, ?5 WHERE EXISTS (SELECT 1 FROM bridge_job_locks WHERE job_id = ?1 AND claim_token = ?2 "
        f"AND status = 'claimed' AND lease_until > {NOW})",
        [job_id, token, text, digest, exit_code])['changes'] >= 1
    if not saved:
        return False
    path = f'bridge_job_results:{token}'
    sql = (f"UPDATE bridge_job_locks SET status = 'done', result_path = ?1, result_sha256 = ?2, updated_at = {NOW} "
           f"WHERE job_id = ?3 AND claim_token = ?4 AND status = 'claimed' AND lease_until > {NOW}")
    try:
        return db.query(sql, [path, digest, job_id, token])['changes'] >= 1
    except D1Unknown:
        return _token_is(db, job_id, token, 'done')


def release(db, job_id, token, error):
    """実行に失敗した。上限に達していればfailed、まだならqueuedに戻す(次に見たCLIが取り直す)。"""
    sql = (f"UPDATE bridge_job_locks SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END, "
           f"claim_token = NULL, lease_until = NULL, last_error = ?1, updated_at = {NOW} "
           f"WHERE job_id = ?2 AND claim_token = ?3 AND status = 'claimed' AND lease_until > {NOW}")
    return db.query(sql, [str(error)[:2000], job_id, token])['changes'] >= 1


def fail_exhausted(db):
    """期限が切れて上限に達したジョブをfailedにする。期限内や完了済みには触らない。"""
    rows = db.query(
        f"SELECT job_id FROM bridge_job_locks WHERE status = 'claimed' AND result_path IS NULL "
        f"AND attempts >= max_attempts AND lease_until <= {NOW}")['results']
    failed = []
    for row in rows:
        changes = db.query(
            f"UPDATE bridge_job_locks SET status = 'failed', last_error = ?1, updated_at = {NOW} "
            f"WHERE job_id = ?2 AND status = 'claimed' AND result_path IS NULL AND attempts >= max_attempts AND lease_until <= {NOW}",
            ['期限が切れ、試す回数の上限に達した。外部へ書き込むジョブは、人が外部の状態を確かめる', row['job_id']])['changes']
        if changes >= 1:
            failed.append(row['job_id'])
    return failed


def cancel(db, job_id, reason):
    sql = (f"UPDATE bridge_job_locks SET status = 'cancelled', last_error = ?1, updated_at = {NOW} "
           f"WHERE job_id = ?2 AND status IN ('queued', 'claimed')")
    return db.query(sql, [str(reason)[:2000], job_id])['changes'] >= 1


def child_env(environ):
    """子プロセス(Claude Code・Codex)に渡す環境変数。トークン・秘密の値・アカウントIDは渡さない。"""
    return {k: environ[k] for k in CHILD_ENV_KEYS if k in environ}


def run_command(args, prompt, *, extend, heartbeat_seconds=HEARTBEAT_SECONDS, timeout_seconds=TIMEOUT_SECONDS, cwd=None, env=None):
    """依頼文を標準入力で渡して実行する。heartbeatごとに期限を延ばし、延ばせなければ子を止める。

    戻り値は (終了コード, 標準出力, 標準エラー, 'finished' | 'lost' | 'timeout')。
    """
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        stdin.write(prompt.encode())
        stdin.seek(0)
        proc = subprocess.Popen(args, stdin=stdin, stdout=out, stderr=err, cwd=cwd, env=env, start_new_session=True)
        deadline = time.monotonic() + timeout_seconds
        state = 'finished'
        while True:
            try:
                proc.wait(timeout=heartbeat_seconds)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    state = 'timeout'
                elif not extend():
                    state = 'lost'
                else:
                    continue
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break
        out.seek(0)
        err.seek(0)
        return proc.returncode, out.read().decode(errors='replace'), err.read().decode(errors='replace'), state


def run_once(db, executor, *, worker, lease_seconds=LEASE_SECONDS):
    """取れるジョブのうち最も古い1件を取り、実行して結果を書く。executor(prompt, extend) -> (code, out, err, state)。"""
    fail_exhausted(db)
    for job_id in candidates(db):
        token = uuid.uuid4().hex
        if not claim(db, job_id, token, worker, lease_seconds):
            continue
        job = _one(db, 'SELECT request_text FROM bridge_jobs WHERE job_id = ?', [job_id])
        code, out, err, state = executor(job['request_text'], lambda: extend(db, job_id, token, lease_seconds))
        if state == 'lost':
            return {'job_id': job_id, 'status': 'lost', 'detail': '期限を延ばせなかったので止めた'}
        if state == 'finished' and code == 0:
            ok = complete(db, job_id, token, out, code)
            return {'job_id': job_id, 'status': 'done' if ok else 'not_completed'}
        reason = f'{state} / 終了コード{code}: {err.strip()[-500:]}'
        release(db, job_id, token, reason)
        return {'job_id': job_id, 'status': 'released', 'detail': reason}
    return {'status': 'idle'}


def _db_from_env():
    token = os.environ.get('CF_CONTAINER_API_TOKEN')
    account = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not account:
        sys.exit('CF_CONTAINER_API_TOKEN と CLOUDFLARE_ACCOUNT_ID が要ります')
    return RestD1(account, os.environ.get('LIB_BRIDGE_JOBS_D1_ID', DEFAULT_DB_ID), token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('register')
    p.add_argument('--origin', required=True)
    p.add_argument('--created-by', required=True)
    p.add_argument('--job-id', default=None)
    p.add_argument('--external', action='store_true', help='外部へ書き込むジョブ。試すのは1回だけ')
    p.add_argument('--ai-chat-share-id', default=None)
    p = sub.add_parser('run-once')
    p.add_argument('--executor', choices=sorted(EXECUTORS), required=True)
    p.add_argument('--worker', default=None)
    p.add_argument('--cwd', default=None)
    sub.add_parser('list')
    p = sub.add_parser('cancel')
    p.add_argument('job_id')
    p.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    db = _db_from_env()
    if args.command == 'register':
        job_id = args.job_id or uuid.uuid4().hex
        created = register(db, job_id, sys.stdin.read(), origin=args.origin, created_by=args.created_by,
                           external_write=args.external, ai_chat_share_id=args.ai_chat_share_id)
        print(json.dumps({'job_id': job_id, 'created': created}, ensure_ascii=False))
    elif args.command == 'run-once':
        worker = args.worker or f'{args.executor}@{os.uname().nodename}'
        cwd = args.cwd or tempfile.mkdtemp(prefix='bridge-job-')
        executor = lambda prompt, ext: run_command(EXECUTORS[args.executor], prompt, extend=ext, cwd=cwd, env=child_env(os.environ))
        print(json.dumps(run_once(db, executor, worker=worker), ensure_ascii=False))
    elif args.command == 'list':
        rows = db.query('SELECT l.job_id, l.status, l.attempts, l.max_attempts, l.claimed_by, l.lease_until, l.last_error, '
                        'substr(j.request_text, 1, 80) AS request FROM bridge_job_locks l JOIN bridge_jobs j ON j.job_id = l.job_id '
                        'ORDER BY l.created_at DESC LIMIT 50')['results']
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    elif args.command == 'cancel':
        print(json.dumps({'job_id': args.job_id, 'cancelled': cancel(db, args.job_id, args.reason)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
