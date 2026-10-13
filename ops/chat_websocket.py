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
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ENDPOINT = '/lib/api/chat/ws'
SOCKET = os.environ.get('LIB_CODEX_SOCKET', '/run/lib-codex/worker.sock')
IDS = re.compile(r'^(codex|claude)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
POLL_INTERVAL = 0.5


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


def handler(secret):
    async def handle(ws):
        try:
            nonce = secrets.token_hex(32)
            await ws.send(json.dumps({'type': 'challenge', 'nonce': nonce}))
            async with asyncio.timeout(10):
                auth = await receive(ws)
            expected = hmac.new(secret, f'WS\n{ENDPOINT}\n{nonce}'.encode(), hashlib.sha256).hexdigest()
            signature = auth.get('signature') if isinstance(auth, dict) else None
            if not isinstance(signature, str) or not re.fullmatch(r'[0-9a-f]{64}', signature) or not hmac.compare_digest(expected, signature):
                await ws.close(1008, 'authentication_failed')
                return
            await ws.send(json.dumps({'type': 'authenticated'}))
            async with asyncio.timeout(30):
                payload = worker_payload(await receive(ws))
            previous = None
            async with asyncio.timeout(310):
                while True:
                    result = await worker_request(payload)
                    if result != previous:
                        await ws.send(json.dumps({'type': 'job', **result}, ensure_ascii=False))
                        previous = result
                    if result.get('ask_status') not in ('pending', 'running'):
                        break
                    ask_id = result.get('ask_id', '')
                    if not isinstance(ask_id, str) or not IDS.fullmatch(ask_id):
                        raise ValueError('invalid_worker_response')
                    payload = {'op': 'poll', 'ask_id': ask_id}
                    # Disconnect stops watching, without resubmitting or cancelling a job.
                    try:
                        await asyncio.wait_for(ws.wait_closed(), timeout=POLL_INTERVAL)
                        return
                    except TimeoutError:
                        pass
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
