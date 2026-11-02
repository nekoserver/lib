#!/usr/bin/env python3
"""Claude Code variant of chat_observer.py: same Unix-socket protocol, Claude session transcript as the source.

The Codex observer reads a Codex app-server; this one tails a Claude Code
session JSONL (~/.claude/projects/<slug>/<session>.jsonl) and emits the same
public snapshot shape, so chat_http_stream.py / chat_websocket.py work unchanged.
Input ("send") resumes the session non-interactively with `claude -p --resume`.
"""
import asyncio
import fcntl
import grp
import json
import os
from pathlib import Path
import sys
import pwd
import re
import socket
import stat
import struct
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))  # shared helpers stay in lib/ops
from spec_eval import configured_evaluations

SOCKET = os.environ.get('LIB_CHAT_OBSERVER_SOCKET', '/run/lib-chat-observer/observer.sock')
INTERVAL = 1
SOURCE_FILE = Path('/var/lib/lib-chat-observer/claude-source.json')
PROJECTS = Path(os.environ.get('LIB_CHAT_CLAUDE_PROJECTS', '/root/.claude/projects'))
CLAUDE_CANDIDATES = (
    os.environ.get('LIB_CHAT_CLAUDE_BIN', ''),
    '/opt/claude-web/claude',
    # Same fallback as claude-helper.sh: the /opt/node22/bin/claude launcher is a stub on this host.
    '/opt/node22/lib/node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai/claude-code-linux-x64/claude',
)
TAIL_BYTES = 4_194_304
SESSION_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
TOOL_KINDS = {'Bash': 'commandExecution', 'WebSearch': 'webSearch', 'WebFetch': 'webSearch',
              'Edit': 'fileChange', 'Write': 'fileChange', 'NotebookEdit': 'fileChange'}


def claude_binary(candidates=CLAUDE_CANDIDATES):
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return 'claude'


def tool_kind(name):
    if name.startswith('mcp__'):
        return 'mcpToolCall'
    return TOOL_KINDS.get(name, 'dynamicToolCall')


def user_text(entry):
    """Human-typed text only; tool results, meta and harness tags are excluded."""
    if entry.get('isMeta') or entry.get('toolUseResult') is not None:
        return None
    content = (entry.get('message') or {}).get('content')
    if isinstance(content, list):
        if any(isinstance(part, dict) and part.get('type') == 'tool_result' for part in content):
            return None
        content = '\n'.join(part.get('text', '') for part in content
                            if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str))
    if not isinstance(content, str) or content.lstrip().startswith('<'):
        return None
    return content


def public_snapshot(entries):
    messages, activity, tools = [], [], {}
    title, status = 'この会話', 'idle'
    for entry in entries:
        kind = entry.get('type')
        if kind == 'ai-title' and isinstance(entry.get('aiTitle'), str):
            title = entry['aiTitle']
            continue
        if entry.get('isSidechain'):
            continue
        if kind == 'system' and entry.get('subtype') == 'turn_duration':
            status = 'idle'
            continue
        message = entry.get('message') or {}
        content = message.get('content')
        if kind == 'user':
            status = 'active'
            for part in content if isinstance(content, list) else []:
                if isinstance(part, dict) and part.get('type') == 'tool_result' and part.get('tool_use_id') in tools:
                    tools[part['tool_use_id']]['status'] = 'failed' if part.get('is_error') else 'completed'
            text = user_text(entry)
            if text:
                messages.append({'id': str(entry.get('uuid', ''))[:128], 'role': 'user', 'phase': None, 'text': text[:8192]})
        elif kind == 'assistant' and isinstance(content, list):
            final = message.get('stop_reason') == 'end_turn'
            # `claude -p` writes no turn_duration, so the final answer also ends the turn.
            status = 'idle' if final else 'active'
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get('type') == 'tool_use':
                    item = {'kind': tool_kind(str(part.get('name', ''))), 'status': 'inProgress'}
                    tools[part.get('id')] = item
                    activity.append(item)
                elif part.get('type') == 'text' and isinstance(part.get('text'), str) and part['text']:
                    messages.append({'id': str(entry.get('uuid', ''))[:128], 'role': 'assistant',
                                     'phase': None if final else 'commentary', 'text': part['text'][:8192]})
    messages = messages[-40:]
    while sum(len(message['text']) for message in messages) > 49152:
        messages.pop(0)
    return {'type': 'conversation', 'title': title[:120], 'status': status,
            'messages': messages, 'activity': [dict(item) for item in activity[-8:]]}


