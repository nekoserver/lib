import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
import chat_http_stream as http
import chat_websocket as backend

ORIGIN = 'https://chat.example'
SECRET = b'test-secret'
ID = 'codex-00000000-0000-0000-0000-000000000000'


def decode(protocol, wire):
    if protocol == 'sse':
        return [json.loads(line[6:]) for line in wire.splitlines() if line.startswith('data: ')]
    if protocol == 'jsonseq':
        return [json.loads(line) for line in wire.split('\x1e') if line.strip()]
    return [json.loads(line) for line in wire.splitlines() if line]


class StreamIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_observer_reports_observer_failure_for_all_protocols(self):
        for protocol in http.TYPES:
            path = http.PREFIX + protocol
            body = b'{"type":"observe"}'
            with patch.object(backend.asyncio, 'open_unix_connection', new_callable=AsyncMock,
                              side_effect=FileNotFoundError):
                response = await self.client.post(path, data=body, headers=self.signed(path, body))
                events = decode(protocol, await response.text())
                self.assertEqual(events[-1], {'type': 'error', 'error': 'observer_unavailable'})

    async def asyncSetUp(self):
        self.client = TestClient(TestServer(http.create_app(SECRET, {ORIGIN})))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def signed(self, path, body):
        ts = str(int(time.time()))
        canonical = f'POST\n{path}\n{ts}\n{hashlib.sha256(body).hexdigest()}'
        return {'Origin': ORIGIN, 'X-Timestamp': ts,
                'X-Signature': hmac.new(SECRET, canonical.encode(), hashlib.sha256).hexdigest()}

    async def test_all_three_streams_deliver_before_completion_without_model_calls(self):
        for protocol in http.TYPES:
            with patch.object(backend, 'DEMO_TEXT', '日本語' * 30), patch.object(backend, 'DEMO_INTERVAL', .02), \
                 patch.object(backend, 'worker_request', new_callable=AsyncMock) as worker:
                response = await self.client.post(http.PREFIX + protocol, json={'type': 'demo'}, headers={'Origin': ORIGIN})
                self.assertEqual(response.status, 200)
                self.assertEqual(response.content_type, http.TYPES[protocol])
                first = await response.content.readany()
                self.assertIn(b'info', first)
                self.assertFalse(response.content.at_eof())
                events = decode(protocol, (first + await response.read()).decode())
                self.assertEqual(events[-1]['ask_status'], 'done')
                self.assertEqual(''.join(event['text'] for event in events if event['type'] == 'delta'), '日本語' * 30)
                worker.assert_not_called()

    async def test_signed_resume_polls_existing_job_for_all_protocols(self):
        for protocol in http.TYPES:
            path = http.PREFIX + protocol
            body = json.dumps({'type': 'resume', 'ask_id': ID}).encode()
            with patch.object(backend, 'worker_request', new_callable=AsyncMock,
                              return_value={'ask_id': ID, 'ask_status': 'done', 'reply': 'existing'}) as worker:
                response = await self.client.post(path, data=body, headers=self.signed(path, body))
                events = decode(protocol, await response.text())
                self.assertEqual(events[-1]['reply'], 'existing')
                worker.assert_awaited_once_with({'op': 'poll', 'ask_id': ID})

    async def test_unauthed_observation_or_submission_cannot_reach_private_services(self):
        with patch.object(backend, 'worker_request', new_callable=AsyncMock) as worker:
            for kind in ('observe', 'submit'):
                response = await self.client.post(http.PREFIX + 'sse', json={'type': kind, 'engine': 'codex', 'prompt': 'hello'}, headers={'Origin': ORIGIN})
                self.assertEqual(response.status, 401)
            worker.assert_not_called()

    async def test_wrong_origin_and_replayed_signature_on_other_path_fail(self):
        body = b'{"type":"resume","ask_id":"' + ID.encode() + b'"}'
        response = await self.client.post(http.PREFIX + 'sse', json={'type': 'demo'}, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status, 403)
        headers = self.signed(http.PREFIX + 'sse', body)
        response = await self.client.post(http.PREFIX + 'ndjson', data=body, headers=headers)
        self.assertEqual(response.status, 401)

    async def test_heartbeats_during_unchanged_jobs(self):
        pending = {'ask_id': ID, 'ask_status': 'pending'}
        done = {'ask_id': ID, 'ask_status': 'done', 'reply': 'ok'}
        with patch.object(backend, 'worker_request', new_callable=AsyncMock, side_effect=[pending, pending, done]), \
             patch.object(backend, 'HEARTBEAT_INTERVAL', 0), patch.object(backend, 'POLL_INTERVAL', 0):
            events = [event async for event in backend.event_stream({'op': 'poll', 'ask_id': ID})]
        self.assertIn({'type': 'heartbeat'}, events)


