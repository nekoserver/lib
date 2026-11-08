"""bridge_jobs.py のテスト。D1の代わりにSQLiteで、本番と同じSQL(bridge_jobs_schema.sql)を流す。

仕様: cloudflare-workers-github-oauth-1 の SPEC.cloudflare-workers-github-oauth-1.20261107.bridge-job-queue.md 5章・12章。
ユーザー指定(2026-11-08): ロックはD1に置き、依頼した側が行を作る。Museは関わらない。ロックがあって結果が無く、
期限が切れていれば再実行する。外部へ書き込むジョブは自動で再実行しない。起動はまず手動で1件ずつ。
"""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import time
import unittest

spec = importlib.util.spec_from_file_location('bridge_jobs', Path(__file__).parents[1] / 'ops/bridge_jobs.py')
bj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bj)

JOB = 'a' * 32
JOB2 = 'b' * 32


class SqliteD1:
    """D1のREST APIの代わり。query(sql, params) -> {'results': [...], 'changes': n}。"""

    def __init__(self):
        self.conn = sqlite3.connect(':memory:', isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.conn.executescript(bj.SCHEMA_PATH.read_text(encoding='utf-8'))
        self.fail_next_after_execute = False

    def query(self, sql, params=()):
        cur = self.conn.execute(sql, list(params))
        rows = [dict(r) for r in cur.fetchall()]
        result = {'results': rows, 'changes': cur.rowcount if cur.rowcount >= 0 else 0}
        if self.fail_next_after_execute:
            self.fail_next_after_execute = False
            raise bj.D1Unknown('応答が返らなかった')
        return result

    def now(self):
        return self.conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER) AS t").fetchone()['t']

    def lock(self, job_id=JOB):
        return dict(self.conn.execute('SELECT * FROM bridge_job_locks WHERE job_id = ?', [job_id]).fetchone())

    def events(self, job_id=JOB):
        return [r['kind'] for r in self.conn.execute('SELECT kind FROM bridge_job_events WHERE job_id = ? ORDER BY id', [job_id])]


def registered(db, job_id=JOB, external=False):
    bj.register(db, job_id, '調べて', origin='aichat', created_by='okiraku', external_write=external)
    return db


class RegisterTest(unittest.TestCase):
    def test_register_creates_job_and_lock_once(self):
        db = SqliteD1()
        self.assertTrue(bj.register(db, JOB, '調べて', origin='aichat', created_by='okiraku'))
        self.assertFalse(bj.register(db, JOB, '別の本文', origin='aichat', created_by='other'))
        lock = db.lock()
        self.assertEqual((lock['status'], lock['attempts'], lock['max_attempts'], lock['created_by']), ('queued', 0, 3, 'okiraku'))
        self.assertEqual(db.conn.execute('SELECT request_text FROM bridge_jobs').fetchone()[0], '調べて')
        self.assertEqual(db.events(), ['queued'])

    def test_external_write_jobs_are_tried_only_once(self):
        db = registered(SqliteD1(), external=True)
        self.assertEqual(db.lock()['max_attempts'], 1)

    def test_rejects_malformed_job_ids_and_empty_requests(self):
        db = SqliteD1()
        for job_id in ('x' * 31, 'g' * 32, "a' OR 1=1 --" + 'a' * 20):
            with self.assertRaises(ValueError):
                bj.register(db, job_id, '調べて', origin='aichat', created_by='u')
        with self.assertRaises(ValueError):
            bj.register(db, JOB, '   ', origin='aichat', created_by='u')


