#!/usr/bin/env python3
"""Authenticated WebSocket bridge to the existing private LLM queue."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from chat_session import valid
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ENDPOINT = '/lib/api/chat/ws'
SOCKET = os.environ.get('LIB_CODEX_SOCKET', '/run/lib-codex/worker.sock')
IDS = re.compile(r'^(codex|claude)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
POLL_INTERVAL = 0.5
HEARTBEAT_INTERVAL = 5
DEMO_INTERVAL = 0.1
DEMO_TEXT = '# ストリーム比較デモ\n\nこれはAIを呼ばずに配信するサンプルです。選んだ通信方式で、文章が少しずつ届きます。\n\n## 比べるポイント\n\n- 最初のイベントが届く時間\n- 更新の回数と間隔\n- 受信を停止したときの動き\n\n```python\nfor chunk in stream:\n    print(chunk, end="", flush=True)\n```\n\n| 通信方式 | データの区切り |\n| --- | --- |\n| SSE | event / data と空行 |\n| WebSocket | メッセージ |\n| NDJSON | 改行 |\n| JSON Text Sequence | RS文字と改行 |\n\n**どの方式も同じ文章を配信します。** AIの生成速度と、通信方式の違いを分けて試せます。\n'


def load_secret():
    try:
        secret = Path(os.environ.get('LIB_CHAT_SECRET_FILE', '/etc/apache2/secrets/origin-hmac')).read_text().strip()
    except (FileNotFoundError, PermissionError):
        secret = ''
    secret = secret or os.environ.get('ORIGIN_HMAC_SECRET', '').strip() or os.environ.get('HMAC_SECRET', '').strip()
    if not secret:
        raise RuntimeError('Configure the existing origin HMAC secret before starting.')
    return secret.encode()


def worker_payload(data):
    if not isinstance(data, dict):
        raise ValueError('invalid_request')
    if data.get('type') == 'demo':
        return {'op': 'demo'}
    if data.get('type') == 'observe':
        return {'op': 'observe'}
    if data.get('type') == 'resume':
        ask_id = data.get('ask_id')
        if not isinstance(ask_id, str) or not IDS.fullmatch(ask_id):
            raise ValueError('invalid_ask_id')
        return {'op': 'poll', 'ask_id': ask_id}
    if data.get('type') != 'submit' or data.get('engine') not in ('codex', 'claude'):
        raise ValueError('invalid_request')
    prompt = data.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('empty_prompt')
    if len(prompt.encode()) > 16_384:
        raise ValueError('prompt_too_large')
    return {'op': 'submit', 'engine': data['engine'], 'prompt': prompt}


async def worker_request(payload):
    wire = (json.dumps(payload, ensure_ascii=False) + '\n').encode()
    if len(wire) > 32_768:
        raise ValueError('invalid_request')
    async with asyncio.timeout(5):
        reader, writer = await asyncio.open_unix_connection(SOCKET, limit=65_536)
        try:
            writer.write(wire)
            await writer.drain()
            line = await reader.readline()
            if not line or len(line) > 65_536:
                raise ValueError('invalid_worker_response')
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError('invalid_worker_response')
            return result
        finally:
            writer.close()
            await writer.wait_closed()


async def receive(ws):
    raw = await ws.recv()
    if not isinstance(raw, str):
        raise ValueError('invalid_request')
    return json.loads(raw)


async def event_stream(payload, disconnected=lambda: False):
    """One event model for all transports; demo never touches the private queue."""
    if payload.get('op') == 'observe':
        yield {'type': 'info', 'source': 'conversation', 'delivery': 'readonly_snapshots'}
        async with asyncio.timeout(5):
            reader, writer = await asyncio.open_unix_connection('/run/lib-chat-observer/observer.sock', limit=262144)
        try:
            writer.write(b'{"op":"watch"}\n')
            await writer.drain()
            while not disconnected():
                async with asyncio.timeout(20):
                    line = await reader.readline()
                if not line:
                    raise OSError('Observer disconnected')
                event = json.loads(line)
                if not isinstance(event, dict) or event.get('type') not in ('conversation', 'heartbeat', 'error'):
                    raise ValueError('Invalid observer response')
                yield event
                if event['type'] == 'error':
                    return
        finally:
            writer.close()
            await writer.wait_closed()
        return
    if payload.get('op') == 'demo':
        yield {'type': 'info', 'source': 'demo', 'delivery': 'incremental'}
        yield {'type': 'job', 'source': 'demo', 'ask_status': 'running'}
        for offset in range(0, len(DEMO_TEXT), 12):
            if disconnected():
                return
            yield {'type': 'delta', 'text': DEMO_TEXT[offset:offset + 12]}
            await asyncio.sleep(DEMO_INTERVAL)
        yield {'type': 'job', 'source': 'demo', 'ask_status': 'done', 'reply': DEMO_TEXT}
        return
    yield {'type': 'info', 'source': 'queue', 'delivery': 'final_answer'}
    previous = None
    last_event = time.monotonic()
    async with asyncio.timeout(310):
        while not disconnected():
            result = await worker_request(payload)
            if result != previous:
                yield {'type': 'job', **result}
                previous = result
                last_event = time.monotonic()
            elif time.monotonic() - last_event >= HEARTBEAT_INTERVAL:
                yield {'type': 'heartbeat'}
                last_event = time.monotonic()
            if result.get('ask_status') not in ('pending', 'running'):
                return
            ask_id = result.get('ask_id', '')
            if not isinstance(ask_id, str) or not IDS.fullmatch(ask_id):
                raise ValueError('invalid_worker_response')
            payload = {'op': 'poll', 'ask_id': ask_id}
            await asyncio.sleep(POLL_INTERVAL)


def handler(secret):
    async def handle(ws):
        try:
            nonce = secrets.token_hex(32)
            await ws.send(json.dumps({'type': 'challenge', 'nonce': nonce}))
            async with asyncio.timeout(10):
                auth = await receive(ws)
            expected = hmac.new(secret, f'WS\n{ENDPOINT}\n{nonce}'.encode(), hashlib.sha256).hexdigest()
            signature = auth.get('signature') if isinstance(auth, dict) else None
            demo_only = isinstance(auth, dict) and auth.get('type') == 'demo_auth'
            session_only = isinstance(auth, dict) and auth.get('type') == 'session_auth'
            if session_only and not valid(secret, auth.get('token'), ws.request.headers.get('Origin')):
                await ws.close(1008, 'session_expired')
                return
            if not demo_only and not session_only and (not isinstance(signature, str) or not re.fullmatch(r'[0-9a-f]{64}', signature) or not hmac.compare_digest(expected, signature)):
                await ws.close(1008, 'authentication_failed')
                return
            await ws.send(json.dumps({'type': 'authenticated'}))
            async with asyncio.timeout(30):
                payload = worker_payload(await receive(ws))
            if session_only and payload.get('op') != 'observe':
                await ws.close(1008, 'observation_only')
                return
            if demo_only and payload.get('op') != 'demo':
                await ws.close(1008, 'authentication_required')
                return
            closed = asyncio.create_task(ws.wait_closed())
            try:
                async for event in event_stream(payload, closed.done):
                    await ws.send(json.dumps(event, ensure_ascii=False))
            finally:
                closed.cancel()
        except ConnectionClosed:
            return
        except (ValueError, OSError, TimeoutError) as error:
            # Never expose private exception text or credentials.
            code = 'connection_timeout' if isinstance(error, TimeoutError) else 'invalid_request' if isinstance(error, ValueError) else 'worker_unavailable'
            try:
                await ws.send(json.dumps({'type': 'error', 'error': code}))
                await ws.close(1008, code)
            except ConnectionClosed:
                pass
    return handle


def check_path(connection, request):
    if request.path != ENDPOINT:
        return connection.respond(404, 'Not found\n')


async def main():
    origins = [value.strip() for value in os.environ.get('LIB_CHAT_ORIGINS', '').split(',') if value.strip()]
    if not origins:
        raise RuntimeError('Set LIB_CHAT_ORIGINS to the exact HTTPS page origins.')
    async with serve(handler(load_secret()), '127.0.0.1', int(os.environ.get('LIB_CHAT_PORT', '8091')),
                     origins=origins, process_request=check_path, max_size=32_768,
                     max_queue=4, compression=None, server_header=None) as server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
