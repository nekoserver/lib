import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('worker', Path(__file__).parents[1] / 'ops/llm_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class OutputLimitTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