class ClaimTest(unittest.TestCase):
    def test_only_one_of_two_workers_wins(self):
        db = registered(SqliteD1())
        self.assertTrue(bj.claim(db, JOB, 't1', 'claude-code@a', 1800))
        self.assertFalse(bj.claim(db, JOB, 't2', 'codex@b', 1800))
        lock = db.lock()
        self.assertEqual((lock['claim_token'], lock['claimed_by'], lock['attempts']), ('t1', 'claude-code@a', 1))
        self.assertEqual(db.events(), ['queued', 'claimed'])

    def test_lease_boundary_is_shared_by_claim_extend_and_complete(self):
        db = registered(SqliteD1())
        bj.claim(db, JOB, 't1', 'w1', 1800)
        db.conn.execute('UPDATE bridge_job_locks SET lease_until = ? WHERE job_id = ?', [db.now(), JOB])
        # 期限ちょうどは期限切れ: 延長と完了は拒み、取り直しは通す
        self.assertFalse(bj.extend(db, JOB, 't1', 1800))
        self.assertFalse(bj.complete(db, JOB, 't1', '結果', 0))
        self.assertTrue(bj.claim(db, JOB, 't2', 'w2', 1800))
        self.assertEqual(db.lock()['attempts'], 2)

    def test_old_token_cannot_extend_or_complete_after_reclaim(self):
        db = registered(SqliteD1())
        bj.claim(db, JOB, 't1', 'w1', 1800)
        db.conn.execute('UPDATE bridge_job_locks SET lease_until = ? WHERE job_id = ?', [db.now() - 1, JOB])
        self.assertTrue(bj.claim(db, JOB, 't2', 'w2', 1800))
        self.assertFalse(bj.extend(db, JOB, 't1', 1800))
        self.assertFalse(bj.complete(db, JOB, 't1', '古い結果', 0))
        self.assertTrue(bj.complete(db, JOB, 't2', '新しい結果', 0))
        lock = db.lock()
        self.assertEqual(lock['status'], 'done')
        # 古い実行者の結果は残らない(完了にできなかったので保存もしない)、新しい結果はトークン別に残る
        rows = db.conn.execute('SELECT claim_token, result_text FROM bridge_job_results ORDER BY claim_token').fetchall()
        self.assertEqual([tuple(r) for r in rows], [('t2', '新しい結果')])

    def test_lost_claim_response_is_resolved_by_reading_the_token(self):
        db = registered(SqliteD1())
        db.fail_next_after_execute = True
        self.assertTrue(bj.claim(db, JOB, 't1', 'w1', 1800))
        db2 = registered(SqliteD1())
        db2.fail_next_after_execute = True
        db2.conn.execute("UPDATE bridge_job_locks SET status = 'cancelled' WHERE job_id = ?", [JOB])
        self.assertFalse(bj.claim(db2, JOB, 't1', 'w1', 1800))

    def test_done_jobs_are_never_reclaimed(self):
        db = registered(SqliteD1())
        bj.claim(db, JOB, 't1', 'w1', 1800)
        self.assertTrue(bj.complete(db, JOB, 't1', '結果', 0))
        db.conn.execute('UPDATE bridge_job_locks SET lease_until = 0 WHERE job_id = ?', [JOB])
        self.assertFalse(bj.claim(db, JOB, 't2', 'w2', 1800))
        self.assertEqual(bj.candidates(db, 10), [])


    def test_a_claimed_job_that_already_has_a_result_is_not_reclaimed(self):
        db = registered(SqliteD1())
        bj.claim(db, JOB, 't1', 'w1', 1800)
        db.conn.execute("UPDATE bridge_job_locks SET result_path = 'bridge_job_results:t1', lease_until = ? WHERE job_id = ?", [db.now() - 1, JOB])
        self.assertEqual(bj.candidates(db, 10), [])
        self.assertFalse(bj.claim(db, JOB, 't2', 'w2', 1800))


