#!/usr/bin/env python3
"""SSE, NDJSON and RFC 7464 streams sharing the WebSocket job event model."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from aiohttp import web
from chat_session import issue, valid, remaining, TTL
from chat_websocket import event_stream, load_secret, worker_payload

PREFIX = '/lib/api/chat/'
TYPES = {'sse': 'text/event-stream', 'ndjson': 'application/x-ndjson', 'jsonseq': 'application/json-seq'}
SESSION_COOKIE = '__Host-conversation-observer'

def session_cookie(token, max_age):
    # Partitioned supports the stream iframe without broad third-party cookies.
    return f'{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; Secure; HttpOnly; SameSite=None; Partitioned'


def encode_event(protocol, event, sequence):
    data = json.dumps(event, ensure_ascii=False)
    if protocol == 'sse':
        return f'id: {sequence}\nevent: {event["type"]}\ndata: {data}\n\n'.encode()
    if protocol == 'jsonseq':
        return ('\x1e' + data + '\n').encode()
    return (data + '\n').encode()


def authenticated(secret, request, body):
    timestamp = request.headers.get('X-Timestamp', '')
    signature = request.headers.get('X-Signature', '')
    if not re.fullmatch(r'[0-9]{1,12}', timestamp) or abs(time.time() - int(timestamp)) > 300:
        return False
    if not re.fullmatch(r'[0-9a-f]{64}', signature):
        return False
    canonical = f'POST\n{request.raw_path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}'
    return hmac.compare_digest(hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest(), signature)


def create_app(secret, origins):
    app = web.Application(client_max_size=32_768)
    active = set()

    async def session(request):
        origin = request.headers.get('Origin') or f'https://{request.host}'
        if origin not in origins or request.query_string:
            return web.json_response({'error': 'origin_rejected'}, status=403)
        if request.method == 'DELETE':
            return web.json_response({'cleared': True}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie('', 0)})
        if request.method == 'GET':
            token = request.cookies.get(SESSION_COOKIE) or request.headers.get('Authorization', '').removeprefix('Bearer ')
            seconds = remaining(secret, token, origin)
            if seconds <= 0:
                return web.json_response({'error': 'session_expired'}, status=401, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie('', 0)})
            return web.json_response({'token': token, 'expires_in': seconds}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie(token, seconds)})
        body = await request.read()
        if not authenticated(secret, request, body):
            return web.json_response({'error': 'authentication_failed'}, status=401)
        if body != b'{"type":"observe"}':
            return web.json_response({'error': 'invalid_request'}, status=400)
        token = issue(secret, origin)
        return web.json_response({'token': token, 'expires_in': TTL}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie(token, TTL)})

    async def stream(request):
        protocol = request.match_info['protocol']
        if protocol not in TYPES or request.query_string:
            raise web.HTTPNotFound()
        if request.headers.get('Origin') not in origins:
            return web.json_response({'error': 'origin_rejected'}, status=403)
        if len(active) >= 32:
            return web.json_response({'error': 'too_many_connections'}, status=429)
        marker = object()
        active.add(marker)
        try:
            body = await request.read()
            try:
                data = json.loads(body)
                payload = worker_payload(data)
            except (ValueError, UnicodeError):
                return web.json_response({'error': 'invalid_request'}, status=400)
            session_ok = payload.get('op') == 'observe' and valid(secret, request.headers.get('Authorization', '').removeprefix('Bearer '), request.headers.get('Origin'))
            if payload.get('op') != 'demo' and not session_ok and not authenticated(secret, request, body):
                return web.json_response({'error': 'authentication_failed'}, status=401)
            response = web.StreamResponse(headers={
                'Content-Type': TYPES[protocol] + '; charset=utf-8',
                'Cache-Control': 'no-store, no-transform', 'X-Accel-Buffering': 'no',
                'X-Content-Type-Options': 'nosniff',
            })
            await response.prepare(request)
            sequence = 0
            def disconnected():
                return request.transport is None or request.transport.is_closing()
            try:
                async for event in event_stream(payload, disconnected):
                    sequence += 1
                    await response.write(encode_event(protocol, event, sequence))
            except (ValueError, OSError, TimeoutError) as error:
                if not disconnected():
                    code = 'connection_timeout' if isinstance(error, TimeoutError) else 'invalid_request' if isinstance(error, ValueError) else 'worker_unavailable'
                    await response.write(encode_event(protocol, {'type': 'error', 'error': code}, sequence + 1))
            await response.write_eof()
            return response
        except (ConnectionError, asyncio.CancelledError):
            # Abort reception only; a submitted CLI job keeps running.
            return web.Response(status=499)
        finally:
            active.discard(marker)

    app.router.add_post(PREFIX + 'session', session)
    app.router.add_get(PREFIX + 'session', session)
    app.router.add_delete(PREFIX + 'session', session)
    app.router.add_post(PREFIX + '{protocol}', stream)
    return app


if __name__ == '__main__':
    origins = {value.strip() for value in os.environ.get('LIB_CHAT_ORIGINS', '').split(',') if value.strip()}
    if not origins:
        raise SystemExit('Set LIB_CHAT_ORIGINS to exact page origins.')
    web.run_app(create_app(load_secret(), origins), host='127.0.0.1',
                port=int(os.environ.get('LIB_CHAT_HTTP_PORT', '8092')),
                access_log=None, handler_cancellation=True)
