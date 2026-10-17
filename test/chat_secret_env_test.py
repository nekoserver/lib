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
            self.assertEqual(load_secret(), b'origin-key')

    def test_blank_origin_uses_legacy_environment(self):
        with patch.dict(os.environ, {'ORIGIN_HMAC_SECRET': ' ', 'HMAC_SECRET': ' fallback-key '}, clear=True):
            self.assertEqual(load_secret(), b'fallback-key')

    def test_missing_environment_fails_even_when_secret_file_exists(self):
        with patch.dict(os.environ, {}, clear=True), patch('pathlib.Path.read_text', return_value='stale-file-key') as read:
            with self.assertRaises(RuntimeError):
                load_secret()
            read.assert_not_called()
