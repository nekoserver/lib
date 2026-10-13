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
