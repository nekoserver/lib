#!/usr/bin/env python3
"""SSE, NDJSON and RFC 7464 streams sharing the WebSocket job event model."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from aiohttp import web
from chat_session import issue, valid, remaining, TTL, CONSOLE_TTL_OPTIONS
from chat_websocket import event_stream, load_secret, worker_payload
from chat_site import register_site

PREFIX = '/lib/api/chat/'
TYPES = {'sse': 'text/event-stream', 'ndjson': 'application/x-ndjson', 'jsonseq': 'application/json-seq'}
SESSION_COOKIE = '__Host-conversation-observer'
CONSOLE_COOKIE = '__Host-conversation-console'

def session_cookie(token, max_age, console=False):
    # Partitioned supports the stream iframe without broad third-party cookies.
    name = CONSOLE_COOKIE if console else SESSION_COOKIE
    return f'{name}={token}; Path=/; Max-Age={max_age}; Secure; HttpOnly; SameSite=None; Partitioned'


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


def create_app(secret, origins, *, frame_origins=None):
    app = web.Application(client_max_size=32_768)
    active = set()
    console_sessions = {}
    asset_tickets = {}

    def issue_asset_ticket():
        now = time.monotonic()
        for old, expires in list(asset_tickets.items()):
            if expires <= now:
                asset_tickets.pop(old, None)
        if len(asset_tickets) >= 1024:
            asset_tickets.pop(next(iter(asset_tickets)))
        ticket = secrets.token_urlsafe(24)
        asset_tickets[ticket] = now + 120
        return ticket

    def valid_asset_ticket(ticket):
        return isinstance(ticket, str) and asset_tickets.get(ticket, 0) > time.monotonic()

    def console_token(request):
        return request.headers.get('Authorization', '').removeprefix('Bearer ') or request.cookies.get(CONSOLE_COOKIE)

    def prune_console_sessions():
        now = int(time.time())
        for old_token, expires in list(console_sessions.items()):
            if expires <= now:
                console_sessions.pop(old_token, None)

    def console_remaining(token, origin):
        prune_console_sessions()
        if token not in console_sessions:
            return 0
        return remaining(secret, token, origin, 'console')

    async def session(request, console=False):
        origin = request.headers.get('Origin') or f'https://{request.host}'
        if origin not in origins or request.query_string:
            return web.json_response({'error': 'origin_rejected'}, status=403)
        if request.method == 'DELETE':
            if console:
                console_sessions.pop(console_token(request), None)
            return web.json_response({'cleared': True}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie('', 0, console)})
        if request.method == 'GET':
            token = request.cookies.get(CONSOLE_COOKIE if console else SESSION_COOKIE)
            if console:
                token = request.headers.get('Authorization', '').removeprefix('Bearer ') or token
            else:
                token = token or request.headers.get('Authorization', '').removeprefix('Bearer ')
            seconds = console_remaining(token, origin) if console else remaining(secret, token, origin)
            if seconds <= 0:
                if console:
                    return web.json_response({'enabled': False}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie('', 0, True)})
                return web.json_response({'error': 'session_expired'}, status=401, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie('', 0)})
            if console:
                return web.json_response({'enabled': True, 'expires_in': seconds, 'token': token}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie(token, seconds, True)})
            return web.json_response({'token': token, 'expires_in': seconds, 'asset_ticket': issue_asset_ticket()}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie(token, seconds)})
        body = await request.read()
        if not authenticated(secret, request, body):
            return web.json_response({'error': 'authentication_failed'}, status=401)
        ttl = TTL
        if console:
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError):
                return web.json_response({'error': 'invalid_request'}, status=400)
            ttl = data.get('ttl_seconds') if isinstance(data, dict) and set(data) == {'type', 'ttl_seconds'} and data.get('type') == 'console' else None
            if type(ttl) is not int or ttl not in CONSOLE_TTL_OPTIONS:
                return web.json_response({'error': 'invalid_request'}, status=400)
        elif body != b'{"type":"observe"}':
            return web.json_response({'error': 'invalid_request'}, status=400)
        token = issue(secret, origin, 'console' if console else 'observe', ttl)
        if console:
            prune_console_sessions()
            console_sessions[token] = int(time.time()) + ttl
            return web.json_response({'enabled': True, 'expires_in': ttl, 'token': token}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie(token, ttl, True)})
        return web.json_response({'token': token, 'expires_in': TTL, 'asset_ticket': issue_asset_ticket()}, headers={'Cache-Control': 'no-store', 'Set-Cookie': session_cookie(token, TTL)})

    async def send_to_console(request):
        origin = request.headers.get('Origin') or f'https://{request.host}'
        if origin not in origins or request.query_string:
            return web.json_response({'error': 'origin_rejected'}, status=403)
        body = await request.read()
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            return web.json_response({'error': 'invalid_request'}, status=400)
        prompt = data.get('prompt') if isinstance(data, dict) and set(data) == {'prompt'} else None
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 16_384:
            return web.json_response({'error': 'invalid_prompt'}, status=400)
        token = console_token(request)
        if token not in console_sessions or not valid(secret, token, origin, 'console'):
            return web.json_response({'error': 'console_session_required'}, status=401, headers={'Cache-Control': 'no-store'})
        try:
            async with asyncio.timeout(20):
                reader, writer = await asyncio.open_unix_connection('/run/lib-chat-observer/observer.sock', limit=262144)
                try:
                    writer.write((json.dumps({'op': 'send', 'text': prompt}, ensure_ascii=False) + '\n').encode())
                    await writer.drain()
                    line = await reader.readline()
                    if not line:
                        raise OSError('Observer disconnected')
                    result = json.loads(line)
                finally:
                    writer.close()
                    await writer.wait_closed()
        except (OSError, TimeoutError, ValueError):
            return web.json_response({'error': 'console_unavailable'}, status=503, headers={'Cache-Control': 'no-store'})
        if isinstance(result, dict) and result.get('error') == 'console_in_use':
            return web.json_response({'error': 'console_in_use'}, status=409, headers={'Cache-Control': 'no-store'})
        if not isinstance(result, dict) or result.get('type') != 'accepted':
            return web.json_response({'error': 'console_unavailable'}, status=503, headers={'Cache-Control': 'no-store'})
        return web.json_response({'accepted': True}, headers={'Cache-Control': 'no-store'})

    async def spec_evaluation(request):
        origin = request.headers.get('Origin') or f'https://{request.host}'
        if origin not in origins or request.query_string:
            return web.json_response({'error': 'origin_rejected'}, status=403)
        try: data = await request.json()
        except (ValueError, UnicodeError): return web.json_response({'error': 'invalid_request'}, status=400)
        if not isinstance(data, dict) or set(data) != {'action', 'repository', 'path'} or data['action'] not in ('inspect', 'create') or not all(isinstance(data[key], str) and 0 < len(data[key]) <= 512 for key in ('repository', 'path')):
            return web.json_response({'error': 'invalid_request'}, status=400)
        if data['action'] == 'create':
            if console_remaining(console_token(request), origin) <= 0:
                return web.json_response({'error': 'console_session_required'}, status=401)
        else:
            token = request.cookies.get(SESSION_COOKIE) or request.headers.get('Authorization', '').removeprefix('Bearer ')
            if not valid(secret, token, origin): return web.json_response({'error': 'session_expired'}, status=401)
        try:
            async with asyncio.timeout(20):
                reader, writer = await asyncio.open_unix_connection('/run/lib-chat-observer/observer.sock', limit=4_194_304)
                try:
                    writer.write((json.dumps({'op': 'spec-eval', **data}, ensure_ascii=False) + '\n').encode())
                    await writer.drain()
                    result = json.loads(await reader.readline())
                finally:
                    writer.close()
                    await writer.wait_closed()
            if not isinstance(result, dict) or result.get('error'):
                return web.json_response({'error': 'evaluation_unavailable'}, status=503)
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (OSError, ValueError, TimeoutError):
            return web.json_response({'error': 'evaluation_unavailable'}, status=503)

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
    app.router.add_post(PREFIX + 'console-session', lambda request: session(request, console=True))
    app.router.add_get(PREFIX + 'console-session', lambda request: session(request, console=True))
    app.router.add_delete(PREFIX + 'console-session', lambda request: session(request, console=True))
    app.router.add_post(PREFIX + 'console', send_to_console)
    app.router.add_post(PREFIX + 'spec-eval', spec_evaluation)
    app.router.add_post(PREFIX + '{protocol}', stream)
    register_site(app, secret, origins, frame_origins=frame_origins, valid_asset_ticket=valid_asset_ticket)
    return app


if __name__ == '__main__':
    origins = {value.strip() for value in os.environ.get('LIB_CHAT_ORIGINS', '').split(',') if value.strip()}
    if not origins:
        raise SystemExit('Set LIB_CHAT_ORIGINS to exact page origins.')
    frame_origins = {value.strip() for value in os.environ.get('LIB_CHAT_FRAME_ORIGINS', '').split(',') if value.strip()} or origins
    web.run_app(create_app(load_secret(), origins, frame_origins=frame_origins), host='127.0.0.1',
                port=int(os.environ.get('LIB_CHAT_HTTP_PORT', '8092')),
                access_log=None, handler_cancellation=True)