class SpecEvalAuthorizationTest(StreamIntegrationTest):
    async def test_read_and_write_capabilities_are_separate(self):
        response = await self.client.post(http.PREFIX+'session', data=b'{"type":"observe"}', headers=self.signed(http.PREFIX+'session', b'{"type":"observe"}'))
        observer = (await response.json())['token']
        data={'action':'create','repository':'nekoserver/dynamicneko','path':'SPEC.feature.md'}
        with patch.object(http.asyncio,'open_unix_connection',new_callable=AsyncMock) as upstream:
            response=await self.client.post(http.PREFIX+'spec-eval',json=data,headers={'Origin':ORIGIN,'Authorization':'Bearer '+observer})
            self.assertEqual(response.status,401)
            response=await self.client.post(http.PREFIX+'spec-eval',json={**data,'action':'inspect'},headers={'Origin':'https://evil.example','Authorization':'Bearer '+observer})
            self.assertEqual(response.status,403)
            response=await self.client.post(http.PREFIX+'spec-eval',json={**data,'path':[]},headers={'Origin':ORIGIN,'Authorization':'Bearer '+observer})
            self.assertEqual(response.status,400)
            upstream.assert_not_called()

    async def test_console_capability_relays_structured_request_and_revocation_stops_write(self):
        path=http.PREFIX+'console-session'; body=b'{"type":"console","ttl_seconds":3600}'
        response=await self.client.post(path,data=body,headers=self.signed(path,body))
        token=(await response.json())['token']
        writer=AsyncMock(); writer.write=Mock(); writer.close=Mock(); reader=AsyncMock()
        reader.readline.return_value=b'{"available":true,"connected":true,"eval":null,"run":{"id":"run","status":"pending"}}\n'
        with patch.object(http.asyncio,'open_unix_connection',new_callable=AsyncMock,return_value=(reader,writer)):
            response=await self.client.post(http.PREFIX+'spec-eval',json={'action':'create','repository':'nekoserver/dynamicneko','path':'SPEC.feature.md'},headers={'Origin':ORIGIN,'Authorization':'Bearer '+token})
            self.assertEqual(response.status,200)
            self.assertEqual(json.loads(writer.write.call_args.args[0])['op'],'spec-eval')
        await self.client.delete(path,headers={'Origin':ORIGIN,'Authorization':'Bearer '+token})
        response=await self.client.post(http.PREFIX+'spec-eval',json={'action':'create','repository':'nekoserver/dynamicneko','path':'SPEC.feature.md'},headers={'Origin':ORIGIN,'Authorization':'Bearer '+token})
        self.assertEqual(response.status,401)


    async def test_console_input_returns_conflict_for_owned_thread_and_acknowledges_acceptance(self):
        path = http.PREFIX + 'console-session'; body = b'{"type":"console","ttl_seconds":900}'
        response = await self.client.post(path, data=body, headers=self.signed(path, body))
        token = (await response.json())['token']
        writer = AsyncMock(); writer.write = Mock(); writer.close = Mock(); reader = AsyncMock()
        for payload, status in [(b'{"type":"error","error":"console_in_use"}\n', 409), (b'{"type":"accepted"}\n', 200)]:
            reader.readline.return_value = payload
            with patch.object(http.asyncio, 'open_unix_connection', new_callable=AsyncMock, return_value=(reader, writer)):
                response = await self.client.post(http.PREFIX + 'console', json={'prompt':'hello'}, headers={'Origin':ORIGIN,'Authorization':'Bearer '+token})
                self.assertEqual(response.status, status)
                self.assertEqual(json.loads(writer.write.call_args.args[0]), {'op':'send','text':'hello'})


if __name__ == '__main__':
    unittest.main()
