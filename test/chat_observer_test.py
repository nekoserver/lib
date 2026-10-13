import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
from websockets.asyncio.server import unix_serve
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
import chat_observer as observer


class ObserverTest(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_excludes_reasoning_tool_output_and_other_thread_metadata(self):
        turns = [{'items': [
            {'type': 'userMessage', 'id': 'user', 'content': [{'type': 'text', 'text': 'こんにちは'}]},
            {'type': 'agentMessage', 'id': 'answer', 'phase': 'commentary', 'text': '作業中です'},
            {'type': 'reasoning', 'content': 'PRIVATE_REASONING'},
            {'type': 'commandExecution', 'command': 'SECRET_COMMAND', 'aggregatedOutput': 'PRIVATE_OUTPUT', 'status': 'completed'},
        ]}]
        snapshot = observer.public_snapshot({'name': 'この会話', 'status': {'type': 'active'}}, turns)
        wire = json.dumps(snapshot)
        for private in ('PRIVATE_REASONING', 'SECRET_COMMAND', 'PRIVATE_OUTPUT'):
            self.assertNotIn(private, wire)
        self.assertEqual([message['text'] for message in snapshot['messages']], ['こんにちは', '作業中です'])
        self.assertEqual(snapshot['activity'], [{'kind': 'commandExecution', 'status': 'completed'}])

    async def test_rpc_client_refuses_all_mutating_methods(self):
        ws = AsyncMock()
        client = observer.ReadClient(ws)
        for method in ('turn/start', 'turn/steer', 'thread/resume', 'thread/fork', 'thread/name/set'):
            with self.assertRaises(ValueError):
                await client.request(method, {})
        ws.send.assert_not_called()

    async def test_observer_reads_only_the_configured_thread_over_real_unix_websocket(self):
        calls = []
        async def app_server(ws):
            async for raw in ws:
                message = json.loads(raw)
                if 'id' not in message:
                    continue
                calls.append(message)
                if message['method'] == 'initialize': result = {}
                elif message['method'] == 'thread/read': result = {'thread': {'name': 'Fixed conversation', 'status': {'type': 'active'}}}
                else: result = {'data': [{'items': [{'type': 'agentMessage', 'id': '1', 'text': '# Streaming reply', 'phase': 'commentary'}]}]}
                await ws.send(json.dumps({'id': message['id'], 'result': result}))
        with tempfile.TemporaryDirectory() as directory:
            async with unix_serve(app_server, directory + '/app.sock'):
                stream = observer.snapshots(directory + '/app.sock', 'fixed-thread')
                snapshot = await anext(stream)
                await stream.aclose()
        self.assertEqual(snapshot['messages'][0]['text'], '# Streaming reply')
        self.assertEqual([call['method'] for call in calls], ['initialize', 'thread/read', 'thread/turns/list'])
        self.assertTrue(all(call['params'].get('threadId') == 'fixed-thread' for call in calls[1:]))


if __name__ == '__main__':
    unittest.main()
