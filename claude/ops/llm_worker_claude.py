#!/usr/bin/env python3
"""Claude variant of lib/ops/llm_worker.py for this host (lib/ops/llm_worker.py stays unchanged).

Same socket protocol, queue, job store and bwrap/setpriv sandbox as the original.
Differences for hosts without the production layout:
  - the Claude helper is lib/claude/ops/claude-helper.sh, bound into the sandbox
    at /run/claude-helper (there is no /usr/local/libexec/lib-claude-helper here)
  - the workspace defaults to /root/lib (no /app/lib); /root is replaced by an
    empty tmpfs inside the sandbox and only the workspace is bound read-only,
    so codex-web can reach it without seeing the rest of /root
"""
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
os.environ.setdefault('LIB_LLM_WORKSPACE', str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / 'ops'))  # the original worker stays in lib/ops
import llm_worker

HELPER = os.environ.get('LIB_CLAUDE_HELPER', str(HERE / 'claude-helper.sh'))
SANDBOX_HELPER = '/run/claude-helper'
original_command = llm_worker.command


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


llm_worker.command = command

if __name__ == '__main__':
    llm_worker.main()
