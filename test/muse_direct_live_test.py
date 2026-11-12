"""muse-vm の api-bridge へ直接送り、どこで止まるかを確定するテスト(2026-11-12)。

本番で「muse-vm に届く(Muse の通知が来る)のに返事が来ず、10分で短いエラーが返る」が、Worker 内 WASM 経由でも
本体のコンテナ経由でも起きた。経路の外で api-bridge を直接試し、仮説ごとに観測を分ける。

  仮説                              正しいなら観測されること
  1. api-bridge が止まっている       /health が返らない
  2. 推論が止まっている              /health と /ping(推論を使わない)は返るのに、短い推論のヘッダが来ない
  3. stream の扱いが原因             stream:false を付けたときだけ返る

muse-vm の上で、tailnet も本体も通さずに実行する(鍵は値を出さない):
  MUSE_LIVE_URL=http://127.0.0.1:8080 MUSE_API_KEY=... python3 -m unittest test.muse_direct_live_test -v
MUSE_LIVE_URL か MUSE_API_KEY が無ければライブの部分は飛ばす。送り方が本体と同じかは、偽のサーバーで常に確かめる。
"""
import http.client
import http.server
import json
import os
import threading
import time
import unittest
import urllib.parse

LIVE_URL = os.environ.get('MUSE_LIVE_URL', '')
LIVE_KEY = os.environ.get('MUSE_API_KEY', '')
# 推論のヘッダを待つ上限。本体の待ち時間(300秒)より短くして、どこで止まるかを先に見る。
INFERENCE_TIMEOUT = float(os.environ.get('MUSE_LIVE_TIMEOUT', '120'))


def build_chat_request(prompt, stream=None):
    """本体(src/utils/wasmMuseBridge.ts・containers/demo/server.js)と同じ形の要求を作る。"""
    payload = {'model': 'muse', 'messages': [{'role': 'user', 'content': prompt}]}
    if stream is not None:
        payload['stream'] = stream
    # JSON.stringify と同じく空白を入れない(本体が送るバイト列と同じにする)。
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return body, {'Content-Type': 'application/json'}


def probe(base_url, key, method, path, body=None, headers=None, timeout=10.0):
    """1回送って、ヘッダが来るまでの秒数・全部読むまでの秒数・ステータス・本文を返す。止まったら stage で示す。"""
    url = urllib.parse.urlsplit(base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=timeout)
    sent = dict(headers or {})
    sent['Authorization'] = 'Bearer ' + key
    started = time.monotonic()
    result = {'stage': 'connect', 'status': None, 'headers_s': None, 'total_s': None, 'body': b''}
    try:
        conn.request(method, path, body=body, headers=sent)
        result['stage'] = 'awaiting_headers'
        response = conn.getresponse()
        result['headers_s'] = round(time.monotonic() - started, 2)
        result['status'] = response.status
        result['content_type'] = response.getheader('Content-Type')
        result['stage'] = 'reading_body'
        result['body'] = response.read()
        result['total_s'] = round(time.monotonic() - started, 2)
        result['stage'] = 'done'
    except (OSError, http.client.HTTPException) as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        conn.close()
    return result


def describe(name, result):
    """結果を1行にする(鍵や本文は出さない)。"""
    return '{}: stage={} status={} headers={}s total={}s content_type={} bytes={} error={}'.format(
        name, result['stage'], result['status'], result['headers_s'], result['total_s'],
        result.get('content_type'), len(result['body']), result.get('error'))


class RequestShapeTest(unittest.TestCase):
    """ライブで試す要求が、本体が送るものと同じ形であること(ずれていたら試す意味がない)。"""

    def test_same_headers_and_body_as_the_worker(self):
        received = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received['path'] = self.path
                received['auth'] = self.headers.get('Authorization')
                received['type'] = self.headers.get('Content-Type')
                received['body'] = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                payload = json.dumps({'model': 'muse', 'choices': [{'message': {'content': 'ok'}}]}).encode()
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
            body, headers = build_chat_request('質問')
            result = probe('http://127.0.0.1:%d' % server.server_port, 'test-key', 'POST', '/v1/chat/completions', body, headers)
        finally:
            server.shutdown()
        self.assertEqual(result['stage'], 'done')
        self.assertEqual(received['path'], '/v1/chat/completions')
        self.assertEqual(received['auth'], 'Bearer test-key')
        self.assertEqual(received['type'], 'application/json')
        self.assertEqual(received['body'].decode('utf-8'), '{"model":"muse","messages":[{"role":"user","content":"質問"}]}')

    def test_stalled_server_is_reported_as_awaiting_headers(self):
        """ヘッダを返さないサーバーなら、止まった段階が awaiting_headers と出ること(仮説2の見分け方)。"""
        stop = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                stop.wait(5)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            body, headers = build_chat_request('質問')
            result = probe('http://127.0.0.1:%d' % server.server_port, 'k', 'POST', '/v1/chat/completions', body, headers, timeout=0.5)
        finally:
            stop.set()
            server.shutdown()
        self.assertEqual(result['stage'], 'awaiting_headers')
        self.assertIsNone(result['status'])


@unittest.skipUnless(LIVE_URL and LIVE_KEY, 'MUSE_LIVE_URL と MUSE_API_KEY を設定すると、muse-vm の api-bridge を直接試す')
class MuseDirectLiveTest(unittest.TestCase):
    """番号の順に実行する。前の段階が失敗したら、それより後ろの結果は原因の特定に使わない。"""

    def test_1_health_answers(self):
        result = probe(LIVE_URL, LIVE_KEY, 'GET', '/health', timeout=10)
        print('\n' + describe('health', result))
        self.assertEqual(result['stage'], 'done', '仮説1: api-bridge が /health に答えない(止まっている)。' + describe('health', result))
        self.assertEqual(result['status'], 200, describe('health', result))

    def test_2_ping_answers_without_inference(self):
        body, headers = build_chat_request('/ping')
        result = probe(LIVE_URL, LIVE_KEY, 'POST', '/v1/chat/completions', body, headers, timeout=15)
        print('\n' + describe('ping', result))
        self.assertEqual(result['stage'], 'done', 'api-bridge がチャットの入口で止まっている(推論を使わない /ping も返らない)。' + describe('ping', result))
        self.assertEqual(result['status'], 200, describe('ping', result))

    def test_3_short_inference_without_stream(self):
        body, headers = build_chat_request('1+1の答えを数字だけで返してください')
        result = probe(LIVE_URL, LIVE_KEY, 'POST', '/v1/chat/completions', body, headers, timeout=INFERENCE_TIMEOUT)
        print('\n' + describe('inference(stream無し)', result))
        self.assertNotEqual(result['stage'], 'awaiting_headers', '仮説2: /ping は返るのに推論のヘッダが来ない(推論が止まっている)。' + describe('inference', result))
        self.assertEqual(result['stage'], 'done', describe('inference', result))
        self.assertEqual(result['status'], 200, describe('inference', result))

    def test_4_short_inference_with_stream_false(self):
        body, headers = build_chat_request('1+1の答えを数字だけで返してください', stream=False)
        result = probe(LIVE_URL, LIVE_KEY, 'POST', '/v1/chat/completions', body, headers, timeout=INFERENCE_TIMEOUT)
        print('\n' + describe('inference(stream:false)', result))
        self.assertEqual(result['stage'], 'done', '仮説3の確認: stream:false でも返らない。' + describe('inference', result))
        self.assertEqual(result['status'], 200, describe('inference', result))


if __name__ == '__main__':
    unittest.main()
