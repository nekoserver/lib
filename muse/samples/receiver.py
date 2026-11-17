#!/usr/bin/env python3
"""receiver.py - muse-monitor が呼ぶ受信側(/monitor/<section>)のサンプル。

契約は nekoserver/muse-monitor の docs/RECEIVER.md:
- GET /monitor/<section> と GET /queue は Authorization: Bearer <TS_API_KEY> を照合する
  （SPEC.muse-monitor.security.hardening REQ-SEC-001/002/004/020。2026-11-12 の照合無し指示は
  2026-11-16 のセキュリティ強化指示で置き換えられた）
- 鍵は ~/.config/muse-receiver.env の TS_API_KEY から読む。読めなければ gated な経路は 503
- 未知の section は 404
- 応答は {"section", "rc", "output", "truncated", "ts"}。output は 64 KiB で切り詰め、60 秒で 504
- GET /health は認証なしで {"status": "ok"}(muse-monitor が相手を探すときに叩く)

このサンプルは lib/muse のスクリプトがある section だけを扱う(読み取り専用)。
diag・pending・execlog・sdk* はスクリプトが無いので 404 を返す。

muse-vm に負荷をかけないための制御(契約の外。応答の形は変えない):
- 同時に実行するスクリプトは max_concurrent 本まで(既定8。既定の項目をすべて同時に走らせられる数)。超えた分は到着順の待ち行列に並ぶ
- 待ち行列は max_queue 件まで(既定32)。あふれたら待たせずに 503 queue_full
- queue_wait 秒(既定30)待っても順番が来なければ 503 busy
- 同じ section への同時の要求は1回の実行にまとめ、同じ結果を返す。成功した結果は cache_seconds 秒(既定5)使い回す
待ち時間を減らすための工夫:
- cache_seconds を過ぎても stale_seconds 秒(既定300)以内の成功結果は、待たせずにすぐ返し、裏で1回だけ取り直す
  (応答の ts は結果を作った時刻なので、古さは ts で分かる)
- 起動直後に全項目を1回ずつ実行して結果を用意する(最初の要求から待たせない)
- GET /queue で、実行中・待ち・実行中の section を返す

項目の追加: --sections に JSON({"section": "スクリプト名"})を渡すと既定に足す。スクリプトは
このディレクトリの親(lib/muse)の直下のファイル名に限る。

使い方: python3 receiver.py [--host 0.0.0.0] [--port 8090] [--sections FILE]
        [--max-concurrent 8] [--max-queue 32]
既定で全アドレス(0.0.0.0)に待ち受ける。127.0.0.1 では tailnet 経由の muse-monitor から接続拒否になる。
絞るときは --host に tailnet のアドレスを指定する。
"""
import argparse
from collections import deque
from datetime import datetime
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import threading
import time

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
SECTIONS = {
    'status': 'muse-status.sh',
    'jobs': 'bridge-jobs.sh',
    'pkgs': 'pkg-versions.sh',
    'vm': 'vm-info.sh',
    'procs': 'procs.sh',
    'ports': 'ports.sh',
    'git': 'git-heads.sh',
    'recent': 'recent-jobs.sh',
}
OUTPUT_LIMIT = 64 * 1024
TIMEOUT_SECONDS = 60
MAX_CONCURRENT = 8
MAX_QUEUE = 32
QUEUE_WAIT_SECONDS = 30
CACHE_SECONDS = 5
STALE_SECONDS = 300
SECTION_NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
SCRIPT_NAME = re.compile(r'^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$')


def load_key(env_file):
    """受信側の鍵(TS_API_KEY)を env ファイルから読む。最後の TS_API_KEY 行が勝つ
    (receiver-check.sh の読み方に合わせる)。読めない・無い・空なら None。
    None の間は gated な経路を 503 にする(REQ-SEC-002/020: 鍵なしで通さない)。"""
    try:
        value = None
        with open(env_file, encoding='utf-8') as f:
            for line in f:
                if line.startswith('TS_API_KEY='):
                    value = line[len('TS_API_KEY='):].strip()
        return value or None
    except OSError:
        return None


