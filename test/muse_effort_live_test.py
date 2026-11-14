"""muse-vm の api-bridge が推論のエフォート(reasoning_effort)を受け付けるかを、muse-vm の上で確かめるテスト(2026-11-13)。

本体の AIチャット・lib の tunnels.rb から Muse へエフォートを指定し、回答の末尾に `Effort: ◯` を出したい。
`muse exec --reasoning-effort` は CLI の起動オプションで、本体と lib が使う api-bridge(/v1/chat/completions)が
同じ指定を受け付けるかは分かっていない。受け付けないまま本体・lib を作ると、指定が効かず `Effort:` の表示が嘘になる。
本体・lib の実装は、このテストが全部通ってから行う(ユーザー指定 2026-11-13)。

  仮説                                         正しいなら観測されること
  1. api-bridge が reasoning_effort を読む     不正な値(例: "bogus")を送ると 400 で断る(読まずに捨てるなら 200 で答える)
  2. 正しい値はどれも受け付ける                none〜ultra のどれを送っても 200 で答える
  3. 実際に使ったエフォートを応答で返す        応答の JSON に reasoning_effort(送った値と同じ)がある
  4. 指定が推論に効いている                    同じ短い質問で、low の方が high より速い(目安。結果は表に出す)

muse-vm の上で、tailnet も本体も通さずに実行する(鍵は値を出さない):
  cd ~/lib && read -rs MUSE_API_KEY && export MUSE_API_KEY && \
    MUSE_LIVE_URL=http://127.0.0.1:8080 python3 -m unittest test/muse_effort_live_test.py -v; unset MUSE_API_KEY
MUSE_LIVE_URL か MUSE_API_KEY が無ければライブの部分は飛ばす。送る形は偽のサーバーで常に確かめる。
"""
import http.server
import json
import os
import threading
import sys
import unittest

# test/ に __init__.py が無く、muse-vm では `test.` で標準ライブラリの test を探してしまうので、同じフォルダから読む。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from muse_direct_live_test import build_chat_request, probe  # noqa: E402

LIVE_URL = os.environ.get('MUSE_LIVE_URL', '')
LIVE_KEY = os.environ.get('MUSE_API_KEY', '')
TIMEOUT = float(os.environ.get('MUSE_LIVE_TIMEOUT', '300'))
# muse --help の値(2026-11-12 の Muse の回答)。既定は high。
EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra']
QUESTION = '1+1の答えを数字だけで返してください'


def build_effort_request(prompt, effort):
    """本体と同じ形の要求に、OpenAI 形式の reasoning_effort を足す。"""
    body, headers = build_chat_request(prompt)
    payload = json.loads(body)
    payload['reasoning_effort'] = effort
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), headers


def reported_effort(result):
    """応答の JSON にある reasoning_effort(無ければ None)。"""
    try:
        return json.loads(result['body']).get('reasoning_effort')
    except (ValueError, AttributeError):
        return None


class EffortRequestShapeTest(unittest.TestCase):
    def test_body_is_the_worker_shape_plus_reasoning_effort(self):
        received = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received['body'] = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                payload = json.dumps({'model': 'muse', 'reasoning_effort': 'low', 'choices': [{'message': {'content': '2'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            body, headers = build_effort_request('質問', 'low')
            result = probe('http://127.0.0.1:%d' % server.server_port, 'k', 'POST', '/v1/chat/completions', body, headers)
        finally:
            server.shutdown()
        self.assertEqual(received['body'].decode(), '{"model":"muse","messages":[{"role":"user","content":"質問"}],"reasoning_effort":"low"}')
        self.assertEqual(reported_effort(result), 'low')


@unittest.skipUnless(LIVE_URL and LIVE_KEY, 'MUSE_LIVE_URL と MUSE_API_KEY を設定すると、muse-vm の api-bridge で確かめる')
class MuseEffortLiveTest(unittest.TestCase):
    def send(self, effort):
        body, headers = build_effort_request(QUESTION, effort)
        result = probe(LIVE_URL, LIVE_KEY, 'POST', '/v1/chat/completions', body, headers, timeout=TIMEOUT)
        print('\neffort={}: stage={} status={} total={}s reported={}'.format(effort, result['stage'], result['status'], result['total_s'], reported_effort(result)))
        return result

    def test_1_rejects_an_invalid_effort(self):
        result = self.send('bogus')
        self.assertEqual(result['status'], 400, '仮説1: 不正な値を断らない(reasoning_effort を読んでいない)')

    def test_2_and_3_accepts_every_effort_and_reports_it(self):
        for effort in EFFORTS:
            with self.subTest(effort=effort):
                result = self.send(effort)
                self.assertEqual(result['status'], 200, '仮説2: 正しい値を受け付けない')
                self.assertEqual(reported_effort(result), effort, '仮説3: 実際に使ったエフォートを応答で返さない')

    def test_4_low_is_faster_than_high(self):
        low, high = self.send('low'), self.send('high')
        self.assertEqual((low['status'], high['status']), (200, 200))
        self.assertLess(low['total_s'], high['total_s'], '仮説4: low が high より速くない(指定が推論に効いていない可能性)')


if __name__ == '__main__':
    unittest.main()
