#!/usr/bin/env python3
"""Read-only, fixed-thread observer. Never accepts app-server RPC from clients."""
import asyncio
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import socket
import struct
import stat
import re
from websockets.asyncio.client import unix_connect
from websockets.exceptions import ConnectionClosed

SOCKET = '/run/lib-chat-observer/observer.sock'
INTERVAL = 1
SOURCE_FILE = Path('/var/lib/lib-chat-observer/source.json')
READ_METHODS = frozenset({'thread/read', 'thread/turns/list', 'thread/loaded/list'})
TOOL_TYPES = frozenset({'commandExecution', 'webSearch', 'fileChange', 'mcpToolCall', 'dynamicToolCall'})


def public_snapshot(thread, turns):
    messages, activity = [], []
    for turn in reversed(turns):
        for item in turn.get('items', []):
            kind = item.get('type')
            if kind == 'userMessage':
                text = '\n'.join(part.get('text', '') for part in item.get('content', [])
                                 if part.get('type') == 'text' and isinstance(part.get('text'), str))
                role, phase = 'user', None
            elif kind == 'agentMessage':
                text = item.get('text', '')
                role, phase = 'assistant', item.get('phase')
            else:
                if kind in TOOL_TYPES:
                    activity.append({'kind': kind, 'status': str(item.get('status', ''))[:32]})
                continue
            if not isinstance(text, str) or not text:
                continue
            messages.append({'id': str(item.get('id', ''))[:128], 'role': role,
                             'phase': phase, 'text': text[:8192]})
    messages = messages[-40:]
    while sum(len(message['text']) for message in messages) > 49152:
        messages.pop(0)
    return {'type': 'conversation', 'title': str(thread.get('name') or 'この会話')[:120],
            'status': str((thread.get('status') or {}).get('type', 'unknown'))[:32],
            'messages': messages, 'activity': activity[-8:]}


class ReadClient:
    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0

    async def request(self, method, params):
        if method not in READ_METHODS and method != 'initialize':
            raise ValueError('Read-only method required')
        self.sequence += 1
        sequence = self.sequence
        await self.ws.send(json.dumps({'id': sequence, 'method': method, 'params': params}))
        async with asyncio.timeout(10):
            while True:
                result = json.loads(await self.ws.recv())
                if result.get('id') == sequence:
                    if 'error' in result:
                        raise ValueError('App-server read failed')
                    return result['result']


def configured_source(path, thread_id, source_file=None):
    """Only the server's private source file can retarget observation."""
    if source_file is None:
        return path, thread_id
    try:
        fd = os.open(source_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return path, thread_id
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('Source configuration must be private')
        raw = source.read(8193)
    if len(raw) > 8192:
        raise ValueError('Source configuration too large')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Invalid source configuration')
    path, thread_id = data.get('appSocket'), data.get('threadId')
    workspace = data.get('followWorkspace')
    if workspace is not None:
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise ValueError('Invalid workspace')
        thread_id = 'workspace:' + workspace
    if not isinstance(path, str) or not Path(path).is_absolute() or not isinstance(thread_id, str) or not (thread_id.startswith('workspace:/') or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread_id)):
        raise ValueError('Invalid source configuration')
    return path, thread_id


async def snapshots(path, thread_id, source_file=None):
    while True:
        target = configured_source(path, thread_id, source_file)
        async for event in target_snapshots(*target, source_file=source_file, fallback=(path, thread_id)):
            yield event


async def workspace_threads(client, workspace):
    loaded = await client.request('thread/loaded/list', {})
    if loaded.get('nextCursor'):
        raise ValueError('Loaded conversations require pagination')
    candidates = []
    for candidate in loaded.get('data', []):
        info = (await client.request('thread/read', {'threadId': candidate, 'includeTurns': False}))['thread']
        if info.get('cwd') == workspace:
            candidates.append(candidate)
    return candidates


async def target_snapshots(path, thread_id, source_file=None, fallback=None):
    # The upstream connection itself is WebSocket over a root-only Unix socket.
    async with unix_connect(path, uri='ws://localhost', max_size=16_777_216) as ws:
        client = ReadClient(ws)
        await client.request('initialize', {'clientInfo': {'name': 'readonly_chat_observer', 'version': '0.1.0'}})
        await ws.send(json.dumps({'method': 'initialized', 'params': {}}))
        previous = None
        selected = None
        while True:
            if source_file is not None and configured_source(*fallback, source_file) != (path, thread_id):
                return
            current_id = thread_id
            if thread_id.startswith('workspace:'):
                workspace = thread_id.removeprefix('workspace:')
                candidates = await workspace_threads(client, workspace)
                if len(candidates) != 1:
                    yield {'type': 'error', 'error': 'conversation_ambiguous' if candidates else 'conversation_waiting'}
                    await asyncio.sleep(INTERVAL)
                    continue
                current_id = candidates[0]
            if selected != current_id:
                previous = None
                selected = current_id
            thread = (await client.request('thread/read', {'threadId': current_id, 'includeTurns': False}))['thread']
            turns = await client.request('thread/turns/list', {
                'threadId': current_id, 'limit': 10, 'sortDirection': 'desc', 'itemsView': 'full',
            })
            snapshot = public_snapshot(thread, turns.get('data', []))
            if snapshot != previous:
                yield snapshot
                previous = snapshot
            else:
                yield {'type': 'heartbeat'}
            await asyncio.sleep(INTERVAL)


async def handle(reader, writer):
    try:
        peer = writer.get_extra_info('socket')
        _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in (0, pwd.getpwnam('www-data').pw_uid):
            return
        async with asyncio.timeout(5):
            line = await reader.readline()
        if line != b'{"op":"watch"}\n':
            return
        path = os.environ['LIB_CHAT_APP_SOCKET']
        thread_id = os.environ['LIB_CHAT_THREAD_ID']
        # Closing the browser cancels the adapter's Unix connection as well.
        closed = asyncio.create_task(reader.read(1))
        async def send():
            async for event in snapshots(path, thread_id, source_file=SOURCE_FILE):
                writer.write((json.dumps(event, ensure_ascii=False) + '\n').encode())
                await writer.drain()
        stream = asyncio.create_task(send())
        try:
            done, _ = await asyncio.wait((closed, stream), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            closed.cancel()
            stream.cancel()
            await asyncio.gather(closed, stream, return_exceptions=True)
    except (OSError, ValueError, KeyError, TimeoutError, ConnectionClosed):
        try:
            writer.write(b'{"type":"error","error":"observer_unavailable"}\n')
            await writer.drain()
        except OSError:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def main():
    if os.getuid() != 0:
        raise SystemExit('The observer needs root to read the private app-server socket.')
    for key in ('LIB_CHAT_APP_SOCKET', 'LIB_CHAT_THREAD_ID'):
        if not os.environ.get(key):
            raise SystemExit('Set ' + key)
    path = Path(SOCKET)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(path.parent, 0, grp.getgrnam('www-data').gr_gid)
    # Retain the lock for the process lifetime; never unlink a live observer socket.
    lock = open(path.parent / 'observer.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Observer already running')
    path.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle, path=path, limit=4096)
    os.chown(path, 0, grp.getgrnam('www-data').gr_gid)
    path.chmod(0o660)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
