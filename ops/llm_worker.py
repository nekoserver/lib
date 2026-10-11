#!/usr/bin/python3
"""Private Unix-socket queue; fixed CLI invocations inside a read-only mount namespace."""
import grp
import json
import os
from pathlib import Path
import pwd
import queue
import re
import signal
import socket
import socketserver
import struct
import subprocess
import threading
import time
import uuid

SOCKET = os.environ.get('LIB_CODEX_SOCKET', '/run/lib-codex/worker.sock')
STATE = Path(os.environ.get('LIB_LLM_STATE', '/var/lib/lib-llm/jobs'))
WORKSPACE = os.environ.get('LIB_LLM_WORKSPACE', '/app/lib')
HOME = '/var/lib/codex-web'
MAX_PROMPT = 16_384
MAX_OUTPUT = 32_768
TTL = 86_400
TIMEOUT = 300
IDS = re.compile(r'^(codex|claude)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
JOBS = queue.Queue(maxsize=8)
LOCK = threading.Lock()


def save(job):
    path = STATE / (job['ask_id'] + '.json')
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(job, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def lookup(ask_id):
    if not IDS.fullmatch(ask_id):
        return {'ask_error': 'invalid_ask_id', 'ask_status': 'failed'}
    path = STATE / (ask_id + '.json')
    try:
        if time.time() - path.stat().st_mtime > TTL:
            return {'ask_error': 'expired_ask_id', 'ask_status': 'failed'}
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {'ask_error': 'unknown_ask_id', 'ask_status': 'failed'}


def claude_authenticated():
    return any(Path(p).is_file() for p in (
        HOME + '/.claude/.credentials.json',
        HOME + '/.claude-api-key',
        HOME + '/.claude-oauth-token',
    ))


def submit(engine, prompt):
    if engine not in ('codex', 'claude'):
        return {'ask_error': 'unsupported_engine', 'ask_status': 'failed'}
    if not isinstance(prompt, str) or not prompt.strip():
        return {'ask_error': 'empty_prompt', 'ask_status': 'failed'}
    if len(prompt.encode()) > MAX_PROMPT:
        return {'ask_error': 'prompt_too_large', 'ask_status': 'failed'}
    if engine == 'claude' and not claude_authenticated():
        return {'ask_error': 'claude_not_authenticated', 'ask_status': 'failed', 'via': engine}
    job = {'ask_id': engine + '-' + str(uuid.uuid4()), 'ask_status': 'pending',
           'via': engine, 'created_at': time.time()}
    with LOCK:
        if JOBS.full():
            return {'ask_error': 'queue_full', 'ask_status': 'failed'}
        save(job)
        JOBS.put_nowait((job, prompt))
    return job


def command(engine):
    user = pwd.getpwnam('codex-web')
    # root creates the namespace; the CLI and its tools run as codex-web.
    # Only the dedicated CLI home and temporary files are writable.
    args = ['/usr/bin/bwrap', '--ro-bind', '/', '/', '--bind', HOME, HOME,
            '--tmpfs', '/tmp', '--chmod', '1777', '/tmp',
            '--tmpfs', '/run', '--proc', '/proc', '--dev', '/dev',
            '--unshare-pid', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
            '--cap-add', 'CAP_SETUID', '--cap-add', 'CAP_SETGID', '--chdir', WORKSPACE,
            '--setenv', 'HOME', HOME, '--setenv', 'CODEX_HOME', HOME + '/.codex',
            '--setenv', 'PATH', '/opt/rbenv/versions/4.0.7/bin:/usr/local/bin:/usr/bin:/bin',
            '/usr/bin/setpriv', '--reuid', str(user.pw_uid), '--regid', str(user.pw_gid),
            '--clear-groups', '--no-new-privs']
    if engine == 'codex':
        args += ['/opt/codex-web/bin/codex', '-a', 'never', 'exec',
                 '--ignore-user-config', '--ignore-rules', '--ephemeral',
                 '--sandbox', 'danger-full-access', '--json', '--color', 'never',
                 '--skip-git-repo-check', '-']
    else:
        args += ['/usr/local/libexec/lib-claude-helper']
    return args


def run_bounded(args, prompt):
    # RLIMIT_FSIZE affects every file written by the CLI and its tools, including
    # databases and runtime artifacts. Bound only the captured output instead.
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    chunks = []
    overflow = threading.Event()

    def collect():
        size = 0
        while True:
            chunk = proc.stdout.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > 4_194_304:
                overflow.set()
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            chunks.append(chunk)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        try:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise TimeoutError
    finally:
        reader.join(timeout=2)
        proc.stdout.close()
    if overflow.is_set():
        raise OverflowError
    return proc.returncode, b''.join(chunks).decode('utf-8', errors='replace')


def failure_code(text, engine):
    """Return fixed diagnostic labels; never expose CLI text or credentials."""
    text = text.lower()
    if any(value in text for value in ('hit your usage limit', 'usage_limit_reached', 'insufficient_quota', 'rate_limit_exceeded')):
        return engine + '_usage_limit'
    if any(value in text for value in ('unauthorized', 'authentication', '401', 'token expired')):
        return engine + '_authentication_failed'
    if any(value in text for value in ('connection', 'reconnecting', 'network', 'stream disconnected')):
        return engine + '_connection_failed'
    if any(value in text for value in ('permission denied', 'read-only file system', 'operation not permitted')):
        return engine + '_permission_denied'
    return engine + '_execution_failed'


def save_failure_diagnostic(job, returncode, errors):
    directory = STATE.parent / 'diagnostics'
    directory.mkdir(mode=0o700, exist_ok=True)
    for old in directory.glob('*.json'):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink()
    path = directory / (job['ask_id'] + '.json')
    # Only CLI error events, never prompts, tool output, or final answers.
    record = {'exit_code': returncode, 'errors': errors[-8:]}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(record, output, ensure_ascii=False)


def execute(job, prompt):
    job.update(ask_status='running', started_at=time.time())
    save(job)
    try:
        # The prompt is stdin, never a shell command or CLI option.
        returncode, text = run_bounded(command(job['via']), prompt)
        reply = None
        error = None
        diagnostic = ''
        errors = []
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if job['via'] == 'codex':
                item = event.get('item') or {}
                if item.get('type') == 'agent_message':
                    reply = item.get('text')
                if event.get('type') in ('error', 'turn.failed'):
                    diagnostic = json.dumps(event.get('error', event.get('message', {})))
                    errors.append({'type': event['type'], 'detail': diagnostic[:4096]})
                # An error event can be a recoverable reconnect. Only a terminal
                # turn failure overrides a successful exit and final answer.
                if event.get('type') == 'turn.failed':
                    error = failure_code(json.dumps(event.get('error', {})), 'codex')
            elif event.get('type') == 'result':
                reply = event.get('result')
                if event.get('is_error'):
                    error = 'claude_execution_failed'
        if returncode != 0 or error or not reply:
            job.update(ask_status='failed', ask_error=error or failure_code(diagnostic, job['via']))
            save_failure_diagnostic(job, returncode, errors)
        else:
            job.update(ask_status='done', reply=reply.encode()[:MAX_OUTPUT].decode('utf-8', errors='ignore'))
    except TimeoutError:
        job.update(ask_status='failed', ask_error='llm_timeout')
    except OverflowError:
        job.update(ask_status='failed', ask_error='llm_output_limit')
    except (OSError, ValueError):
        job.update(ask_status='failed', ask_error='llm_helper_failed')
    job['finished_at'] = time.time()
    save(job)
    print(json.dumps({'ask_id': job['ask_id'], 'status': job['ask_status']}), flush=True)


def consume():
    while True:
        job, prompt = JOBS.get()
        execute(job, prompt)
        JOBS.task_done()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in (0, pwd.getpwnam('www-data').pw_uid):
            return
        try:
            line = self.rfile.readline(32_769)
            if len(line) > 32_768:
                raise ValueError
            req = json.loads(line)
            if req.get('op') == 'submit':
                result = submit(req.get('engine'), req.get('prompt'))
            elif req.get('op') == 'poll':
                result = lookup(str(req.get('ask_id', '')))
            else:
                result = {'ask_error': 'invalid_operation'}
        except (ValueError, OSError):
            result = {'ask_error': 'invalid_request'}
        self.wfile.write((json.dumps(result, ensure_ascii=False) + '\n').encode())


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    if os.getuid() != 0:
        raise SystemExit('Run worker as root; helpers drop to codex-web in a read-only namespace.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in STATE.glob('*.json'):
        if time.time() - path.stat().st_mtime > TTL:
            path.unlink()
            continue
        job = json.loads(path.read_text())
        if job.get('ask_status') in ('pending', 'running'):
            job.update(ask_status='failed', ask_error='worker_restarted')
            save(job)
    path = Path(SOCKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(SOCKET)
            raise SystemExit('Worker already running')
        except ConnectionRefusedError:
            path.unlink()
        finally:
            probe.close()
    server = Server(SOCKET, Handler)
    os.chown(SOCKET, 0, grp.getgrnam('www-data').gr_gid)
    os.chmod(SOCKET, 0o660)
    threading.Thread(target=consume, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
