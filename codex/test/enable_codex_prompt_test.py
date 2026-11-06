import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'ops/enable-codex-prompt.sh'

class EnableCodexPromptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = root = Path(self.tmp.name)
        self.bin = root / 'codex'
        self.bin.write_text('#!/bin/sh\n')
        self.bin.chmod(0o755)
        self.source = root / 'source-auth.json'
        self.source.write_text('{"from":"source"}')
        self.link, self.home = root / 'opt/bin/codex', root / 'home/.codex'

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, **env):
        base = {'PATH': os.environ['PATH'], 'LIB_RESTORE_NO_START': '1',
                'LIB_CODEX_SOCKET': str(self.root / 'no-worker.sock'),
                'LIB_CODEX_BIN': str(self.bin), 'LIB_CODEX_LINK': str(self.link),
                'LIB_CODEX_HOME': str(self.home), 'LIB_CODEX_AUTH_SOURCE': str(self.source),
                'LIB_CODEX_USER': pwd.getpwuid(os.getuid()).pw_name}
        return subprocess.run(['sh', str(SCRIPT)], env={**base, **env}, capture_output=True, text=True)

    def test_does_not_need_the_claude_secrets(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.assertFalse('claude' in SCRIPT.read_text().replace('claude/ops/restore-claude-host.sh', ''))

    def test_asks_for_the_claude_setup_when_the_worker_is_missing(self):
        result = self.run_script(LIB_RESTORE_NO_START='')
        self.assertEqual(result.returncode, 1)
        self.assertIn('run claude/ops/restore-claude-host.sh first', result.stderr)
        self.assertFalse(self.link.exists())

    def test_links_the_codex_binary_and_keeps_the_home_private(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(os.readlink(self.link), str(self.bin))
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o700)

    def test_copies_the_login_privately(self):
        self.assertEqual(self.run_script().returncode, 0)
        auth = self.home / 'auth.json'
        self.assertEqual(auth.read_text(), '{"from":"source"}')
        self.assertEqual(auth.stat().st_mode & 0o777, 0o600)

    def test_keeps_an_existing_login(self):
        self.home.mkdir(parents=True)
        (self.home / 'auth.json').write_text('{"from":"existing"}')
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.home / 'auth.json').read_text(), '{"from":"existing"}')
        self.assertIn('keeping the login', result.stdout)

    def test_warns_without_a_login(self):
        self.source.unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('no Codex login', result.stderr)
        self.assertFalse((self.home / 'auth.json').exists())

    def test_changes_nothing_without_the_binary(self):
        self.bin.unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn('No Codex binary', result.stderr)
        self.assertFalse(self.link.exists())

    def test_is_idempotent(self):
        self.run_script()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(os.readlink(self.link), str(self.bin))


if __name__ == '__main__':
    unittest.main()