class FailureTest(unittest.TestCase):
    def test_release_requeues_until_the_attempt_limit_then_fails(self):
        db = registered(SqliteD1())
        for n, expected in ((1, 'queued'), (2, 'queued'), (3, 'failed')):
            self.assertTrue(bj.claim(db, JOB, f't{n}', 'w', 1800))
            self.assertTrue(bj.release(db, JOB, f't{n}', f'終了コード1 ({n}回目)'))
            self.assertEqual(db.lock()['status'], expected)
        self.assertEqual(db.events(), ['queued', 'claimed', 'released', 'claimed', 'released', 'claimed', 'failed'])
        self.assertIn('3回目', db.lock()['last_error'])

    def test_expired_jobs_at_the_limit_are_failed_only_by_a_conditional_update(self):
        db = registered(SqliteD1(), external=True)
        bj.claim(db, JOB, 't1', 'w', 1800)
        self.assertEqual(bj.fail_exhausted(db), [])  # 期限内は触らない
        db.conn.execute('UPDATE bridge_job_locks SET lease_until = ? WHERE job_id = ?', [db.now() - 1, JOB])
        self.assertEqual(bj.fail_exhausted(db), [JOB])
        self.assertEqual(db.lock()['status'], 'failed')
        self.assertIn('人が外部の状態を確かめる', db.lock()['last_error'])

    def test_cancel_stops_queued_and_claimed_jobs(self):
        db = registered(SqliteD1())
        bj.claim(db, JOB, 't1', 'w', 1800)
        self.assertTrue(bj.cancel(db, JOB, '利用者が中止'))
        self.assertFalse(bj.extend(db, JOB, 't1', 1800))
        self.assertEqual(db.events()[-1], 'cancelled')


class ExecutorTest(unittest.TestCase):
    def test_child_environment_drops_tokens_and_secrets(self):
        env = bj.child_env({'PATH': '/bin', 'HOME': '/root', 'LANG': 'C.UTF-8', 'CF_CONTAINER_API_TOKEN': 'x',
                            'ORIGIN_HMAC_SECRET': 'y', 'MUSE_API_KEY': 'z', 'GH_TOKEN': 'w', 'CLOUDFLARE_ACCOUNT_ID': 'v'})
        self.assertEqual(env, {'PATH': '/bin', 'HOME': '/root', 'LANG': 'C.UTF-8'})

    def test_lost_lease_stops_the_child(self):
        calls = []
        started = time.monotonic()
        code, out, err, state = bj.run_command([sys.executable, '-c', 'import time; time.sleep(30)'], '',
                                               extend=lambda: calls.append(1) or False, heartbeat_seconds=0.2, timeout_seconds=20)
        self.assertEqual(state, 'lost')
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(len(calls), 1)

    def test_prompt_is_passed_on_stdin_and_output_is_captured(self):
        code, out, err, state = bj.run_command([sys.executable, '-c', 'import sys; print(sys.stdin.read().upper())'], 'abc',
                                               extend=lambda: True, heartbeat_seconds=5, timeout_seconds=20)
        self.assertEqual((code, out.strip(), state), (0, 'ABC', 'finished'))


class RunOnceTest(unittest.TestCase):
    def test_runs_the_oldest_claimable_job_and_records_the_result(self):
        db = registered(registered(SqliteD1(), JOB), JOB2)
        seen = []

        def executor(prompt, extend):
            seen.append(prompt)
            return 0, '答え', '', 'finished'

        outcome = bj.run_once(db, executor, worker='claude-code@test', lease_seconds=1800)
        self.assertEqual((outcome['job_id'], outcome['status']), (JOB, 'done'))
        self.assertEqual(seen, ['調べて'])
        self.assertEqual(db.lock(JOB)['status'], 'done')
        self.assertEqual(db.lock(JOB2)['status'], 'queued')
        self.assertEqual(db.events(JOB), ['queued', 'claimed', 'completed'])

    def test_failed_execution_releases_and_nothing_to_do_returns_idle(self):
        db = registered(SqliteD1())
        outcome = bj.run_once(db, lambda p, e: (2, '', 'エラー', 'finished'), worker='w', lease_seconds=1800)
        self.assertEqual(outcome['status'], 'released')
        self.assertIn('終了コード2', db.lock()['last_error'])
        db.conn.execute("UPDATE bridge_job_locks SET status = 'cancelled'")
        self.assertEqual(bj.run_once(db, lambda p, e: (0, '', '', 'finished'), worker='w', lease_seconds=1800)['status'], 'idle')


if __name__ == '__main__':
    unittest.main()
