import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parents[1] / 'ops/llm_worker_claude.py'
spec = importlib.util.spec_from_file_location('llm_worker_muse', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
base = worker.llm_worker


def fake_nc(status, body, seen):
    """Stand in for `tailscale nc`: answer one HTTP request on the socket it is handed."""
    def popen(args, stdin, stdout, stderr):
        seen['args'] = args
        remote = stdin.dup()

        def serve():
            with remote:
                data = b''
                while b'\r\n\r\n' not in data:
                    data += remote.recv(65536)
                head, _, rest = data.partition(b'\r\n\r\n')
                length = int([line for line in head.split(b'\r\n') if line.lower().startswith(b'content-length')][0].split(b':')[1])
                while len(rest) < length:
                    rest += remote.recv(65536)
                seen['head'], seen['body'] = head.decode(), json.loads(rest)
                remote.sendall(f'HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
        threading.Thread(target=serve, daemon=True).start()
        return MagicMock()
    return popen


def answer(status=200, body=b'{}', seen=None):
    return patch.object(worker.subprocess, 'Popen', fake_nc(status, body, {} if seen is None else seen))


class MuseAskTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(worker, 'MUSE_API_KEY', 'test-key')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sends_the_prompt_with_the_key_and_returns_the_reply(self):
        seen = {}
        body = json.dumps({'model': 'muse-1', 'choices': [{'message': {'content': '六日'}}]}).encode()
        with answer(body=body, seen=seen):
            self.assertEqual(worker.ask_muse('今日は何日？'), ('六日', 'muse-1'))
        self.assertEqual(seen['args'], ['tailscale', 'nc', 'muse-vm', '8080'])
        self.assertIn('POST /v1/chat/completions ', seen['head'])
        self.assertIn('Authorization: Bearer test-key', seen['head'])
        self.assertEqual(seen['body'], {'model': 'muse', 'messages': [{'role': 'user', 'content': '今日は何日？'}]})

    def test_surrounding_whitespace_is_removed_from_the_reply(self):
        body = json.dumps({'model': 'muse-1', 'choices': [{'message': {'content': '\n金曜日です。\n二行目\n\n'}}]}).encode()
        with answer(body=body):
            self.assertEqual(worker.ask_muse('今日は何曜日？'), ('金曜日です。\n二行目', 'muse-1'))

    def test_http_failures_map_to_error_codes(self):
        for status, body, code in ((401, b'{}', 'muse_authentication_failed'), (429, b'{}', 'muse_usage_limit'),
                                   (500, b'{}', 'muse_execution_failed'), (200, b'not json', 'muse_execution_failed'),
                                   (200, b'{"choices":[{"message":{"content":""}}]}', 'muse_execution_failed')):
            with self.subTest(status=status, body=body), answer(status, body):
                with self.assertRaisesRegex(worker.MuseError, code):
                    worker.ask_muse('x')

    def test_closed_connection_is_a_connection_failure(self):
        def popen(args, stdin, stdout, stderr):
            return MagicMock()  # the remote end closes, as when `tailscale nc` cannot dial
        with patch.object(worker.subprocess, 'Popen', popen):
            with self.assertRaisesRegex(worker.MuseError, 'muse_connection_failed'):
                worker.ask_muse('x')


class MuseJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(base, 'STATE', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self, **ask):
        with patch.object(worker, 'MUSE_API_KEY', 'test-key'), patch.object(worker, 'ask_muse', **ask):
            job = base.submit('muse', '今日は何日？')
            self.assertEqual(job['ask_status'], 'pending')
            queued, prompt = base.JOBS.get_nowait()
            base.JOBS.task_done()
            base.execute(queued, prompt)
        return base.lookup(job['ask_id'])

    def test_a_job_can_be_polled_until_done(self):
        job = self.run_job(return_value=('六日', 'muse-1'))
        self.assertEqual((job['ask_status'], job['reply'], job['via'], job['llm_model']), ('done', '六日', 'muse', 'muse-1'))

    def test_a_done_job_uses_the_model_key_the_cgi_reads(self):
        # tunnels_lib.rb reads meta['model']; llm_model alone never reaches the Worker.
        job = self.run_job(return_value=('六日', 'muse-1'))
        self.assertEqual(job['model'], 'muse-1')

    def test_failures_are_reported_on_the_job(self):
        for raised, code in ((worker.MuseError('muse_usage_limit'), 'muse_usage_limit'), (TimeoutError(), 'llm_timeout'),
                             (OSError(), 'muse_connection_failed')):
            with self.subTest(code=code):
                job = self.run_job(side_effect=raised)
                self.assertEqual((job['ask_status'], job['ask_error']), ('failed', code))

    def test_without_a_key_nothing_is_queued(self):
        with patch.object(worker, 'MUSE_API_KEY', ''):
            result = base.submit('muse', 'x')
        self.assertEqual(result['ask_error'], 'muse_not_authenticated')
        self.assertTrue(base.JOBS.empty())

    def test_other_engines_keep_the_original_paths(self):
        self.assertEqual(base.submit('nemotron', 'x')['ask_error'], 'unsupported_engine')

    def test_the_key_is_not_left_for_child_processes(self):
        code = ("import importlib.util, os, sys;"
                "s = importlib.util.spec_from_file_location('w', sys.argv[1]);"
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m);"
                "print(m.MUSE_API_KEY, 'MUSE_API_KEY' in os.environ)")
        out = subprocess.run([sys.executable, '-c', code, str(SCRIPT)], capture_output=True, text=True, check=True,
                             env={**os.environ, 'MUSE_API_KEY': 'test-key'}).stdout
        self.assertEqual(out.split(), ['test-key', 'False'])


if __name__ == '__main__':
    unittest.main()
