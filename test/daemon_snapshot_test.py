import importlib.util
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('daemon_snapshot', Path(__file__).parents[1] / 'ops/daemon_snapshot.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

class DaemonSnapshotTest(unittest.TestCase):
    def test_stopped_process_does_not_probe(self):
        with patch.object(monitor, 'probe') as probe:
            result = monitor.check_service(monitor.SERVICES[0], [])
        self.assertEqual('stopped', result['state'])
        probe.assert_not_called()

    def test_live_process_with_failed_response_is_degraded(self):
        rows = [{'comm':'apache2','argv':['apache2','--secret=do-not-publish'], 'pid':42,'age':10}]
        with patch.object(monitor, 'probe', side_effect=socket.timeout()):
            result = monitor.check_service(monitor.SERVICES[0], rows)
        self.assertEqual('degraded', result['state'])
        self.assertEqual([42], result['pids'])
        self.assertNotIn('argv', result)
        self.assertNotIn('secret', str(result))

    def test_permission_failure_is_unknown(self):
        rows = [{'comm':'apache2','argv':['apache2'], 'pid':42,'age':10}]
        with patch.object(monitor, 'probe', side_effect=PermissionError()):
            result = monitor.check_service(monitor.SERVICES[0], rows)
        self.assertEqual('unknown', result['state'])

    def test_other_caddy_process_is_not_origin_proxy(self):
        rows = [{'comm':'caddy','argv':['caddy','--config','/elsewhere/Caddyfile'], 'pid':42,'age':10}]
        result = monitor.check_service(monitor.SERVICES[1], rows)
        self.assertEqual('stopped', result['state'])

    def test_stale_cache_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            path.write_text('[]')
            with patch.object(monitor.time, 'time', return_value=path.stat().st_mtime+121):
                with self.assertRaises(ValueError):
                    monitor.probe('cache', path)

    def test_snapshot_publish_is_valid_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            with patch.object(monitor, 'CACHE', path):
                monitor.publish({'scope':'この VM'})
            self.assertIn('この VM', path.read_text())
            self.assertEqual(0o644, path.stat().st_mode & 0o777)

if __name__ == '__main__':
    unittest.main()
