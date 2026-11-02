import importlib.util
from pathlib import Path
import pwd
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('llm_worker_claude', Path(__file__).parents[1] / 'ops/llm_worker_claude.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
CODEX_WEB = pwd.struct_passwd(('codex-web', 'x', 994, 994, '', '/var/lib/codex-web', '/bin/sh'))


def build(engine, workspace):
    with patch.object(worker.llm_worker, 'WORKSPACE', workspace), \
         patch.object(worker.llm_worker.pwd, 'getpwnam', return_value=CODEX_WEB):
        return worker.command(engine)


def mounts(args):
    """bwrap options before the privilege drop, as (option, *operands) tuples."""
    head = args[:args.index('/usr/bin/setpriv')]
    found, index = [], 1
    while index < len(head):
        option = head[index]
        width = 3 if option in ('--ro-bind', '--bind', '--chmod', '--setenv') else 2 if option.startswith('--') and option not in ('--unshare-pid', '--die-with-parent', '--new-session') else 1
        found.append(tuple(head[index:index + width]))
        index += width
    return found


class ClaudeWorkerCommandTest(unittest.TestCase):
    def test_claude_runs_the_bound_helper_inside_the_sandbox(self):
        args = build('claude', '/var/www/html/lib')
        self.assertEqual(args[-1], '/run/claude-helper')
        found = mounts(args)
        self.assertIn(('--ro-bind', worker.HELPER, '/run/claude-helper'), found)
        # The helper must be mounted after /run becomes a fresh tmpfs, or the tmpfs hides it.
        self.assertGreater(found.index(('--ro-bind', worker.HELPER, '/run/claude-helper')), found.index(('--tmpfs', '/run')))
        self.assertEqual(args[args.index('/usr/bin/setpriv'):][:3], ['/usr/bin/setpriv', '--reuid', '994'])

    def test_workspace_under_root_is_the_only_visible_part_of_root(self):
        found = mounts(build('claude', '/root/lib'))
        self.assertIn(('--tmpfs', '/root'), found)
        self.assertIn(('--ro-bind', '/root/lib', '/root/lib'), found)
        self.assertGreater(found.index(('--ro-bind', '/root/lib', '/root/lib')), found.index(('--tmpfs', '/root')))
        self.assertIn(('--chdir', '/root/lib'), found)

    def test_workspace_outside_root_adds_nothing(self):
        found = mounts(build('claude', '/var/www/html/lib'))
        self.assertNotIn(('--tmpfs', '/root'), found)

    def test_codex_keeps_its_cli_and_gets_no_helper(self):
        args = build('codex', '/root/lib')
        self.assertNotIn('/run/claude-helper', args)
        self.assertIn('/opt/codex-web/bin/codex', args)
        self.assertIn(('--tmpfs', '/root'), mounts(args))

    def test_default_workspace_is_the_lib_checkout(self):
        self.assertEqual(Path(worker.os.environ['LIB_LLM_WORKSPACE']), Path(__file__).resolve().parents[2])


if __name__ == '__main__':
    unittest.main()
