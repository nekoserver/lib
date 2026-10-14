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
