#!/usr/bin/env python3
"""Claude variant of lib/ops/llm_worker.py for this host (lib/ops/llm_worker.py stays unchanged).

Same socket protocol, queue, job store and bwrap/setpriv sandbox as the original.
Differences for hosts without the production layout:
  - the Claude helper is lib/claude/ops/claude-helper.sh, bound into the sandbox
    at /run/claude-helper (there is no /usr/local/libexec/lib-claude-helper here)
  - the workspace defaults to /root/lib (no /app/lib); /root is replaced by an
    empty tmpfs inside the sandbox and only the workspace is bound read-only,
    so codex-web can reach it without seeing the rest of /root
  - muse_prompt goes to muse-vm's OpenAI-compatible API over the tailnet. It runs no CLI
    or tools, so it stays outside the sandbox; the key comes from MUSE_API_KEY
"""
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
os.environ.setdefault('LIB_LLM_WORKSPACE', str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / 'ops'))  # the original worker stays in lib/ops
import llm_worker

HELPER = os.environ.get('LIB_CLAUDE_HELPER', str(HERE / 'claude-helper.sh'))
SANDBOX_HELPER = '/run/claude-helper'
# Removed from the environment so the Codex and Claude runs cannot inherit the key.
MUSE_API_KEY = os.environ.pop('MUSE_API_KEY', '')
MUSE_HOST = os.environ.get('LIB_MUSE_HOST', 'muse-vm')
MUSE_PORT = int(os.environ.get('LIB_MUSE_PORT', '8080'))
MUSE_MODEL = os.environ.get('LIB_MUSE_MODEL', 'muse')
MUSE_MAX_BODY = 1_048_576
# Seconds to wait for muse-vm to answer the reachability probe. `tailscale nc` gives no
# sign of a failed dial, and an unreachable peer held the socket for 127 s (2026-11-12),
# past Cloudflare's 100 s limit, so /neko askgk got HTTP 524 instead of an error code.
MUSE_CONNECT_TIMEOUT = 10
MODEL_NAME = re.compile(r'[a-zA-Z0-9_.:/-]{1,128}')
original_command = llm_worker.command
original_submit = llm_worker.submit
original_execute = llm_worker.execute


def command(engine, answer_path=None):
    args = original_command(engine, answer_path)
    mounts = []
    workspace = llm_worker.WORKSPACE
    if workspace == '/root' or workspace.startswith('/root/'):
        mounts += ['--tmpfs', '/root', '--ro-bind', workspace, workspace]
    if engine == 'claude':
        # /tmp and /run are fresh tmpfs inside bwrap, so mount the helper after them.
        mounts += ['--ro-bind', HELPER, SANDBOX_HELPER]
        args[-1] = SANDBOX_HELPER
    at = args.index('/usr/bin/setpriv')
    args[at:at] = mounts
    return args


class MuseError(Exception):
    pass


class TailnetConnection(http.client.HTTPConnection):
    """tailscaled uses userspace networking here, so `tailscale nc` carries the socket."""
    nc = None

    def connect(self):
        self.sock, remote = socket.socketpair()
        self.sock.settimeout(self.timeout)
        with remote:
            self.nc = subprocess.Popen(['tailscale', 'nc', self.host, str(self.port)],
                                       stdin=remote, stdout=remote, stderr=subprocess.DEVNULL)

    def close(self):
        super().close()
        if self.nc:
            self.nc.kill()
            self.nc.wait()
            self.nc = None


def probe_muse():
    """Fail fast unless muse-vm answers over the tailnet. Any HTTP status shows it is reachable."""
    conn = TailnetConnection(MUSE_HOST, MUSE_PORT, timeout=MUSE_CONNECT_TIMEOUT)
    try:
        conn.request('GET', '/v1/models', headers={'Authorization': 'Bearer ' + MUSE_API_KEY})
        conn.getresponse().read(MUSE_MAX_BODY)
    except (http.client.HTTPException, OSError) as error:
        raise MuseError('muse_connection_failed') from error
    finally:
        conn.close()


def ask_muse(prompt):
    probe_muse()
    conn = TailnetConnection(MUSE_HOST, MUSE_PORT, timeout=llm_worker.TIMEOUT)
    body = json.dumps({'model': MUSE_MODEL, 'messages': [{'role': 'user', 'content': prompt}]})
    try:
        conn.request('POST', '/v1/chat/completions', body, {
            'Authorization': 'Bearer ' + MUSE_API_KEY, 'Content-Type': 'application/json'})
        response = conn.getresponse()
        status, payload = response.status, response.read(MUSE_MAX_BODY + 1)
    except (http.client.HTTPException, ConnectionError) as error:
        raise MuseError('muse_connection_failed') from error
    finally:
        conn.close()
    if status in (401, 403):
        raise MuseError('muse_authentication_failed')
    if status == 429:
        raise MuseError('muse_usage_limit')
    if status != 200 or len(payload) > MUSE_MAX_BODY:
        raise MuseError('muse_execution_failed')
    try:
        data = json.loads(payload)
        reply = data['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise MuseError('muse_execution_failed') from error
    if not isinstance(reply, str) or not reply.strip():
        raise MuseError('muse_execution_failed')
    model = data.get('model')
    return reply.strip(), model if isinstance(model, str) and MODEL_NAME.fullmatch(model) else MUSE_MODEL


def submit(engine, prompt):
    if engine != 'muse':
        return original_submit(engine, prompt)
    if not isinstance(prompt, str) or not prompt.strip():
        return {'ask_error': 'empty_prompt', 'ask_status': 'failed'}
    if len(prompt.encode()) > llm_worker.MAX_PROMPT:
        return {'ask_error': 'prompt_too_large', 'ask_status': 'failed'}
    if not MUSE_API_KEY:
        return {'ask_error': 'muse_not_authenticated', 'ask_status': 'failed', 'via': engine}
    job = {'ask_id': 'muse-' + str(uuid.uuid4()), 'ask_status': 'pending',
           'via': engine, 'created_at': time.time()}
    with llm_worker.LOCK:
        if llm_worker.JOBS.full():
            return {'ask_error': 'queue_full', 'ask_status': 'failed'}
        llm_worker.save(job)
        llm_worker.JOBS.put_nowait((job, prompt))
    return job


def execute(job, prompt):
    if job['via'] != 'muse':
        original_execute(job, prompt)
        return
    job.update(ask_status='running', started_at=time.time())
    llm_worker.save(job)
    try:
        reply, model = ask_muse(prompt)
        job.update(ask_status='done', model=model, llm_model=model,
                   reply=reply.encode()[:llm_worker.MAX_OUTPUT].decode('utf-8', errors='ignore'))
    except MuseError as error:
        job.update(ask_status='failed', ask_error=str(error))
    except TimeoutError:
        job.update(ask_status='failed', ask_error='llm_timeout')
    except OSError:
        job.update(ask_status='failed', ask_error='muse_connection_failed')
    job['finished_at'] = time.time()
    llm_worker.save(job)
    llm_worker.log_event({'ask_id': job['ask_id'], 'status': job['ask_status']})


llm_worker.IDS = re.compile(r'^(codex|claude|muse)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
llm_worker.command = command
llm_worker.submit = submit
llm_worker.execute = execute

if __name__ == '__main__':
    llm_worker.main()
