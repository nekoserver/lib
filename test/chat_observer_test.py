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
    async def test_trusted_target_change_refreshes_an_existing_stream(self):
        calls = []
        async def app_server(ws):
            async for raw in ws:
                message = json.loads(raw)
                if 'id' not in message: continue
                calls.append(message)
                if message['method'] == 'initialize': result = {}
                elif message['method'] == 'thread/read': result = {'thread': {'name': message['params']['threadId'], 'status': {'type': 'active'}}}
                else: result = {'data': [{'items': [{'type': 'agentMessage', 'id': '1', 'text': message['params']['threadId']}]}]}
                await ws.send(json.dumps({'id': message['id'], 'result': result}))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            path = directory + '/app.sock'
            source.write_text(json.dumps({'appSocket': path, 'threadId': 'old-thread'})); source.chmod(0o600)
            async with unix_serve(app_server, path):
                stream = observer.snapshots(path, 'fallback-thread', source_file=source)
                first = await anext(stream)
                source.write_text(json.dumps({'appSocket': path, 'threadId': 'current-thread'}))
                second = await anext(stream)
                await stream.aclose()
        self.assertEqual(first['messages'][0]['text'], 'old-thread')
        self.assertEqual(second['messages'][0]['text'], 'current-thread')
        self.assertTrue(all(call['method'] in observer.READ_METHODS | {'initialize'} for call in calls))

    def test_source_configuration_must_be_private_and_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            source.write_text('{"appSocket":"/private/app.sock","threadId":"current-thread"}'); source.chmod(0o600)
            self.assertEqual(observer.configured_source('/fallback.sock', 'fallback', source), ('/private/app.sock', 'current-thread'))
            source.chmod(0o666)
            with self.assertRaises(ValueError): observer.configured_source('/fallback.sock', 'fallback', source)
            source.chmod(0o600); source.write_text('{}')
            with self.assertRaises(ValueError): observer.configured_source('/fallback.sock', 'fallback', source)

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
        self.assertEqual([call['method'] for call in calls], ['initialize', 'thread/read', 'thread/turns/list', 'thread/queue/list'])
        self.assertTrue(all(call['params'].get('threadId') == 'fixed-thread' for call in calls[1:]))


    async def test_eval_uses_existing_console_rpc_and_verifies_real_file(self):
        from spec_eval import SpecEvaluations
        import subprocess
        calls=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); repo=root/'repo'; repo.mkdir()
            subprocess.run(['git','init','-q',str(repo)],check=True)
            subprocess.run(['git','-C',str(repo),'remote','add','origin','https://github.com/nekoserver/dynamicneko.git'],check=True)
            (repo/'SPEC.feature.md').write_text('# Feature')
            service=SpecEvaluations({'nekoserver/dynamicneko':str(repo)},root/'receipts')
            async def app_server(ws):
                async for raw in ws:
                    message=json.loads(raw)
                    if 'id' not in message: continue
                    calls.append(message['method'])
                    if message['method']=='thread/read': result={'thread':{'status':{'type':'idle'}}}
                    else: result={}
                    if message['method']=='turn/start':
                        prompt=message['params']['input'][0]['text']
                        self.assertIn(str(repo),prompt)
                        header=next(line for line in prompt.splitlines() if line.startswith('<!-- tree-view-spec-eval '))
                        (repo/'EVAL.feature.md').write_text(header+'\n## 評価\n根拠付きの完成した評価本文を保存した。\n')
                    await ws.send(json.dumps({'id':message['id'],'result':result}))
            socket=directory+'/app.sock'
            with patch.object(observer,'configured_evaluations',return_value=service), patch.object(observer,'SOURCE_FILE',root/'absent.json'), patch.dict(observer.os.environ,{'LIB_CHAT_APP_SOCKET':socket,'LIB_CHAT_THREAD_ID':'fixed-thread'}):
                async with unix_serve(app_server,socket):
                    operation={'op':'spec-eval','action':'create','repository':'nekoserver/dynamicneko','path':'SPEC.feature.md'}
                    accepted=await observer.spec_evaluation(operation)
                    self.assertTrue(accepted['connected'])
                    self.assertIsNone(accepted['eval'])
                    result=await observer.spec_evaluation({**operation,'action':'inspect'})
                    self.assertEqual(result['run']['status'],'completed')
                    self.assertEqual(result['eval']['path'],'EVAL.feature.md')
                    await observer.spec_evaluation(operation)
            self.assertEqual(calls.count('turn/start'),1)


if __name__ == '__main__':
    unittest.main()
