import asyncio
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

spec = importlib.util.spec_from_file_location('chat', Path(__file__).parents[1] / 'ops/chat_websocket.py')
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)
ID = 'codex-00000000-0000-0000-0000-000000000000'
ORIGIN = 'https://chat.example'
SECRET = b'test-secret'


class ChatIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []
        self.results = []
        self.socket_patch = patch.object(chat, 'SOCKET', self.directory.name + '/queue.sock')
        self.socket_patch.start()
        self.interval_patch = patch.object(chat, 'POLL_INTERVAL', 0.01)
        self.interval_patch.start()
        self.queue = await asyncio.start_unix_server(self.queue_handler, path=chat.SOCKET)
        self.server = await serve(chat.handler(SECRET), '127.0.0.1', 0, origins=[ORIGIN],
                                  process_request=chat.check_path, max_size=32768)
        self.url = f'ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}' + chat.ENDPOINT

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.queue.close()
        await self.queue.wait_closed()
        self.socket_patch.stop()
        self.interval_patch.stop()
        self.directory.cleanup()

    async def queue_handler(self, reader, writer):
        self.calls.append(json.loads(await reader.readline()))
        result = self.results.pop(0) if self.results else {'ask_id': ID, 'ask_status': 'pending'}
        writer.write((json.dumps(result) + '\n').encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def auth(self, ws):
        challenge = json.loads(await ws.recv())
        signature = hmac.new(SECRET, f'WS\n{chat.ENDPOINT}\n{challenge["nonce"]}'.encode(), hashlib.sha256).hexdigest()
        await ws.send(json.dumps({'type': 'auth', 'signature': signature}))
        self.assertEqual(json.loads(await ws.recv())['type'], 'authenticated')
        return signature

    async def next_result(self, ws):
        while True:
            event = json.loads(await ws.recv())
            if event["type"] not in ("info", "heartbeat"):
                return event

    async def test_submit_delivers_status_and_final_reply(self):
        self.results = [{'ask_id': ID, 'ask_status': status} for status in ('pending', 'pending', 'running')]
        self.results.append({'ask_id': ID, 'ask_status': 'done', 'reply': 'こんにちは', 'llm_model': 'test-model'})
        async with connect(self.url, origin=ORIGIN) as ws:
            await self.auth(ws)
            await ws.send(json.dumps({'type': 'submit', 'engine': 'codex', 'prompt': 'Hello\nworld'}))
            states = [await self.next_result(ws) for _ in range(3)]
            self.assertEqual([s['ask_status'] for s in states], ['pending', 'running', 'done'])
            self.assertEqual(states[-1]['reply'], 'こんにちは')
            self.assertEqual(states[-1]['llm_model'], 'test-model')
        self.assertEqual(self.calls[0], {'op': 'submit', 'engine': 'codex', 'prompt': 'Hello\nworld'})
        self.assertTrue(all(call['op'] == 'poll' for call in self.calls[1:]))

    async def test_muse_submit_polls_its_job_to_the_final_reply(self):
        muse_id = 'muse-00000000-0000-0000-0000-000000000000'
        self.results = [{'ask_id': muse_id, 'ask_status': 'pending'},
                        {'ask_id': muse_id, 'ask_status': 'done', 'reply': 'PONG', 'via': 'muse'}]
        async with connect(self.url, origin=ORIGIN) as ws:
            await self.auth(ws)
            await ws.send(json.dumps({'type': 'submit', 'engine': 'muse', 'prompt': 'Hello'}))
            states = [await self.next_result(ws) for _ in range(2)]
        self.assertEqual([s.get('ask_status') for s in states], ['pending', 'done'])
        self.assertEqual(states[-1]['reply'], 'PONG')
        self.assertEqual(self.calls[0], {'op': 'submit', 'engine': 'muse', 'prompt': 'Hello'})
        self.assertEqual(self.calls[1], {'op': 'poll', 'ask_id': muse_id})

    async def test_muse_job_can_be_resumed(self):
        muse_id = 'muse-00000000-0000-0000-0000-000000000000'
        self.assertEqual(chat.worker_payload({'type': 'resume', 'ask_id': muse_id}), {'op': 'poll', 'ask_id': muse_id})

    async def test_engines_without_a_worker_are_still_rejected(self):
        with self.assertRaises(ValueError):
            chat.worker_payload({'type': 'submit', 'engine': 'nemotron', 'prompt': 'Hello'})

    async def test_resume_only_polls(self):
        self.results = [{'ask_id': ID, 'ask_status': 'done', 'reply': 'existing'}]
        async with connect(self.url, origin=ORIGIN) as ws:
            await self.auth(ws)
            await ws.send(json.dumps({'type': 'resume', 'ask_id': ID}))
            self.assertEqual((await self.next_result(ws))['reply'], 'existing')
        self.assertEqual(self.calls, [{'op': 'poll', 'ask_id': ID}])

    async def test_bad_auth_cannot_enqueue(self):
        async with connect(self.url, origin=ORIGIN) as ws:
            await ws.recv()
            await ws.send(json.dumps({'type': 'auth', 'signature': '0' * 64}))
            with self.assertRaises(ConnectionClosed) as error:
                await ws.recv()
            self.assertEqual(error.exception.rcvd.code, 1008)
        self.assertEqual(self.calls, [])

    async def test_demo_auth_cannot_observe_or_submit(self):
        for operation in ({'type': 'observe'}, {'type': 'submit', 'engine': 'codex', 'prompt': 'hello'}):
            async with connect(self.url, origin=ORIGIN) as ws:
                await ws.recv()
                await ws.send(json.dumps({'type': 'demo_auth'}))
                self.assertEqual(json.loads(await ws.recv())['type'], 'authenticated')
                await ws.send(json.dumps(operation))
                with self.assertRaises(ConnectionClosed) as error:
                    await ws.recv()
                self.assertEqual(error.exception.rcvd.code, 1008)
        self.assertEqual(self.calls, [])

    async def test_demo_delivers_deltas_without_calling_queue(self):
        with patch.object(chat, 'DEMO_TEXT', '日本語' * 10), patch.object(chat, 'DEMO_INTERVAL', 0):
            async with connect(self.url, origin=ORIGIN) as ws:
                await ws.recv()
                await ws.send(json.dumps({'type': 'demo_auth'}))
                await ws.recv()
                await ws.send(json.dumps({'type': 'demo'}))
                events = []
                while True:
                    event = json.loads(await ws.recv())
                    events.append(event)
                    if event.get('ask_status') == 'done':
                        break
        self.assertEqual(''.join(event['text'] for event in events if event['type'] == 'delta'), '日本語' * 10)
        self.assertEqual(self.calls, [])

    async def test_signature_cannot_be_replayed(self):
        async with connect(self.url, origin=ORIGIN) as ws:
            signature = await self.auth(ws)
        async with connect(self.url, origin=ORIGIN) as ws:
            await ws.recv()
            await ws.send(json.dumps({'type': 'auth', 'signature': signature}))
            with self.assertRaises(ConnectionClosed):
                await ws.recv()
        self.assertEqual(self.calls, [])

    async def test_wrong_origin_or_path_rejected(self):
        for origin, url in [('https://evil.example', self.url), (None, self.url), (ORIGIN, self.url + '?secret=no')]:
            with self.assertRaises(InvalidStatus):
                async with connect(url, origin=origin):
                    self.fail('Handshake must fail')
        self.assertEqual(self.calls, [])

    async def test_invalid_prompt_does_not_enqueue(self):
        for prompt in ['', 'あ' * 6000, None]:
            async with connect(self.url, origin=ORIGIN) as ws:
                await self.auth(ws)
                await ws.send(json.dumps({'type': 'submit', 'engine': 'codex', 'prompt': prompt}, ensure_ascii=False))
                self.assertEqual(json.loads(await ws.recv())['error'], 'invalid_request')
        self.assertEqual(self.calls, [])

    async def test_unavailable_worker_returns_fixed_error(self):
        with patch.object(chat, 'SOCKET', self.directory.name + '/missing.sock'):
            async with connect(self.url, origin=ORIGIN) as ws:
                await self.auth(ws)
                await ws.send(json.dumps({'type': 'resume', 'ask_id': ID}))
                result = await self.next_result(ws)
                self.assertEqual(result, {'type': 'error', 'error': 'worker_unavailable'})

    async def test_disconnect_stops_polling_without_resubmit(self):
        async with connect(self.url, origin=ORIGIN) as ws:
            await self.auth(ws)
            await ws.send(json.dumps({'type': 'submit', 'engine': 'claude', 'prompt': 'Hello'}))
            await self.next_result(ws)
        await asyncio.sleep(0.03)
        count = len(self.calls)
        await asyncio.sleep(0.03)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(sum(call['op'] == 'submit' for call in self.calls), 1)


if __name__ == '__main__':
    unittest.main()
