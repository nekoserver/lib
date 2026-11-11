#!/usr/bin/env python3
"""receiver.py - muse-monitor が呼ぶ受信側(/monitor/<section>)のサンプル。

契約は nekoserver/muse-monitor の docs/RECEIVER.md:
- GET /monitor/<section>、Authorization: Bearer <鍵> が必須
- 鍵は環境変数 MUSE_CODE_WASM_API_KEY(muse-monitor 側の TS_API_KEY と同じ値)
- 鍵が未設定なら 503、ヘッダーが無い・不一致なら 401、未知の section は 404
- 応答は {"section", "rc", "output", "truncated", "ts"}。output は 64 KiB で切り詰め、60 秒で 504
- GET /health は認証なしで {"status": "ok"}(muse-monitor が相手を探すときに叩く)

このサンプルは lib/muse のスクリプトがある section だけを扱う(読み取り専用)。
diag・pending・execlog・sdk* はスクリプトが無いので 404 を返す。

使い方: MUSE_CODE_WASM_API_KEY=... python3 receiver.py [--host 127.0.0.1] [--port 8090]
既定で 127.0.0.1 にだけ待ち受ける。tailnet に出すときは --host にそのアドレスを指定する。
"""
import argparse
from datetime import datetime
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess

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
        proc.wait()
        raise TimeoutError(str(e)) from e
    truncated = len(data) > limit
    if truncated:
        data = data[:limit]
    return proc.returncode, data.decode('utf-8', errors='replace'), truncated


def make_handler(key, scripts_dir=SCRIPTS_DIR, sections=None, timeout=TIMEOUT_SECONDS, limit=OUTPUT_LIMIT):
    sections = SECTIONS if sections is None else sections

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
            if not path.startswith('/monitor/'):
                return self.reply(404, {'error': 'not_found'})
            if not key:
                return self.reply(503, {'error': 'receiver_key_not_configured'})
            given = self.headers.get('Authorization', '')
            if not given.startswith('Bearer ') or not hmac.compare_digest(given[7:].encode(), key.encode()):
                return self.reply(401, {'error': 'unauthorized'})
            section = path[len('/monitor/'):]
            script = sections.get(section)
            if script is None or not (Path(scripts_dir) / script).is_file():
                return self.reply(404, {'error': 'unknown_section', 'section': section[:40]})
            try:
                rc, output, truncated = run_section(Path(scripts_dir) / script, timeout, limit)
            except TimeoutError:
                return self.reply(504, {'error': 'timeout', 'section': section, 'timeoutSeconds': timeout})
            return self.reply(200, {'section': section, 'rc': rc, 'output': output, 'truncated': truncated,
                                    'ts': datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')})

        def do_POST(self):
            self.reply(405, {'error': 'method_not_allowed'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(os.environ.get('MUSE_CODE_WASM_API_KEY', '')))
    print(f'listening on {args.host}:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
