"""Codex App Server contract: stored threads must be resumed before turn/start.
Reference: https://learn.chatgpt.com/docs/app-server (2026-11-04).
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from websockets.asyncio.server import unix_serve
sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
from chat_observer import send_to_console

class ConsoleInputTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, status):
        calls = []
        loaded = status != 'notLoaded'
        async def server(ws):
            nonlocal loaded
            async for raw in ws:
                d = json.loads(raw)
                if 'id' not in d: continue
                calls.append(d)
                method = d['method']
                if method == 'thread/read': result = {'thread': {'id': 'fixed-thread', 'status': {'type': status}}}
                elif method == 'thread/resume':
                    self.assertEqual(d['params'], {'threadId': 'fixed-thread', 'excludeTurns': True})
                    loaded = True
                    result = {'thread': {'id': 'fixed-thread'}}
                elif method == 'turn/start':
                    if not loaded:
                        await ws.send(json.dumps({'id': d['id'], 'error': {'code': -32600, 'message': 'thread not found'}}))
                        continue
                    self.assertEqual(d['params']['threadId'], 'fixed-thread')
                    self.assertEqual(d['params']['input'][0]['text'], 'hello')
                    result = {'turn': {'id': 'turn-1', 'status': 'inProgress'}}
                else: result = {}
                await ws.send(json.dumps({'id': d['id'], 'result': result}))
        with tempfile.TemporaryDirectory() as tmp:
            async with unix_serve(server, tmp + '/app.sock'):
                await send_to_console(tmp + '/app.sock', 'fixed-thread', 'hello')
        return [d['method'] for d in calls]

    async def test_resumes_only_fixed_stored_thread_before_sending(self):
        self.assertEqual(await self.exercise('notLoaded'), ['initialize', 'thread/read', 'thread/resume', 'turn/start'])

    async def test_does_not_resume_an_already_loaded_thread(self):
        for status in ('idle', 'active'):
            self.assertEqual(await self.exercise(status), ['initialize', 'thread/read', 'turn/start'])

    async def test_rejects_workspace_and_invalid_thread_ids(self):
        for thread in ('workspace:/root', '../other', ''):
            with self.assertRaises(ValueError): await send_to_console('/unused.sock', thread, 'hello')

    async def test_active_writer_is_preserved_when_queue_is_unavailable(self):
        from chat_observer import ConsoleInputError
        calls = []
        async def server(ws):
            async for raw in ws:
                d = json.loads(raw)
                if 'id' not in d: continue
                calls.append(d['method'])
                if d['method'] == 'thread/queue/add':
                    reply = {'error': {'code': -32601, 'message': 'queue unavailable'}}
                elif d['method'] == 'thread/resume':
                    reply = {'error': {'code': -32600, 'message': 'thread fixed-thread already has an active writer'}}
                else:
                    reply = {'result': {'thread': {'status': {'type': 'notLoaded'}}} if d['method'] == 'thread/read' else {}}
                await ws.send(json.dumps({'id': d['id'], **reply}))
        with tempfile.TemporaryDirectory() as tmp:
            async with unix_serve(server, tmp + '/app.sock'):
                with self.assertRaises(ValueError):
                    await send_to_console(tmp + '/app.sock', 'fixed-thread', 'hello')
        self.assertEqual(calls.count('thread/queue/add'), 1)
        self.assertNotIn('turn/start', calls)

if __name__ == '__main__': unittest.main()
