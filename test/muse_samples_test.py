"""muse/samples のテスト。

receiver.py(muse-monitor が呼ぶ受信側のサンプル)の故障想定:
- 鍵が未設定でも通してしまう / 鍵の不一致や Bearer 以外を通す
- 未知の section や存在しないスクリプトで 500 になる、パスの細工でスクリプト以外を実行する
- 出力の上限・時間切れ・終了コードが契約(docs/RECEIVER.md)と違う
- /health が認証を求めて、muse-monitor が相手を見つけられない
- section の一覧が muse-monitor の許可リストから外れる、スクリプトが実在しない
bridge-jobs の見本の故障想定: 見本の形が実際のスクリプトと合わなくなる。
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).parents[1]
MUSE = ROOT / 'muse'
SAMPLES = MUSE / 'samples'
SH = shutil.which('dash') or 'sh'

spec = importlib.util.spec_from_file_location('muse_receiver', SAMPLES / 'receiver.py')
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)

# nekoserver/muse-monitor の src/do.ts の SECTIONS(受信側が受ける section の全体)
MONITOR_SECTIONS = {'status', 'diag', 'jobs', 'pkgs', 'vm', 'procs', 'ports', 'git', 'recent',
                    'pending', 'execlog', 'sdkhealth', 'sdkprofiles', 'sdksessions', 'sdkts'}


def alive(pid):
    """動いているか。終了済みで回収待ち(ゾンビ)は止まっているとみなす(コンテナのPID 1が回収しないことがある)。"""
    try:
        with open(f'/proc/{pid}/status', encoding='utf-8') as f:
            state = next((line for line in f if line.startswith('State:')), '')
    except FileNotFoundError:
        return False
    return 'Z' not in state.split(':', 1)[1].split()[0] if state else True


class ReceiverTest(unittest.TestCase):
    KEY = 'receiver-test-key'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        scripts = {
            'ok.sh': 'echo "hello"\necho "to stderr" >&2\n',
            'rc3.sh': 'echo "partial"\nexit 3\n',
            'big.sh': 'head -c 70000 /dev/zero | tr "\\0" "a"\n',
            'slow.sh': f'sleep 5 &\necho $! > {self.dir}/child.pid\nwait\n',
            'jp.sh': 'echo "日本語の出力"\n',
        }
        for name, body in scripts.items():
            (self.dir / name).write_text('#!/bin/sh\n' + body)
        sections = {'ok': 'ok.sh', 'rc3': 'rc3.sh', 'big': 'big.sh', 'slow': 'slow.sh', 'jp': 'jp.sh', 'missing': 'nothing.sh'}
        self.servers = []
        self.base = self.start(self.KEY, sections)

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def start(self, key, sections, timeout=1, limit=64 * 1024):
        server = receiver.ThreadingHTTPServer(('127.0.0.1', 0), receiver.make_handler(key, self.dir, sections, timeout, limit))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def get(self, path, key=KEY, base=None, header=None):
        headers = {} if key is None else {'Authorization': header or f'Bearer {key}'}
        try:
            with urlopen(Request((base or self.base) + path, headers=headers), timeout=10) as res:
                return res.status, json.loads(res.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_runs_the_section_script_and_returns_the_contract_fields(self):
        status, body = self.get('/monitor/ok')
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {'section', 'rc', 'output', 'truncated', 'ts'})
        self.assertEqual(body['section'], 'ok')
        self.assertEqual(body['rc'], 0)
        self.assertIn('hello', body['output'])
        self.assertIn('to stderr', body['output'])
        self.assertFalse(body['truncated'])
        self.assertRegex(body['ts'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$')

    def test_passes_the_exit_code_and_utf8_output_through(self):
        self.assertEqual(self.get('/monitor/rc3')[1]['rc'], 3)
        self.assertIn('日本語の出力', self.get('/monitor/jp')[1]['output'])

    def test_truncates_output_at_64_kib(self):
        status, body = self.get('/monitor/big')
        self.assertEqual(status, 200)
        self.assertTrue(body['truncated'])
        self.assertEqual(len(body['output']), 64 * 1024)

    def test_times_out_with_504_and_stops_child_processes_too(self):
        # 子プロセス(sleep)が出力をつかんだまま残ると、打ち切った後も終わるまで待たされる
        started = time.monotonic()
        status, body = self.get('/monitor/slow')
        self.assertEqual(status, 504)
        self.assertEqual(body['error'], 'timeout')
        self.assertLess(time.monotonic() - started, 3)
        pid = int((self.dir / 'child.pid').read_text())
        time.sleep(0.3)
        self.assertFalse(alive(pid), '時間切れの後も子プロセスが動いている')

    def test_rejects_missing_wrong_or_non_bearer_keys_with_401(self):
        for kwargs in ({'key': None}, {'key': 'wrong'}, {'key': self.KEY, 'header': f'Basic {self.KEY}'}, {'key': self.KEY, 'header': 'Bearer '}):
            status, body = self.get('/monitor/ok', **kwargs)
            self.assertEqual(status, 401, kwargs)
            self.assertEqual(body['error'], 'unauthorized')

    def test_answers_503_when_the_receiver_has_no_key(self):
        base = self.start('', {'ok': 'ok.sh'})
        status, body = self.get('/monitor/ok', base=base)
        self.assertEqual(status, 503)
        self.assertEqual(body['error'], 'receiver_key_not_configured')

    def test_unknown_missing_or_crafted_sections_are_404_and_run_nothing(self):
        for section in ('nope', 'missing', '../ok', 'ok/extra', '', 'OK'):
            status, body = self.get('/monitor/' + section)
            self.assertEqual(status, 404, section)
            self.assertEqual(body['error'], 'unknown_section')

    def test_health_needs_no_key_and_other_paths_are_404(self):
        self.assertEqual(self.get('/health', key=None), (200, {'status': 'ok'}))
        self.assertEqual(self.get('/other')[0], 404)
        req = Request(self.base + '/monitor/ok', method='POST', data=b'', headers={'Authorization': f'Bearer {self.KEY}'})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 405)


class ReceiverSectionsTest(unittest.TestCase):
    def test_sections_are_within_muse_monitor_and_point_to_existing_scripts(self):
        self.assertLessEqual(set(receiver.SECTIONS), MONITOR_SECTIONS)
        for section, script in receiver.SECTIONS.items():
            self.assertTrue((MUSE / script).is_file(), f'{section} -> {script}')

    def test_defaults_follow_the_contract(self):
        self.assertEqual(receiver.OUTPUT_LIMIT, 64 * 1024)
        self.assertEqual(receiver.TIMEOUT_SECONDS, 60)

    def test_listens_on_localhost_by_default(self):
        text = (SAMPLES / 'receiver.py').read_text(encoding='utf-8')
        self.assertIn("parser.add_argument('--host', default='127.0.0.1')", text)


class BridgeJobsSampleTest(unittest.TestCase):
    def run_script(self, name):
        return subprocess.run([SH, str(MUSE / name), str(SAMPLES / 'bridge-jobs')], capture_output=True, text=True, timeout=30)

    def test_bridge_jobs_lists_the_sample_queue_in_order(self):
        r = self.run_script('bridge-jobs.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), [
            'prio 5  20261111-0001  muse-monitorの状態を確認して、結果を報告する',
            'prio 1  20261111-0002  READMEの誤字を探す',
            'done: 1',
        ])

    def test_recent_jobs_shows_the_sample_report_heading(self):
        r = self.run_script('recent-jobs.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}  パッケージの版の一覧$')


if __name__ == '__main__':
    unittest.main()
