import json
import subprocess
import importlib.util
from pathlib import Path
import sys
import os
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('worker', Path(__file__).parents[1] / 'ops/llm_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class OutputLimitTest(unittest.TestCase):
    def test_claude_resume_lists_saved_metadata_without_messages_or_symlinks(self):
        with tempfile.TemporaryDirectory() as home:
            project = Path(home) / '.claude/projects/example'
            project.mkdir(parents=True)
            session = '12345678-1234-1234-1234-123456789abc'
            event = {'type': 'user', 'sessionId': session, 'cwd': '/example', 'message': 'private prompt'}
            (project / (session + '.jsonl')).write_text(json.dumps(event)+'\n')
            (project / '87654321-1234-1234-1234-123456789abc.jsonl').symlink_to(project / (session + '.jsonl'))
            output = subprocess.check_output([sys.executable, '-c', worker.CLAUDE_RESUME_SCRIPT], env={**os.environ, 'HOME': home}, text=True)
            self.assertIn(session, output)
            self.assertIn('/example', output)
            self.assertNotIn('private prompt', output)
            self.assertNotIn('87654321', output)
            self.assertIn('--no-session-persistence', output)
            self.assertIn('再開・送信は行いません', output)

    def test_claude_resume_empty_store_and_readonly_dispatch(self):
        with tempfile.TemporaryDirectory() as home:
            output = subprocess.check_output([sys.executable, '-c', worker.CLAUDE_RESUME_SCRIPT], env={**os.environ, 'HOME': home}, text=True)
            self.assertIn('見つかりません', output)
        with patch.object(worker, 'run_control', return_value='saved sessions') as control, patch.object(worker, 'run_bounded') as model:
            self.assertEqual(worker.execute_claude_control('/resume'), (0, '', 'saved sessions'))
            self.assertIn('未対応', worker.execute_claude_control('/resume arbitrary-id')[2])
            control.assert_called_once_with(['/usr/bin/python3', '-c', worker.CLAUDE_RESUME_SCRIPT])
            model.assert_not_called()

    def test_claude_context_and_config_use_native_commands_without_model_turns(self):
        for name, note in [('/context', '新規起動'), ('/config', '設定変更は行いません')]:
            event = {'type': 'result', 'local_command': name[1:], 'num_turns': 0, 'result': 'actual CLI output'}
            with self.subTest(name=name), patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(event))) as run:
                code, _, reply = worker.execute_claude_control(name)
                self.assertEqual(code, 0)
                self.assertIn('actual CLI output', reply)
                self.assertIn(note, reply)
                run.assert_called_once_with(['helper'], name)

    def test_claude_hooks_reports_disabled_state_without_exposing_commands(self):
        init = {'type': 'system', 'subtype': 'init'}
        event = {'type': 'result', 'local_command': 'model', 'num_turns': 0, 'result': 'native output'}
        settings = {'hooks': {'PreToolUse': [{'hooks': [{'command': 'secret command'}]}]}}
        with patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(init)+'\n'+json.dumps(event))), patch.object(worker.Path, 'is_file', return_value=True), patch.object(worker.Path, 'read_text', return_value=json.dumps(settings)):
            code, _, reply = worker.execute_claude_control('/hooks')
            self.assertEqual(code, 0)
            self.assertIn('disableAllHooks=true', reply)
            self.assertIn('PreToolUse: 1', reply)
            self.assertNotIn('secret command', reply)

    def test_new_claude_commands_reject_model_results_and_mutating_arguments(self):
        event = {'type': 'result', 'local_command': 'context', 'num_turns': 1, 'result': 'invented output'}
        with patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(event))):
            self.assertEqual(worker.execute_claude_control('/context'), (1, '', None))
            self.assertEqual(worker.execute_claude_control('/hooks'), (1, '', None))
        with patch.object(worker, 'run_bounded') as run:
            for name in ['/config model=opus', '/hooks enable', '/context extra']:
                self.assertIn('未対応', worker.execute_claude_control(name)[2])
            run.assert_not_called()

    def test_claude_control_commands_and_permission_alias(self):
        init = {'type': 'system', 'subtype': 'init', 'model': 'actual-model',
                'permissionMode': 'dontAsk', 'cwd': '/workspace', 'claude_code_version': 'actual-version', 'mcp_servers': []}
        for name in ['/mcp', '/model', '/agents', '/status', '/permission', '/permissions']:
            native = name if name in ('/mcp', '/model', '/agents') else '/model'
            event = {'type': 'result', 'local_command': native[1:], 'num_turns': 0, 'result': 'native output'}
            with self.subTest(name=name), patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(init)+'\n'+json.dumps(event))) as run, patch.object(worker.Path, 'is_file', return_value=False):
                code, _, reply = worker.execute_claude_control(name)
                self.assertEqual(code, 0)
                run.assert_called_once_with(['helper'], native)
                if name == '/status':
                    self.assertIn('actual-model', reply)
                    self.assertIn('/workspace', reply)
                elif name.startswith('/permission'):
                    self.assertIn('dontAsk', reply)
                    self.assertIn('変更しません', reply)
                else:
                    self.assertIn('native output', reply)
        with patch.object(worker, 'run_control') as help_cli, patch.object(worker, 'run_bounded') as model:
            code, _, reply = worker.execute_claude_control('/help')
            self.assertEqual(code, 0)
            self.assertIn('Claude 連携ヘルプ', reply)
            self.assertIn('claude_prompt="/status"', reply)
            self.assertIn('情報表示のみ', reply)
            for name in ['/cost', '/status', '/model', '/context', '/mcp', '/agents', '/hooks', '/permissions', '/permission', '/config', '/resume', '/help']:
                self.assertIn(name, reply)
            self.assertLess(len(reply), 800)
            help_cli.assert_not_called()
            model.assert_not_called()

    def test_claude_dialog_adapters_require_init_and_reject_mutating_args(self):
        event = {'type': 'result', 'local_command': 'model', 'num_turns': 0, 'result': 'native output'}
        with patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(event))):
            self.assertEqual(worker.execute_claude_control('/status'), (1, '', None))
            self.assertEqual(worker.execute_claude_control('/permission'), (1, '', None))
        with patch.object(worker, 'run_bounded') as run:
            for name in ['/model opus', '/mcp disable all', '/permissions allow Bash']:
                self.assertIn('未対応', worker.execute_claude_control(name)[2])
            run.assert_not_called()

    def test_claude_cost_returns_native_output_without_codex_or_model_turn(self):
        event = {'type': 'result', 'local_command': 'cost', 'num_turns': 0,
                 'is_error': False, 'result': 'Current session: 20% used'}
        job = {'ask_id': 'test', 'via': 'claude'}
        with patch.object(worker, 'save'), patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(event))) as native, patch.object(worker, 'read_codex_limits') as codex:
            worker.execute(job, ' /COST ')
            self.assertEqual(job['ask_status'], 'done')
            self.assertIn(event['result'], job['reply'])
            native.assert_called_once_with(['helper'], '/cost')
            codex.assert_not_called()

    def test_claude_cost_rejects_model_answers_errors_and_missing_results(self):
        for event in [
            {'type': 'result', 'num_turns': 1, 'result': 'invented cost'},
            {'type': 'result', 'local_command': 'cost', 'num_turns': 1, 'result': 'invented cost'},
            {'type': 'result', 'local_command': 'cost', 'num_turns': 0, 'is_error': True, 'result': 'error'},
            {'type': 'result', 'local_command': 'cost', 'num_turns': 0},
        ]:
            with self.subTest(event=event), patch.object(worker, 'command', return_value=['helper']), patch.object(worker, 'run_bounded', return_value=(0, json.dumps(event))):
                self.assertEqual(worker.execute_claude_control('/cost'), (1, '', None))
        with patch.object(worker, 'run_bounded') as native:
            self.assertIn('未対応', worker.execute_claude_control('/cost extra')[2])
            native.assert_not_called()

    def test_inventory_commands_use_readonly_sources_not_model(self):
        def rpc(method, params=None, **kwargs):
            if method == 'mcpServerStatus/list':
                return {'data': [{'name': 'example', 'authStatus': 'loggedIn', 'tools': {'find': {'description': 'find things'}}}], 'nextCursor': None}
            if method == 'app/list':
                return {'data': [{'name': 'Example App', 'isEnabled': True, 'isAccessible': True}], 'nextCursor': None}
            if method == 'app/installed':
                return {'apps': [{'id': 'example', 'runtimeName': 'Example App', 'enabled': True, 'callable': True}]}
            raise AssertionError(method)
        with patch.object(worker, 'read_codex_rpc', side_effect=rpc), patch.object(worker, 'run_control', return_value='{"plugins":[{"name":"example","enabled":true}]}'), patch.object(worker, 'run_bounded') as model:
            self.assertIn('example', worker.execute_codex('/mcp')[2])
            self.assertIn('find', worker.execute_codex('/mcp verbose')[2])
            self.assertIn('Example App', worker.execute_codex('/apps')[2])
            self.assertIn('example', worker.execute_codex('/plugins')[2])
            self.assertIn('端末', worker.execute_codex('/ps')[2])
            model.assert_not_called()

    def test_diff_includes_staged_unstaged_untracked_and_is_bounded(self):
        with patch.object(worker, 'run_control', return_value='diff --git a/example b/example') as control:
            self.assertIn('diff --git', worker.execute_codex('/diff')[2])
            self.assertIn('ls-files', control.call_args.args[0][-1])

    def test_claude_usage_does_not_read_codex_account_or_start_model(self):
        job = {'ask_id': 'test', 'via': 'claude'}
        with patch.object(worker, 'save'), patch.object(worker, 'run_bounded') as model, patch.object(worker, 'read_codex_limits') as quota:
            worker.execute(job, '/usage')
            self.assertEqual(job['ask_status'], 'done')
            self.assertIn('Claude', job['reply'])
            self.assertIn('未対応', job['reply'])
            model.assert_not_called()
            quota.assert_not_called()

    def test_commands_preserve_distinct_meanings_without_model_turn(self):
        data = {'rateLimits': {'primary': {'usedPercent': 25, 'windowDurationMins': 300, 'resetsAt': 0}}}
        def rpc(method, params=None):
            if method == 'config/read':
                return {'config': {'model': 'configured-model'}}
            if method == 'account/usage/read':
                return {'summary': {'lifetimeTokens': 1234}, 'dailyUsageBuckets': [{'startDate': '2026-10-14', 'tokens': 100}]}
            raise AssertionError(method)
        with patch.object(worker, 'read_codex_limits', return_value=data), patch.object(worker, 'read_codex_rpc', side_effect=rpc), patch.object(worker, 'run_bounded') as model:
            status = worker.execute_codex('/status')[2]
            self.assertIn('configured-model', status)
            self.assertIn('残り 75%', status)
            self.assertIn('セッションID', status)
            menu = worker.execute_codex('/usage')[2]
            self.assertIn('/usage daily', menu)
            self.assertNotIn('残り 75%', menu)
            self.assertEqual(menu, worker.execute_codex('./usage')[2])
            self.assertIn('1234', worker.execute_codex('/usage cumulative')[2])
            self.assertIn('2026-10-14: 100', worker.execute_codex('/usage daily')[2])
            self.assertIn('2026-W42: 100', worker.execute_codex('/usage weekly')[2])
            self.assertIn('未対応', worker.execute_codex('/model')[2])
            model.assert_not_called()

    def test_usage_unavailable_does_not_invent_remaining_quota(self):
        self.assertIn('残り枠は不明', worker.format_codex_limits({}))
        with patch.object(worker, 'read_codex_limits', side_effect=ValueError('secret error')):
            reply = worker.execute_codex('/status')[2]
            self.assertIn('残り枠は不明', reply)
            self.assertNotIn('secret error', reply)

    def test_codex_reset_timestamp_preserves_seconds(self):
        reply = worker.format_codex_limits({'rateLimits': {
            'primary': {'usedPercent': 14, 'windowDurationMins': 300, 'resetsAt': 1792678476},
            'secondary': {'usedPercent': 72, 'windowDurationMins': 10080, 'resetsAt': 1793089348}}})
        self.assertIn('codex 5時間枠: 残り 86%（使用 14%）、リセット 2026-10-22 14:14:36 UTC', reply)
        self.assertIn('codex 168時間枠: 残り 28%（使用 72%）、リセット 2026-10-27 08:22:28 UTC', reply)

    def test_codex_metadata_stops_before_prompt_and_tool_output(self):
        text = 'model: gpt-6.1-sol\nreasoning effort: none\nuser\nmodel: fake\nreasoning effort: max\n'
        self.assertEqual(worker.codex_summary(text), {'model': 'gpt-6.1-sol', 'effort': 'none'})

    @unittest.skipUnless(os.geteuid() == 0 and Path(worker.HOME).is_dir(), 'VM helper home requires root')
    def test_codex_answer_cannot_follow_a_symlink(self):
        def fake_run(args, prompt):
            path = args[args.index('--output-last-message') + 1]
            os.symlink('/etc/passwd', path)
            return 0, 'model: gpt-6.1-sol\nreasoning effort: none\n'
        with patch.object(worker, 'run_bounded', fake_run):
            with self.assertRaises(OSError):
                worker.execute_codex('test')

    def test_internal_files_can_exceed_capture_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runtime-artifact'
            code, output = worker.run_bounded([
                sys.executable, '-c',
                'import sys; open(sys.argv[1], "wb").write(b"x" * 5000000); print("ok")',
                str(path),
            ], 'test')
            self.assertEqual(code, 0)
            self.assertEqual(output.strip(), 'ok')
            self.assertEqual(path.stat().st_size, 5_000_000)

    def test_excessive_cli_output_is_stopped(self):
        with self.assertRaises(OverflowError):
            worker.run_bounded([
                sys.executable, '-c', 'import sys; sys.stdout.write("x" * 5000000)',
            ], 'test')


class ConsumerRecoveryTest(unittest.TestCase):
    def test_closed_log_stream_does_not_raise(self):
        with patch('builtins.print', side_effect=BrokenPipeError):
            worker.log_event({'status': 'done'})

    def test_failed_job_does_not_stop_next_job(self):
        class StopConsumer(BaseException):
            pass
        first = {'ask_id': 'first', 'ask_status': 'pending'}
        second = {'ask_id': 'second', 'ask_status': 'pending'}
        from unittest.mock import Mock
        jobs = Mock()
        jobs.get.side_effect = [(first, 'first prompt'), (second, 'second prompt'), StopConsumer]
        with patch.object(worker, 'JOBS', jobs), \
             patch.object(worker, 'execute', side_effect=[RuntimeError('unexpected result'), None]) as execute, \
             patch.object(worker, 'save') as save, \
             patch.object(worker, 'log_event'):
            with self.assertRaises(StopConsumer):
                worker.consume()
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(jobs.task_done.call_count, 2)
            self.assertEqual(first['ask_status'], 'failed')
            self.assertEqual(first['ask_error'], 'worker_job_failed')
            save.assert_called_once_with(first)


if __name__ == '__main__':
    unittest.main()
