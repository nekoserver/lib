import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
import chat_session as session
import chat_http_stream as http
import chat_websocket as ws_backend
SECRET = b'test-secret'
ORIGIN = 'https://chat.example'

class SessionTest(unittest.IsolatedAsyncioTestCase):
    def test_expiry_origin_tampering_and_secret_rotation(self):
        token = session.issue(SECRET, ORIGIN)
        self.assertTrue(session.valid(SECRET, token, ORIGIN))
        self.assertFalse(session.valid(SECRET, token, 'https://other.example'))
        self.assertFalse(session.valid(SECRET, token + 'x', ORIGIN))
        self.assertFalse(session.valid(b'rotated', token, ORIGIN))
        with patch.object(session.time, 'time', return_value=time.time() + session.TTL + 1):
            self.assertFalse(session.valid(SECRET, token, ORIGIN))

    async def test_http_issue_then_readonly_stream_and_reject_submission(self):
        async with TestClient(TestServer(http.create_app(SECRET, {ORIGIN}))) as client:
            path = http.PREFIX + 'session'; body = b'{"type":"observe"}'; timestamp = str(int(time.time()))
            headers = {'Origin': ORIGIN, 'X-Timestamp': timestamp, 'X-Signature': hmac.new(SECRET, f'POST\n{path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}'.encode(), hashlib.sha256).hexdigest()}
            denied = await client.post(path, data=body, headers={'Origin': ORIGIN})
            self.assertEqual(denied.status, 401)
            response = await client.post(path, data=body, headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            token = (await response.json())['token']
            async def events(payload, disconnected):
                yield {'type': 'conversation', 'messages': []}
            with patch.object(http, 'event_stream', events):
                for protocol in http.TYPES:
                    response = await client.post(http.PREFIX + protocol, json={'type': 'observe'}, headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + token})
                    self.assertEqual(response.status, 200)
                    self.assertIn('conversation', await response.text())
                response = await client.post(http.PREFIX + 'sse', json={'type': 'submit', 'engine': 'codex', 'prompt': 'hello'}, headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + token})
                self.assertEqual(response.status, 401)

    async def test_websocket_session_observes_but_cannot_submit(self):
        async def events(payload, disconnected):
            yield {'type': 'conversation', 'messages': []}
        with patch.object(ws_backend, 'event_stream', events):
            async with serve(ws_backend.handler(SECRET), '127.0.0.1', 0, origins=[ORIGIN], process_request=ws_backend.check_path) as server:
                url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}' + ws_backend.ENDPOINT
                for request, allowed in [({'type':'observe'}, True), ({'type':'submit','engine':'codex','prompt':'hello'}, False)]:
                    async with connect(url, origin=ORIGIN) as ws:
                        await ws.recv()
                        await ws.send(json.dumps({'type':'session_auth','token':session.issue(SECRET, ORIGIN)}))
                        self.assertEqual(json.loads(await ws.recv())['type'], 'authenticated')
                        await ws.send(json.dumps(request))
                        if allowed: self.assertEqual(json.loads(await ws.recv())['type'], 'conversation')
                        else:
                            with self.assertRaises(ConnectionClosed): await ws.recv()
                            self.assertEqual(ws.close_code, 1008)
