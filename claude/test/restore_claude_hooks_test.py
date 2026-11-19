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
            {'type': 'command', 'command': 'node "${CLAUDE_PROJECT_DIR:-.}/scripts/guard-a.js"'},
            {'type': 'command', 'command': 'node "${CLAUDE_PROJECT_DIR:-.}/scripts/claude-full-test-guard.js"'}]}],
                 'Stop': [{'hooks': [{'type': 'command', 'command': 'node "${CLAUDE_PROJECT_DIR:-.}/scripts/guard-b.js"'}]}]}
        (self.repo / '.claude/settings.json').write_text(json.dumps({'hooks': hooks}))
        (self.repo / 'scripts/guard-a.js').write_text("'use strict';\n")
        (self.repo / 'scripts/guard-b.js').write_text("'use strict';\n")
        (self.repo / 'scripts/claude-full-test-guard.js').write_text(
            "const c = JSON.parse(require('fs').readFileSync(0, 'utf8')).tool_input.command;\n"
            "process.exit(/^npx vitest run$/.test(c) ? 2 : 0);\n")
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
        env = {'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': self.tmp.name}
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
        env = {'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': self.tmp.name}
        result = subprocess.run(['sh', str(SCRIPT), str(self.repo / 'absent')], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('skip', result.stdout)

    def test_host_restore_runs_the_hook_restore(self):
        self.assertIn('"$HERE/restore-claude-hooks.sh"', RESTORE.read_text())


class UserLevelHooksTest(unittest.TestCase):
    """The repo's hooks load only in a session started inside the repo. A session started in /root
    (2026-11-19, a full `npx vitest run` went through) gets the hooks that work in any directory from
    ~/.claude/settings.json, which the restore writes after every container start."""

    GUARDS = ('claude-full-test-guard.js', 'claude-japanese-guard.js', 'claude-self-check-guard.js')
    REPO_ONLY = ('claude-push-guard.js', 'check-migration-table-registry.js')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        self.home = Path(self.tmp.name) / 'home'
        (self.repo / '.claude').mkdir(parents=True)
        (self.repo / 'scripts').mkdir()
        (self.repo / 'node_modules').mkdir()
        self.home.mkdir()

        def cmd(name):
            return {'type': 'command', 'command': f'node "${{CLAUDE_PROJECT_DIR:-.}}/scripts/{name}"'}
        hooks = {
            'PostToolUse': [{'matcher': 'Edit|Write', 'hooks': [cmd('check-migration-table-registry.js')]}],
            'PreToolUse': [{'matcher': 'Bash', 'hooks': [dict(cmd('claude-push-guard.js'), timeout=600),
                                                         cmd('claude-full-test-guard.js')]}],
            'UserPromptSubmit': [{'hooks': [cmd('claude-japanese-guard.js'), cmd('claude-self-check-guard.js')]}],
            'SessionStart': [{'hooks': [cmd('claude-japanese-guard.js'), cmd('claude-self-check-guard.js')]}],
            'Stop': [{'hooks': [cmd('claude-japanese-guard.js')]}],
        }
        (self.repo / '.claude/settings.json').write_text(json.dumps({'hooks': hooks}))
        for name in self.GUARDS + self.REPO_ONLY:
            (self.repo / 'scripts' / name).write_text("'use strict';\n")
        # Like the real guard: exit 2 for an unscoped vitest run, read from the hook input on stdin.
        (self.repo / 'scripts/claude-full-test-guard.js').write_text(
            "const c = JSON.parse(require('fs').readFileSync(0, 'utf8')).tool_input.command;\n"
            "process.exit(/^npx vitest run$/.test(c) ? 2 : 0);\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self):
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home)}
        return subprocess.run(['sh', str(SCRIPT), str(self.repo)], env=env, capture_output=True, text=True)

    def user_settings(self):
        return json.loads((self.home / '.claude/settings.json').read_text())

    def commands(self, event):
        return [h['command'] for group in self.user_settings()['hooks'].get(event, []) for h in group['hooks']]

    def test_installs_the_directory_independent_guards_with_absolute_paths(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        repo = self.repo.resolve()
        self.assertEqual(self.commands('PreToolUse'), [f'node "{repo}/scripts/claude-full-test-guard.js"'])
        self.assertEqual(self.commands('UserPromptSubmit'), [f'node "{repo}/scripts/claude-japanese-guard.js"',
                                                             f'node "{repo}/scripts/claude-self-check-guard.js"'])
        self.assertEqual(self.commands('SessionStart'), self.commands('UserPromptSubmit'))
        self.assertEqual(self.commands('Stop'), [f'node "{repo}/scripts/claude-japanese-guard.js"'])
        self.assertEqual(self.user_settings()['hooks']['PreToolUse'][0]['matcher'], 'Bash')
        self.assertIn('hooks: user level', result.stdout)

    def test_leaves_out_the_hooks_that_need_the_repo_as_working_directory(self):
        # The push guard runs git in its working directory; the migration check posts to the Worker.
        self.run_script()
        text = json.dumps(self.user_settings())
        for name in self.REPO_ONLY:
            self.assertNotIn(name, text)
        self.assertNotIn('PostToolUse', self.user_settings()['hooks'])

    def test_keeps_other_settings_and_hooks_and_does_not_duplicate(self):
        (self.home / '.claude').mkdir()
        mine = {'matcher': 'Read', 'hooks': [{'type': 'command', 'command': 'echo mine'}]}
        (self.home / '.claude/settings.json').write_text(json.dumps({'theme': 'auto', 'hooks': {'PreToolUse': [mine]}}))
        self.run_script()
        self.run_script()
        settings = self.user_settings()
        self.assertEqual(settings['theme'], 'auto')
        self.assertIn(mine, settings['hooks']['PreToolUse'])
        self.assertEqual(len(self.commands('PreToolUse')), 2)
        self.assertEqual(len(self.commands('Stop')), 1)

    def test_a_broken_guard_is_not_installed(self):
        (self.repo / 'scripts/claude-full-test-guard.js').write_text('function (\n')
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('claude-full-test-guard.js', json.dumps(self.user_settings()))
        self.assertEqual(len(self.commands('Stop')), 1)

    def test_checks_that_the_installed_full_test_guard_really_blocks(self):
        # Scripts that exist and parse are not hooks that work (2026-11-19): run the installed command.
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('hooks: works: the full test guard stops `npx vitest run` outside the repo', result.stdout)

    def test_a_guard_that_does_not_block_fails(self):
        (self.repo / 'scripts/claude-full-test-guard.js').write_text("process.exit(0);\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('hooks: NG the full test guard did not stop `npx vitest run`', result.stdout)

    def test_host_restore_says_it_installs_the_user_level_hooks(self):
        self.assertIn('~/.claude/settings.json', RESTORE.read_text())


if __name__ == '__main__':
    unittest.main()