def read_entries(path):
    with open(path, 'rb') as transcript:
        size = transcript.seek(0, os.SEEK_END)
        transcript.seek(max(0, size - TAIL_BYTES))
        raw = transcript.read()
    lines = raw.split(b'\n')
    if size > TAIL_BYTES:
        lines = lines[1:]
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def session_file(session_id):
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError('Invalid session')
    found = sorted(PROJECTS.glob(f'*/{session_id}.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def workspace_session(workspace):
    project = PROJECTS / re.sub(r'[^A-Za-z0-9]', '-', workspace)
    found = sorted(project.glob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0].stem if found else None


def configured_source(session_id, source_file=None):
    """Only the server's private source file can retarget observation."""
    if source_file is None:
        return session_id
    try:
        fd = os.open(source_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return session_id
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
    session_id, workspace = data.get('sessionId'), data.get('followWorkspace')
    if workspace is not None:
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise ValueError('Invalid workspace')
        return 'workspace:' + workspace
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise ValueError('Invalid source configuration')
    return session_id


def resolve(target):
    if target.startswith('workspace:'):
        return workspace_session(target.removeprefix('workspace:'))
    return target


async def snapshots(session_id, source_file=None):
    previous, selected, seen = None, None, None
    while True:
        current = resolve(configured_source(session_id, source_file))
        path = session_file(current) if current else None
        if path is None:
            yield {'type': 'error', 'error': 'conversation_waiting'}
            await asyncio.sleep(INTERVAL)
            continue
        if selected != current:
            previous, selected, seen = None, current, None
        info = path.stat()
        if (info.st_size, info.st_mtime_ns) != seen:
            seen = (info.st_size, info.st_mtime_ns)
            snapshot = await asyncio.to_thread(lambda: public_snapshot(read_entries(path)))
        else:
            snapshot = previous
        if snapshot != previous:
            yield snapshot
            previous = snapshot
        else:
            yield {'type': 'heartbeat'}
        await asyncio.sleep(INTERVAL)


def session_cwd(path):
    for entry in reversed(read_entries(path)):
        cwd = entry.get('cwd')
        if isinstance(cwd, str) and Path(cwd).is_dir():
            return cwd
    return None


async def send_to_console(session_id, text):
    if session_id.startswith('workspace:') or not SESSION_ID.fullmatch(session_id):
        raise ValueError('A fixed conversation is required')
    path = session_file(session_id)
    if path is None:
        raise ValueError('Unknown session')
    # Claude resolves --resume per project directory, so run from the session's cwd.
    # '--' ends option parsing: text such as '--version' must stay a prompt.
    process = await asyncio.create_subprocess_exec(
        claude_binary(), '-p', '--resume', session_id, '--', text, cwd=session_cwd(path),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    # Accepted once the turn is running; an immediate exit means the resume was rejected.
    try:
        async with asyncio.timeout(2):
            code = await process.wait()
    except TimeoutError:
        return
    if code != 0:
        raise ValueError('Claude rejected console input')


async def console_connected(session_id):
    return SESSION_ID.fullmatch(session_id) is not None and session_file(session_id) is not None


async def spec_evaluation(operation):
    if set(operation) != {'op', 'action', 'repository', 'path'} or operation['action'] not in ('inspect', 'create'):
        raise ValueError('invalid_evaluation_request')
    service = configured_evaluations()
    repository, spec = operation['repository'], operation['path']
    result = await service.inspect(repository, spec)
    session_id = resolve(configured_source(os.environ['LIB_CHAT_CLAUDE_SESSION'], SOURCE_FILE)) or ''
    connected = await console_connected(session_id)
    if operation['action'] == 'create':
        if not connected: raise ValueError('console_unavailable')
        async def send(prompt):
            if resolve(configured_source(os.environ['LIB_CHAT_CLAUDE_SESSION'], SOURCE_FILE)) != session_id:
                raise ValueError('console_target_changed')
            await send_to_console(session_id, prompt)
        result = await service.create(repository, spec, send, thread_id=session_id)
    return {**result, 'connected': connected}


async def handle(reader, writer):
    try:
        peer = writer.get_extra_info('socket')
        _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in (0, pwd.getpwnam('www-data').pw_uid):
            return
        async with asyncio.timeout(5):
            line = await reader.readline()
        try:
            operation = json.loads(line)
        except (ValueError, UnicodeError):
            return
        if isinstance(operation, dict) and operation.get('op') == 'spec-eval':
            try:
                async with asyncio.timeout(18): result = await spec_evaluation(operation)
                writer.write((json.dumps(result, ensure_ascii=False) + '\n').encode())
            except (OSError, ValueError, KeyError, TimeoutError):
                writer.write(b'{"error":"evaluation_unavailable","connected":false}\n')
            await writer.drain()
            return
        if isinstance(operation, dict) and set(operation) == {'op', 'text'} and operation.get('op') == 'send' and isinstance(operation.get('text'), str):
            text = operation['text']
            if not text.strip() or len(text.encode()) > 16_384:
                writer.write(b'{"type":"error","error":"invalid_prompt"}\n')
                await writer.drain()
                return
            try:
                session_id = resolve(configured_source(os.environ['LIB_CHAT_CLAUDE_SESSION'], SOURCE_FILE)) or ''
                async with asyncio.timeout(15):
                    await send_to_console(session_id, text)
                writer.write(b'{"type":"accepted"}\n')
            except (OSError, ValueError, TimeoutError):
                writer.write(b'{"type":"error","error":"console_unavailable"}\n')
            await writer.drain()
            return
        if operation != {'op': 'watch'}:
            return
        session_id = os.environ['LIB_CHAT_CLAUDE_SESSION']
        # Closing the browser cancels the adapter's Unix connection as well.
        closed = asyncio.create_task(reader.read(1))
        async def send():
            async for event in snapshots(session_id, source_file=SOURCE_FILE):
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
    except (OSError, ValueError, KeyError, TimeoutError):
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
        raise SystemExit('The observer needs root to read the private Claude transcripts.')
    if not os.environ.get('LIB_CHAT_CLAUDE_SESSION'):
        raise SystemExit('Set LIB_CHAT_CLAUDE_SESSION (a session id, or workspace:/abs/path)')
    path = Path(SOCKET)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(path.parent, 0, grp.getgrnam('www-data').gr_gid)
    path.parent.chmod(0o750)
    # Retain the lock for the process lifetime; never unlink a live observer socket.
    lock = open(path.parent / 'observer.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Observer already running')
    path.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle, path=path, limit=32_768)
    os.chown(path, 0, grp.getgrnam('www-data').gr_gid)
    path.chmod(0o660)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
