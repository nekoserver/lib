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
import sys
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
        # 鍵が無い(load_key が None を返す)間は、gated な経路を通さず 503 にする。
        # 起動自体は拒否しないのが正(2026-11-18 に稼働中実装へ統一。NOTICE.lib.20261118.receiver-gate 参照)
        base = self.start(None, {'ok': 'ok.sh'})
        status, body = self.get('/monitor/ok', base=base)
        self.assertEqual(status, 503)
        self.assertEqual(body['error'], 'receiver_key_missing')

    def test_unknown_missing_or_crafted_sections_are_404_and_run_nothing(self):
        for section in ('nope', 'missing', '../ok', 'ok/extra', '', 'OK'):
            status, body = self.get('/monitor/' + section)
            self.assertEqual(status, 404, section)
            self.assertEqual(body['error'], 'unknown_section')

    def test_health_answers_ok_only_without_any_key_material(self):
        # /health は鍵なしで引ける代わりに、鍵の指紋も値も一切出さない(稼働中実装の形)
        status, body = self.get('/health', key=None)
        self.assertEqual(status, 200)
        self.assertEqual(body, {'status': 'ok'})
        self.assertNotIn(self.KEY, json.dumps(body))

    def test_401_is_bare_unauthorized_without_fingerprints(self):
        # 不一致の 401 は {'error': 'unauthorized'} だけ。どちらの鍵が違うかは応答からは
        # 分からない(切り分けは NOTICE に記録した設定時の指紋で行う)
        status, body = self.get('/monitor/ok', key='wrong')
        self.assertEqual(status, 401)
        self.assertEqual(body, {'error': 'unauthorized'})
        self.assertNotIn(self.KEY, json.dumps(body))

    def test_a_bearer_with_surrounding_spaces_is_rejected(self):
        # 照合は完全一致のみ。前後の空白や Bearer の後の余分な空白は通さない
        self.assertEqual(self.get('/monitor/ok', key=self.KEY, header=f'Bearer  {self.KEY} ')[0], 401)

    def test_health_needs_no_key_and_other_paths_are_404(self):
        self.assertEqual(self.get('/health', key=None)[0], 200)
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

    def test_listens_on_every_address_by_default_so_muse_monitor_can_reach_it(self):
        # 127.0.0.1 だと tailnet 経由の muse-monitor からは接続拒否になる(2026-11-11 に起きた)。鍵の照合があるので全アドレスで待ち受ける
        text = (SAMPLES / 'receiver.py').read_text(encoding='utf-8')
        self.assertIn("parser.add_argument('--host', default='0.0.0.0')", text)

    def test_starts_without_the_key_file_with_gated_paths_unavailable_and_ignores_the_shell_env(self):
        # 鍵ファイルが無くても起動はする(gated な経路が 503 になるだけ)。鍵は
        # ~/.config/muse-receiver.env だけから読み、シェルの TS_API_KEY は使わない
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, TS_API_KEY='stray-value-in-shell')
            proc = subprocess.Popen([sys.executable, str(SAMPLES / 'receiver.py'), '--host', '127.0.0.1', '--port', '0'],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
            timer = threading.Timer(5, proc.kill)  # 待ち受けの行が出ないまま止まらないように
            timer.start()
            lines = []
            try:
                for line in proc.stdout:
                    lines.append(line)
                    if line.startswith('listening'):
                        break
            finally:
                timer.cancel()
                proc.kill()
                proc.communicate()
        out = ''.join(lines)
        self.assertIn('listening', out)
        self.assertIn('auth: unavailable', out)
        self.assertNotIn('stray-value-in-shell', out)

    def test_starts_with_the_key_file_and_prints_auth_on_not_the_key(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / '.config').mkdir()
            key_file = Path(home) / '.config' / 'muse-receiver.env'
            key_file.write_text('TS_API_KEY=<redacted>\n')
            env = dict(os.environ, HOME=home, TS_API_KEY='stray-value-in-shell')
            proc = subprocess.Popen([sys.executable, str(SAMPLES / 'receiver.py'), '--host', '127.0.0.1', '--port', '0'],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
            timer = threading.Timer(5, proc.kill)  # 待ち受けの行が出ないまま止まらないように
            timer.start()
            lines = []
            try:
                for line in proc.stdout:
                    lines.append(line)
                    if line.startswith('listening'):
                        break
            finally:
                timer.cancel()
                proc.kill()
                proc.communicate()
        out = ''.join(lines)
        self.assertIn('listening', out)
        self.assertIn('auth: on', out)
        self.assertNotIn('file-key', out)
        self.assertNotIn('stray-value-in-shell', out)

    def test_load_key_reads_the_last_assignment_and_strips_whitespace_only(self):
        # 行頭が TS_API_KEY= の行だけが対象で、最後の代入が勝つ。空白(CRLF 含む)は
        # 落とすが、引用符や export は解釈しない(付いていれば値の一部になる)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'k.env'
            cases = {
                'TS_API_KEY=abc\n': 'abc',
                'TS_API_KEY="abc"\r\n': '"abc"',
                "TS_API_KEY='abc'  \n": "'abc'",
                'export TS_API_KEY=abc\n': None,
                '# comment\nTS_API_KEY=old\nTS_API_KEY=new\n': 'new',
                'TS_API_KEY=\n': None,
                'OTHER=abc\n': None,
            }
            for text, want in cases.items():
                path.write_text(text)
                self.assertEqual(receiver.load_key(path), want, repr(text))
            self.assertIsNone(receiver.load_key(Path(d) / 'missing.env'))


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




class ReceiverConcurrencyTest(unittest.TestCase):
    """同時実行の上限・同じ項目のまとめ・結果の使い回し・設定による項目の追加。"""
    KEY = 'k'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / 'runs.log'
        # 実行のたびに開始と終了を1行ずつ記録し、0.4秒かかるスクリプト
        for name in ('a', 'b', 'c', 'd', 'e', 'f'):
            (self.dir / f'{name}.sh').write_text(f'#!/bin/sh\necho "start {name}" >> {self.log}\nsleep 0.4\necho "end {name}" >> {self.log}\necho "out {name}"\n')
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def start(self, **options):
        # 古い結果の即答は、それを確かめるテストだけで有効にする(他のテストは毎回の実行を数えるため)
        options.setdefault('stale_seconds', 0)
        sections = {n: f'{n}.sh' for n in ('a', 'b', 'c', 'd', 'e', 'f')}
        handler = receiver.make_handler(self.KEY, self.dir, sections, **options)
        self.handler = handler
        server = receiver.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def get(self, base, section):
        try:
            with urlopen(Request(f'{base}/monitor/{section}', headers={'Authorization': f'Bearer {self.KEY}'}), timeout=20) as res:
                return res.status, json.loads(res.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def parallel(self, base, sections):
        results = [None] * len(sections)
        def work(i, s):
            results[i] = self.get(base, s)
        threads = [threading.Thread(target=work, args=(i, s)) for i, s in enumerate(sections)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def max_running(self):
        running = peak = 0
        for line in self.log.read_text().splitlines():
            running += 1 if line.startswith('start') else -1
            peak = max(peak, running)
        return peak

    def test_limits_how_many_scripts_run_at_once(self):
        base = self.start(timeout=5, max_concurrent=2, cache_seconds=0)
        results = self.parallel(base, ['a', 'b', 'c', 'd', 'e', 'f'])
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertLessEqual(self.max_running(), 2)
        self.assertEqual(self.log.read_text().count('start'), 6)

    def test_answers_busy_when_no_slot_frees_up_in_time(self):
        base = self.start(timeout=5, max_concurrent=1, cache_seconds=0, queue_wait=0.1)
        results = self.parallel(base, ['a', 'b'])
        statuses = sorted(status for status, _ in results)
        self.assertEqual(statuses, [200, 503])
        busy = next(body for status, body in results if status == 503)
        self.assertEqual(busy['error'], 'busy')

    def test_waiting_requests_run_in_arrival_order(self):
        base = self.start(timeout=5, max_concurrent=1, cache_seconds=0)
        order = ['a', 'b', 'c', 'd']
        threads = []
        for section in order:
            t = threading.Thread(target=self.get, args=(base, section))
            t.start()
            threads.append(t)
            time.sleep(0.05)
        for t in threads:
            t.join()
        starts = [line.split()[1] for line in self.log.read_text().splitlines() if line.startswith('start')]
        self.assertEqual(starts, order)

    def test_refuses_at_once_when_the_queue_is_full(self):
        base = self.start(timeout=5, max_concurrent=1, max_queue=1, cache_seconds=0)
        started = time.monotonic()
        results = self.parallel(base, ['a', 'b', 'c'])
        statuses = sorted(status for status, _ in results)
        self.assertEqual(statuses, [200, 200, 503])
        full = next(body for status, body in results if status == 503)
        self.assertEqual(full['error'], 'queue_full')
        self.assertEqual(self.log.read_text().count('start'), 2)
        self.assertLess(time.monotonic() - started, 3)

    def test_queue_endpoint_shows_running_and_waiting_and_needs_the_key(self):
        base = self.start(timeout=5, max_concurrent=1, cache_seconds=0)
        threads = [threading.Thread(target=self.get, args=(base, s)) for s in ('a', 'b')]
        for t in threads:
            t.start()
        time.sleep(0.15)
        with urlopen(Request(f'{base}/queue', headers={'Authorization': f'Bearer {self.KEY}'}), timeout=5) as res:
            snapshot = json.loads(res.read())
        for t in threads:
            t.join()
        self.assertEqual(snapshot['running'], 1)
        self.assertEqual(snapshot['waiting'], 1)
        self.assertEqual(snapshot['maxConcurrent'], 1)
        self.assertEqual(len(snapshot['runningSections']), 1)
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f'{base}/queue', timeout=5)
        self.assertEqual(ctx.exception.code, 401)

    def test_concurrent_requests_for_the_same_section_share_one_run(self):
        base = self.start(timeout=5, max_concurrent=4, cache_seconds=0)
        results = self.parallel(base, ['a'] * 5)
        self.assertTrue(all(status == 200 and body['output'] == 'out a\n' for status, body in results), results)
        self.assertEqual(self.log.read_text().count('start a'), 1)

    def test_reuses_a_finished_result_for_a_short_time_only(self):
        base = self.start(timeout=5, cache_seconds=1)
        first = self.get(base, 'a')[1]
        second = self.get(base, 'a')[1]
        self.assertEqual(first['ts'], second['ts'])
        self.assertEqual(self.log.read_text().count('start a'), 1)
        time.sleep(1.2)
        self.get(base, 'a')
        self.assertEqual(self.log.read_text().count('start a'), 2)


    def timed_get(self, base, section):
        started = time.monotonic()
        result = self.get(base, section)
        return time.monotonic() - started, result

    def wait_for_starts(self, section, count, limit=3):
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if self.log.read_text().count(f'start {section}') >= count and self.log.read_text().count(f'end {section}') >= count:
                return
            time.sleep(0.05)
        self.fail(f'{section} did not run {count} times')

    def test_answers_a_stale_result_at_once_and_refreshes_it_in_the_background(self):
        base = self.start(timeout=5, cache_seconds=0.2, stale_seconds=10)
        self.get(base, 'a')
        time.sleep(0.3)
        elapsed, (status, body) = self.timed_get(base, 'a')
        self.assertEqual(status, 200)
        self.assertEqual(body['output'], 'out a\n')
        self.assertLess(elapsed, 0.2, 'the stale result should come back without waiting for the 0.4s script')
        self.wait_for_starts('a', 2)
        time.sleep(0.1)
        # 取り直しは1回だけ(続けて来た要求で重ねて走らせない)
        for _ in range(3):
            self.get(base, 'a')
        time.sleep(0.6)
        self.assertLessEqual(self.log.read_text().count('start a'), 3)

    def test_runs_the_script_again_when_the_result_is_older_than_stale_seconds(self):
        base = self.start(timeout=5, cache_seconds=0.1, stale_seconds=0.3)
        self.get(base, 'a')
        time.sleep(0.5)
        elapsed, (status, _) = self.timed_get(base, 'a')
        self.assertEqual(status, 200)
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertEqual(self.log.read_text().count('start a'), 2)

    def test_does_not_answer_a_failed_run_as_a_stale_result(self):
        (self.dir / 'a.sh').write_text('#!/bin/sh\nsleep 2\n')
        base = self.start(timeout=0.3, cache_seconds=0.1, stale_seconds=10)
        self.assertEqual(self.get(base, 'a')[0], 504)
        time.sleep(0.2)
        self.assertEqual(self.get(base, 'a')[0], 504)

    def test_warm_runs_every_section_once_so_first_requests_answer_at_once(self):
        base = self.start(timeout=5, max_concurrent=6, cache_seconds=10)
        started = time.monotonic()
        self.handler.runner.warm(self.handler.sections, self.dir)
        self.assertLess(time.monotonic() - started, 1.5, 'warm should run the sections side by side')
        self.assertEqual(self.log.read_text().count('start'), 6)
        elapsed, (status, _) = self.timed_get(base, 'f')
        self.assertEqual(status, 200)
        self.assertLess(elapsed, 0.2)
        self.assertEqual(self.log.read_text().count('start'), 6)

    def test_by_default_every_default_section_can_run_at_once(self):
        self.assertGreaterEqual(receiver.MAX_CONCURRENT, len(receiver.SECTIONS))
        self.assertGreater(receiver.STALE_SECONDS, receiver.CACHE_SECONDS)


class ReceiverSectionsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        path = self.dir / 'sections.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_adds_sections_from_a_json_file_on_top_of_the_defaults(self):
        sections = receiver.load_sections(self.write({'diag': 'diag.sh', 'status': 'muse-status.sh'}))
        self.assertEqual(sections['diag'], 'diag.sh')
        self.assertEqual(sections['jobs'], 'bridge-jobs.sh')

    def test_rejects_paths_and_bad_names(self):
        for bad in ({'x': '../x.sh'}, {'x': 'sub/x.sh'}, {'x': '/bin/sh'}, {'x': ''}, {'bad name': 'x.sh'}, {'x': 1}, ['x']):
            with self.assertRaises(ValueError, msg=bad):
                receiver.load_sections(self.write(bad))

    def test_without_a_file_uses_the_defaults(self):
        self.assertEqual(receiver.load_sections(None), receiver.SECTIONS)


class ReceiverBestStateTest(unittest.TestCase):
    """muse-vm の受信側の最善の状態(SPEC.scripts.md 4.0)を、receiver-check.sh が見分けられるか。

    受信側は本物を起動する。ss だけは、このコンテナに無いので、待ち受けの表示を偽物で返す。
    """
    KEY = 'best-state-key'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        (self.home / '.config').mkdir(parents=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def start_receiver(self, host='127.0.0.1', key=KEY):
        server = receiver.ThreadingHTTPServer((host, 0), receiver.make_handler(key, self.root, {}))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return server.server_address[1]

    def write_env(self, key=KEY, mode=0o600):
        path = self.home / '.config' / 'muse-receiver.env'
        path.write_text(f'TS_API_KEY={key}\n')
        path.chmod(mode)

    def fake_ss(self, *listen):
        lines = ['State Recv-Q Send-Q Local Address:Port Peer Address:Port'] + [f'LISTEN 0 128 {a} 0.0.0.0:*' for a in listen]
        body = ''.join(f"echo '{line}'\n" for line in lines)
        (self.bin / 'ss').write_text('#!/bin/sh\n' + body)
        (self.bin / 'ss').chmod(0o755)

    def check(self, port):
        env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.home), 'LANG': 'C.UTF-8'}
        return subprocess.run([SH, str(SAMPLES / 'receiver-check.sh'), str(port)], capture_output=True, text=True, env=env, timeout=30)

    def ng_lines(self, r):
        return [line for line in r.stdout.splitlines() if line.startswith('NG')]

    def test_all_ok_when_listening_on_every_address_with_the_matching_key(self):
        port = self.start_receiver()
        self.write_env()
        self.fake_ss(f'0.0.0.0:{port}')
        r = self.check(port)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ng_lines(r), [])
        self.assertGreaterEqual(r.stdout.count('OK'), 4)
        self.assertNotIn(self.KEY, r.stdout + r.stderr)

    def test_ng_when_listening_only_on_localhost(self):
        port = self.start_receiver()
        self.write_env()
        self.fake_ss(f'127.0.0.1:{port}')
        r = self.check(port)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any('127.0.0.1' in line for line in self.ng_lines(r)), r.stdout)

    def test_ng_when_nothing_listens(self):
        self.write_env()
        self.fake_ss()
        r = self.check(1)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any('待ち受けていない' in line for line in self.ng_lines(r)), r.stdout)

    def test_ng_when_the_key_file_differs_from_the_receiver(self):
        port = self.start_receiver(key='other-key')
        self.write_env()
        self.fake_ss(f'0.0.0.0:{port}')
        r = self.check(port)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any('401' in line for line in self.ng_lines(r)), r.stdout)

    def test_ng_when_the_key_file_is_missing_or_readable_by_others(self):
        port = self.start_receiver()
        self.fake_ss(f'0.0.0.0:{port}')
        r = self.check(port)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any('muse-receiver.env' in line for line in self.ng_lines(r)), r.stdout)
        self.write_env(mode=0o644)
        r = self.check(port)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any('600' in line for line in self.ng_lines(r)), r.stdout)

    def test_check_script_is_read_only_posix_sh_and_keeps_the_key_out_of_argv(self):
        text = (SAMPLES / 'receiver-check.sh').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('#!/bin/sh\n'))
        self.assertIn('\nset -u\n', text)
        self.assertNotRegex(text, r'(^|[\s;|&(])(rm|kill|systemctl (start|stop|restart)|tailscale)\b')
        self.assertNotIn('Authorization: Bearer $key" ', text)
        self.assertIn('-K -', text)

    def test_service_unit_keeps_the_receiver_running_in_the_best_state(self):
        unit = (SAMPLES / 'muse-receiver.service').read_text(encoding='utf-8')
        self.assertIn('Restart=always', unit)
        self.assertNotIn('EnvironmentFile', unit)  # 鍵は receiver.py が ~/.config/muse-receiver.env から直接読む
        self.assertIn('muse/samples/receiver.py', unit)
        self.assertNotIn('127.0.0.1', unit)
        self.assertNotIn('TS_API_KEY=', unit)

    def test_spec_and_rules_state_the_same_best_state(self):
        spec = (MUSE / 'SPEC.scripts.md').read_text(encoding='utf-8')
        rules = (ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
        for text in (spec, rules):
            for needle in ('receiver-check.sh', 'muse-receiver.service', 'muse-receiver.env', '0.0.0.0'):
                self.assertIn(needle, text)


if __name__ == '__main__':
    unittest.main()
