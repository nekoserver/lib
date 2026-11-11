"""claude/ops/bridge_jobs.py の claim トークンの照合。

故障想定:
- 通常の == で比べて、比較の時間からトークンを推し量られる(vuln-watch のパターン走査、2026-11-11)
- 置き換えのときに、トークンが無い行(NULL)や型の違いで例外になる、または一致と判定してしまう
"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge_jobs', ROOT / 'claude' / 'ops' / 'bridge_jobs.py')
bridge_jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_jobs)


class FakeDb:
    def __init__(self, row):
        self.row = row

    def query(self, sql, params=()):
        return {'results': [self.row] if self.row else []}


class TokenCompareTest(unittest.TestCase):
    def test_matches_only_the_same_token_and_status(self):
        db = FakeDb({'claim_token': 'tok-123', 'status': 'claimed'})
        self.assertTrue(bridge_jobs._token_is(db, 'j', 'tok-123', 'claimed'))
        self.assertFalse(bridge_jobs._token_is(db, 'j', 'tok-124', 'claimed'))
        self.assertFalse(bridge_jobs._token_is(db, 'j', 'tok-12', 'claimed'))
        self.assertFalse(bridge_jobs._token_is(db, 'j', 'tok-123', 'done'))

    def test_missing_row_null_token_or_empty_token_never_match(self):
        self.assertFalse(bridge_jobs._token_is(FakeDb(None), 'j', 'tok', 'claimed'))
        self.assertFalse(bridge_jobs._token_is(FakeDb({'claim_token': None, 'status': 'claimed'}), 'j', 'tok', 'claimed'))
        self.assertFalse(bridge_jobs._token_is(FakeDb({'claim_token': None, 'status': 'claimed'}), 'j', None, 'claimed'))
        self.assertFalse(bridge_jobs._token_is(FakeDb({'claim_token': '', 'status': 'claimed'}), 'j', '', 'claimed'))

    def test_uses_a_constant_time_comparison(self):
        source = (ROOT / 'claude' / 'ops' / 'bridge_jobs.py').read_text(encoding='utf-8')
        body = source.split('def _token_is', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('hmac.compare_digest', body)
        self.assertNotIn("['claim_token'] == token", body)


if __name__ == '__main__':
    unittest.main()
