import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops'))
from chat_websocket import load_secret


class SecretEnvironmentTest(unittest.TestCase):
    def test_origin_secret_takes_precedence(self):
        with patch.dict(os.environ, {'ORIGIN_HMAC_SECRET': ' origin-key \n', 'HMAC_SECRET': 'other-key'}, clear=True):
            self.assertEqual(load_secret(paths=()), b'origin-key')

    def test_blank_origin_uses_legacy_environment(self):
        with patch.dict(os.environ, {'ORIGIN_HMAC_SECRET': ' ', 'HMAC_SECRET': ' fallback-key '}, clear=True):
            self.assertEqual(load_secret(paths=()), b'fallback-key')

    def test_missing_environment_fails_even_when_secret_file_exists(self):
        with patch.dict(os.environ, {}, clear=True), patch('pathlib.Path.read_text', return_value='stale-file-key') as read:
            with self.assertRaises(RuntimeError):
                load_secret(paths=())
            read.assert_not_called()


class DualConfigTest(unittest.TestCase):
    def test_both_keys_authenticate_and_sessions_survive_mismatch(self):
        import hashlib
        import hmac
        import tempfile
        from chat_hmac import matches
        from chat_session import issue, valid
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            primary = Path(directory) / 'primary.env'
            fallback = Path(directory) / 'fallback.env'
            primary.write_text("ORIGIN_HMAC_SECRET='primary key'\n")
            fallback.write_text("ORIGIN_HMAC_SECRET='fallback key'\n")
            with self.assertLogs(level='WARNING') as logs:
                keys = load_secret(paths=(primary, fallback))
            self.assertNotIn('primary key', '\n'.join(logs.output))
            self.assertNotIn('fallback key', '\n'.join(logs.output))
            for key in (b'primary key', b'fallback key'):
                signature = hmac.new(key, b'request', hashlib.sha256).hexdigest()
                self.assertTrue(matches(keys, b'request', signature))
                self.assertFalse(matches(keys, b'changed request', signature))
                self.assertTrue(valid(keys, issue(key, 'https://example.test'), 'https://example.test'))
            self.assertFalse(valid(keys, issue(b'unknown', 'https://example.test'), 'https://example.test'))
            primary.unlink()
            self.assertEqual(load_secret(paths=(primary, fallback)), b'fallback key')
            fallback.write_text('ORIGIN_HMAC_SECRET=\n')
            with self.assertRaises(RuntimeError):
                load_secret(paths=(primary, fallback))

    def test_duplicates_are_not_reported_as_mismatch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            config = Path(directory) / 'key.env'
            config.write_text('ORIGIN_HMAC_SECRET=same-key\nHMAC_SECRET=same-key\n')
            with self.assertNoLogs(level='WARNING'):
                self.assertEqual(load_secret(paths=(config, config)).keys, (b'same-key',))