def load_sections(path):
    """既定の SECTIONS に、JSON ファイルの {"section": "スクリプト名"} を足して返す。不正なら ValueError。"""
    if path is None:
        return dict(SECTIONS)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('sections file must be a JSON object')
    merged = dict(SECTIONS)
    for name, script in data.items():
        if not isinstance(name, str) or not SECTION_NAME.match(name):
            raise ValueError(f'bad section name: {name!r}')
        if not isinstance(script, str) or not SCRIPT_NAME.match(script) or script in ('.', '..'):
            raise ValueError(f'bad script for {name}: {script!r} (a file name directly under lib/muse)')
        merged[name] = script
    return merged


def run_section(script, timeout=TIMEOUT_SECONDS, limit=OUTPUT_LIMIT):
    """スクリプトを実行し、(rc, 出力, 切り詰めたか) を返す。時間切れは TimeoutError。"""
    # 子プロセス(curl など)も残さないよう、別のプロセスグループで起動し、時間切れならグループごと止める。
    proc = subprocess.Popen(['/bin/sh', str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        data, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()  # 出力のパイプも閉じる
        raise TimeoutError(str(e)) from e
    truncated = len(data) > limit
    if truncated:
        data = data[:limit]
    return proc.returncode, data.decode('utf-8', errors='replace'), truncated


class Runner:
    """同時実行の上限・到着順の待ち行列・同じ section のまとめ・成功結果の使い回しを受け持つ。"""

    def __init__(self, timeout, limit, max_concurrent, max_queue, queue_wait, cache_seconds, stale_seconds=0):
        self.timeout, self.limit = timeout, limit
        self.max_concurrent, self.max_queue = max_concurrent, max_queue
        self.queue_wait, self.cache_seconds = queue_wait, cache_seconds
        self.stale_seconds = stale_seconds
        self.cond = threading.Condition()
        self.waiting = deque()
        self.running = []
        self.inflight = {}
        self.cache = {}

    def snapshot(self):
        with self.cond:
            return {'running': len(self.running), 'waiting': len(self.waiting), 'runningSections': list(self.running),
                    'maxConcurrent': self.max_concurrent, 'maxQueue': self.max_queue}

    def request(self, section, script):
        """(HTTPの状態, 本文) を返す。"""
        with self.cond:
            cached = self.cache.get(section)
            if cached:
                age = time.monotonic() - cached[0]
                if age < self.cache_seconds:
                    return cached[1]
                if age < self.stale_seconds:
                    # 古い結果をすぐ返し、取り直しは裏で1回だけ。待ち行列があふれていれば取り直さない
                    if section not in self.inflight and len(self.waiting) < self.max_queue:
                        entry = self._claim(section)
                        threading.Thread(target=self._lead, args=(section, script, entry), daemon=True).start()
                    return cached[1]
            entry = self.inflight.get(section)
            leader = entry is None
            if leader:
                if len(self.waiting) >= self.max_queue:
                    return 503, {'error': 'queue_full', 'section': section, 'maxQueue': self.max_queue}
                entry = self._claim(section)
        if not leader:
            entry['done'].wait()
            return entry['result']
        return self._lead(section, script, entry)

    def warm(self, sections, scripts_dir):
        """全項目を並べて1回ずつ実行し、結果を用意する。終わるまで待つ。"""
        threads = [threading.Thread(target=self.request, args=(name, Path(scripts_dir) / script), daemon=True)
                   for name, script in sections.items() if (Path(scripts_dir) / script).is_file()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def _claim(self, section):
        """self.cond を持った状態で呼ぶ。section の実行を1つに決める。"""
        entry = {'done': threading.Event(), 'result': None}
        self.inflight[section] = entry
        return entry

    def _lead(self, section, script, entry):
        try:
            result = self._run_in_turn(section, script)
        except Exception as e:  # 待っている要求を取り残さない
            result = 500, {'error': 'receiver_error', 'section': section, 'message': str(e)[:200]}
        with self.cond:
            self.inflight.pop(section, None)
            if result[0] == 200 and (self.cache_seconds > 0 or self.stale_seconds > 0):
                self.cache[section] = (time.monotonic(), result)
        entry['result'] = result
        entry['done'].set()
        return result

    def _run_in_turn(self, section, script):
        ticket = object()
        with self.cond:
            self.waiting.append(ticket)
            deadline = time.monotonic() + self.queue_wait
            while not (self.waiting[0] is ticket and len(self.running) < self.max_concurrent):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.waiting.remove(ticket)
                    self.cond.notify_all()
                    return 503, {'error': 'busy', 'section': section, 'queueWaitSeconds': self.queue_wait}
                self.cond.wait(remaining)
            self.waiting.popleft()
            self.running.append(section)
            self.cond.notify_all()
        try:
            rc, output, truncated = run_section(script, self.timeout, self.limit)
        except TimeoutError:
            return 504, {'error': 'timeout', 'section': section, 'timeoutSeconds': self.timeout}
        finally:
            with self.cond:
                self.running.remove(section)
                self.cond.notify_all()
        return 200, {'section': section, 'rc': rc, 'output': output, 'truncated': truncated,
                     'ts': datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')}


def make_handler(key, scripts_dir=SCRIPTS_DIR, sections=None, timeout=TIMEOUT_SECONDS, limit=OUTPUT_LIMIT,
                 max_concurrent=MAX_CONCURRENT, max_queue=MAX_QUEUE, queue_wait=QUEUE_WAIT_SECONDS, cache_seconds=CACHE_SECONDS,
                 stale_seconds=STALE_SECONDS):
    sections = SECTIONS if sections is None else sections
    runner = Runner(timeout, limit, max_concurrent, max_queue, queue_wait, cache_seconds, stale_seconds)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/health':
                return self.reply(200, {'status': 'ok'})
            if path != '/queue' and not path.startswith('/monitor/'):
                return self.reply(404, {'error': 'not_found'})
            # Authorization の照合(REQ-SEC-001/002)。鍵は TS_API_KEY のみで、
            # TS_AUTHKEY(Tailscale の参加鍵)は受信側の鍵として扱わない(REQ-SEC-004)。
            if key is None:
                return self.reply(503, {'error': 'receiver_key_missing'})
            auth = self.headers.get('Authorization', '')
            token = auth[len('Bearer '):] if auth.startswith('Bearer ') else ''
            if not hmac.compare_digest(token, key):
                return self.reply(401, {'error': 'unauthorized'})
            if path == '/queue':
                return self.reply(200, runner.snapshot())
            section = path[len('/monitor/'):]
            script = sections.get(section)
            if script is None or not (Path(scripts_dir) / script).is_file():
                return self.reply(404, {'error': 'unknown_section', 'section': section[:40]})
            self.reply(*runner.request(section, Path(scripts_dir) / script))

        def do_POST(self):
            self.reply(405, {'error': 'method_not_allowed'})

    Handler.runner, Handler.sections, Handler.scripts_dir = runner, sections, scripts_dir
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--sections', help='JSON {"section": "script name"} added to the defaults')
    parser.add_argument('--key-env-file', default=str(Path.home() / '.config' / 'muse-receiver.env'),
                        help='file holding TS_API_KEY (the receiver key); gated paths are 503 while unreadable')
    parser.add_argument('--max-concurrent', type=int, default=MAX_CONCURRENT)
    parser.add_argument('--max-queue', type=int, default=MAX_QUEUE)
    args = parser.parse_args()
    key = load_key(args.key_env_file)
    handler = make_handler(key, sections=load_sections(args.sections),
                           max_concurrent=args.max_concurrent, max_queue=args.max_queue)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    threading.Thread(target=handler.runner.warm, args=(handler.sections, handler.scripts_dir), daemon=True).start()
    print(f'listening on {args.host}:{args.port} (auth: {"on" if key else "unavailable: gated paths return 503"})', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
