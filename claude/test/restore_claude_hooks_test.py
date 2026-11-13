import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'ops/restore-claude-hooks.sh'
RESTORE = Path(__file__).parents[1] / 'ops/restore-claude-host.sh'


class RestoreClaudeHooksTest(unittest.TestCase):
    """The main Worker repo's Claude Code hooks (.claude/settings.json) need their scripts and node_modules."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        (self.repo / '.claude').mkdir(parents=True)
        (self.repo / 'scripts').mkdir()
        hooks = {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
            {'type': 'command', 'command': 'node "${CLAUDE_PROJECT_DIR:-.}/scripts/guard-a.js"'}]}],
                 'Stop': [{'hooks': [{'type': 'command', 'command': 'node "${CLAUDE_PROJECT_DIR:-.}/scripts/guard-b.js"'}]}]}
        (self.repo / '.claude/settings.json').write_text(json.dumps({'hooks': hooks}))
        (self.repo / 'scripts/guard-a.js').write_text("'use strict';\n")
        (self.repo / 'scripts/guard-b.js').write_text("'use strict';\n")
        (self.repo / 'package-lock.json').write_text('{}')
        # npm stub: records the call and creates node_modules like `npm ci` would.
        self.bin = Path(self.tmp.name) / 'bin'
        self.bin.mkdir()
        self.npm_log = Path(self.tmp.name) / 'npm.log'
        npm = self.bin / 'npm'
        npm.write_text(f'#!/bin/sh\necho "$*" >> {self.npm_log}\nmkdir -p node_modules/.bin\n')
        npm.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self):
        env = {'PATH': f'{self.bin}:{os.environ["PATH"]}'}
        return subprocess.run(['sh', str(SCRIPT), str(self.repo)], env=env, capture_output=True, text=True)

    def test_replaces_a_node_modules_symlink_that_points_to_itself(self):
        (self.repo / 'node_modules').symlink_to(self.repo / 'node_modules')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / 'node_modules').is_symlink())
        self.assertTrue((self.repo / 'node_modules').is_dir())
        self.assertIn('ci', self.npm_log.read_text())

    def test_leaves_a_working_node_modules_alone(self):
        (self.repo / 'node_modules').mkdir()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.npm_log.exists())

    def test_reports_each_hook_script(self):
        (self.repo / 'node_modules').mkdir()
        result = self.run_script()
        self.assertIn('OK scripts/guard-a.js', result.stdout)
        self.assertIn('OK scripts/guard-b.js', result.stdout)

    def test_a_missing_or_broken_hook_script_fails(self):
        (self.repo / 'node_modules').mkdir()
        (self.repo / 'scripts/guard-a.js').unlink()
        (self.repo / 'scripts/guard-b.js').write_text('function (\n')
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('NG scripts/guard-a.js', result.stdout)
        self.assertIn('NG scripts/guard-b.js', result.stdout)

    def test_a_missing_repo_is_reported_without_failing(self):
        # The repo is not part of every container; its absence must not stop the rest of startup.
        env = {'PATH': f'{self.bin}:{os.environ["PATH"]}'}
        result = subprocess.run(['sh', str(SCRIPT), str(self.repo / 'absent')], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('skip', result.stdout)

    def test_host_restore_runs_the_hook_restore(self):
        self.assertIn('"$HERE/restore-claude-hooks.sh"', RESTORE.read_text())


if __name__ == '__main__':
    unittest.main()
